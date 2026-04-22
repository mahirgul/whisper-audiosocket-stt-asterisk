"""
audiosocket_server.py

Async TCP server implementing the Asterisk AudioSocket protocol.
Handles multiple concurrent connections, VAD-based chunking, and
feeds each audio chunk through the processing pipeline.

AudioSocket protocol (Asterisk):
  Each frame: [type: 1 byte] [length: 2 bytes big-endian] [payload: length bytes]
  type 0x01 — UUID (16 bytes, sent once at connection start)
  type 0x10 — Audio payload (raw PCM, slin format)
  type 0x00 — Hangup / end-of-stream
"""

import asyncio
import json
import os
import struct
import traceback
import uuid as _uuid
from datetime import datetime, timezone

import audiosocket_processor as asp

# ---------------------------------------------------------------------------
# Global state (shared with web.py via this module's namespace)
# ---------------------------------------------------------------------------

_server: asyncio.AbstractServer | None = None
_config: dict = {}
_active_connections: dict[str, dict] = {}   # uuid → session meta
_event_queue: asyncio.Queue = asyncio.Queue()  # SSE event bus
_BASE_DIR: str = ""   # Set at startup by web.py (project root)

# AudioSocket frame type constants
FRAME_HANGUP = 0x00
FRAME_UUID   = 0x01
FRAME_AUDIO  = 0x10


# ---------------------------------------------------------------------------
# Public interface (called by web.py)
# ---------------------------------------------------------------------------

def set_base_dir(base_dir: str) -> None:
    global _BASE_DIR
    _BASE_DIR = base_dir


def get_status() -> dict:
    return {
        "listening": _server is not None and _server.is_serving(),
        "port": _config.get("port", 9092),
        "active_connections": len(_active_connections),
        "sessions": list(_active_connections.values()),
    }


def get_active_connections() -> dict:
    return _active_connections


async def get_event_queue() -> asyncio.Queue:
    return _event_queue


def load_config(config_path: str) -> dict:
    """Load audiosocket.json; return defaults if file missing."""
    defaults = {
        "port": 9092,
        "target_lang": "en",
        "voice_type": "M",
        "input_sample_rate": 8000,
        "input_channels": 1,
        "input_sample_width": 2,
        "vad_silence_threshold_ms": 1500,
        "vad_min_chunk_ms": 1000,
        "delivery": {
            "enabled": False,
            "url": "http://your-server/api/receive-audio",
            "method": "POST",
            "field_name": "audio",
            "extra_fields": {"session_id": "{uuid}", "lang": "{target_lang}"},
            "timeout_s": 10
        }
    }
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        # Merge with defaults for missing keys
        for k, v in defaults.items():
            if k not in loaded:
                loaded[k] = v
        return loaded
    return defaults


async def start_server(config_path: str) -> None:
    """Start (or restart) the AudioSocket TCP server."""
    global _server, _config

    # Stop existing server if running
    if _server is not None:
        _server.close()
        await _server.wait_closed()
        _server = None
        print("[AudioSocket] Previous server stopped.")

    _config = load_config(config_path)
    port = _config.get("port", 9092)

    _server = await asyncio.start_server(
        _connection_handler,
        host="0.0.0.0",
        port=port
    )
    print(f"[AudioSocket] Listening on port {port}")
    asyncio.ensure_future(_server.serve_forever())


async def stop_server() -> None:
    global _server
    if _server:
        _server.close()
        await _server.wait_closed()
        _server = None


# ---------------------------------------------------------------------------
# Connection handler
# ---------------------------------------------------------------------------

async def _connection_handler(reader: asyncio.StreamReader,
                               writer: asyncio.StreamWriter) -> None:
    remote = writer.get_extra_info("peername")
    session_id = None
    start_time = datetime.now(timezone.utc)

    try:
        # Read the UUID frame first
        session_id = await _read_uuid_frame(reader)
        if session_id is None:
            print(f"[AudioSocket] No UUID received from {remote}. Closing.")
            writer.close()
            return

        print(f"[AudioSocket] Connection from {remote} — session {session_id}")

        out_dir = _session_dir(session_id)
        os.makedirs(out_dir, exist_ok=True)

        # Register active connection
        _active_connections[session_id] = {
            "uuid": session_id,
            "remote": str(remote),
            "started": start_time.isoformat(),
            "chunks": 0,
            "status": "active"
        }

        await _emit("connection_open", {
            "uuid": session_id,
            "remote_addr": str(remote),
            "timestamp": start_time.isoformat()
        })

        # Save session metadata
        await _save_session_meta(session_id, out_dir, "active")

        # Audio accumulation
        sample_rate  = _config.get("input_sample_rate", 8000)
        channels     = _config.get("input_channels", 1)
        sample_width = _config.get("input_sample_width", 2)
        silence_ms   = _config.get("vad_silence_threshold_ms", 1500)
        min_ms       = _config.get("vad_min_chunk_ms", 1000)

        # bytes per ms of audio
        bytes_per_ms = (sample_rate * channels * sample_width) // 1000
        silence_bytes_threshold = silence_ms * bytes_per_ms
        min_chunk_bytes = min_ms * bytes_per_ms

        audio_buf = bytearray()
        silence_buf = bytearray()
        chunk_idx = 0

        while True:
            frame_type, payload = await _read_frame(reader)

            if frame_type is None or frame_type == FRAME_HANGUP:
                # Flush remaining audio
                if len(audio_buf) >= min_chunk_bytes:
                    chunk_idx += 1
                    await _process_chunk(session_id, chunk_idx, bytes(audio_buf),
                                         out_dir)
                break

            if frame_type == FRAME_AUDIO:
                # Simple VAD: detect silence by checking RMS energy
                is_silent = _is_silent(payload, sample_width)

                if is_silent:
                    silence_buf.extend(payload)
                    if len(silence_buf) >= silence_bytes_threshold:
                        # Silence threshold reached — flush audio chunk
                        if len(audio_buf) >= min_chunk_bytes:
                            chunk_idx += 1
                            _active_connections[session_id]["chunks"] = chunk_idx
                            await _process_chunk(session_id, chunk_idx,
                                                 bytes(audio_buf), out_dir)
                            audio_buf.clear()
                        silence_buf.clear()
                else:
                    # Non-silent audio — include accumulated silence + new audio
                    audio_buf.extend(silence_buf)
                    audio_buf.extend(payload)
                    silence_buf.clear()

        # Mark session closed
        duration_s = (datetime.now(timezone.utc) - start_time).total_seconds()
        _active_connections.pop(session_id, None)
        await _save_session_meta(session_id, out_dir, "completed",
                                 total_chunks=chunk_idx,
                                 duration_s=round(duration_s, 1))
        await _emit("connection_close", {
            "uuid": session_id,
            "total_chunks": chunk_idx,
            "duration_s": round(duration_s, 1)
        })

    except asyncio.IncompleteReadError:
        print(f"[AudioSocket] Connection closed unexpectedly — {session_id}")
    except Exception as e:
        traceback.print_exc()
        if session_id:
            await _emit("error", {"uuid": session_id, "message": str(e)})
    finally:
        if session_id:
            _active_connections.pop(session_id, None)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# AudioSocket protocol helpers
# ---------------------------------------------------------------------------

async def _read_frame(reader: asyncio.StreamReader) -> tuple[int | None, bytes]:
    """Read one AudioSocket frame. Returns (type, payload) or (None, b'')."""
    try:
        header = await reader.readexactly(3)
    except asyncio.IncompleteReadError:
        return None, b""

    frame_type = header[0]
    length = struct.unpack(">H", header[1:3])[0]

    if length > 0:
        payload = await reader.readexactly(length)
    else:
        payload = b""

    return frame_type, payload


async def _read_uuid_frame(reader: asyncio.StreamReader) -> str | None:
    """
    Read frames until we get the UUID frame (type 0x01).
    Returns UUID as a hex string, or None on failure.
    """
    for _ in range(10):  # Try up to 10 frames
        frame_type, payload = await _read_frame(reader)
        if frame_type is None:
            return None
        if frame_type == FRAME_UUID and len(payload) == 16:
            return str(_uuid.UUID(bytes=payload))
        if frame_type == FRAME_HANGUP:
            return None
    return None


# ---------------------------------------------------------------------------
# VAD helper
# ---------------------------------------------------------------------------

def _is_silent(pcm_bytes: bytes, sample_width: int,
               silence_rms_threshold: int = 300) -> bool:
    """
    Returns True if the audio chunk is considered silent.
    Uses RMS energy of the PCM samples.
    """
    if not pcm_bytes:
        return True

    import struct as _struct
    fmt = {1: "b", 2: "h", 4: "i"}.get(sample_width, "h")
    num_samples = len(pcm_bytes) // sample_width
    if num_samples == 0:
        return True

    samples = _struct.unpack(f"<{num_samples}{fmt}", pcm_bytes[:num_samples * sample_width])
    rms = (sum(s * s for s in samples) / num_samples) ** 0.5
    return rms < silence_rms_threshold


# ---------------------------------------------------------------------------
# Processing + IO helpers
# ---------------------------------------------------------------------------

async def _process_chunk(session_id: str, chunk_idx: int, pcm_data: bytes,
                          out_dir: str) -> None:
    """Dispatch one audio chunk through the full processing pipeline."""
    await asp.process_chunk(
        session_id=session_id,
        chunk_idx=chunk_idx,
        pcm_data=pcm_data,
        config=_config,
        out_dir=out_dir,
        event_cb=_emit
    )


async def _emit(event_type: str, payload: dict) -> None:
    """Push an SSE event onto the global queue."""
    await _event_queue.put({"event": event_type, "data": payload})


def _session_dir(session_id: str) -> str:
    base = _BASE_DIR or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "audiosocket", session_id)


async def _save_session_meta(session_id: str, out_dir: str, status: str,
                              total_chunks: int = 0, duration_s: float = 0.0) -> None:
    meta_path = os.path.join(out_dir, "session.json")
    existing = {}
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            pass

    existing.update({
        "uuid": session_id,
        "status": status,
        "config": _config,
        "updated": datetime.now(timezone.utc).isoformat(),
    })
    if status == "active" and "started" not in existing:
        existing["started"] = datetime.now(timezone.utc).isoformat()
    if status == "completed":
        existing["total_chunks"] = total_chunks
        existing["duration_s"] = duration_s
        existing["completed"] = datetime.now(timezone.utc).isoformat()

    import aiofiles
    async with aiofiles.open(meta_path, "w", encoding="utf-8") as f:
        await f.write(json.dumps(existing, ensure_ascii=False, indent=2))
