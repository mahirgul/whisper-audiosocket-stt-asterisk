"""
audiosocket_server.py

Async TCP server implementing the Asterisk AudioSocket protocol.
Runs in its OWN dedicated thread with a separate asyncio event loop,
so heavy processing (Whisper, translation, etc.) never blocks the FastAPI web server.

AudioSocket protocol (Asterisk):
  Each frame: [type: 1 byte] [length: 2 bytes big-endian] [payload: length bytes]
  type 0x01 — UUID (16 bytes, sent once at connection start)
  type 0x10 — Audio payload (raw PCM, slin format)
  type 0x00 — Hangup / end-of-stream
"""

import asyncio
import json
import os
import queue
import struct
import sys
import threading
import time
import traceback
import uuid as _uuid
from datetime import datetime, timezone
import wave
try:
    import audioop_lts as audioop
except ImportError:
    import audioop

import audiosocket_processor
import model_manager
import local_translator

# ---------------------------------------------------------------------------
# Global state — thread-safe
# ---------------------------------------------------------------------------

_thread: threading.Thread | None = None
_loop: asyncio.AbstractEventLoop | None = None    # event loop of the AS thread
_server: asyncio.AbstractServer | None = None

_config: dict = {}
_config_lock = threading.Lock()

_active_connections: dict[str, dict] = {}          # uuid → session meta
_connections_lock = threading.Lock()

# Thread-safe queues for SSE clients (FastAPI reads them)
_event_queues: set[queue.Queue] = set()
_event_queues_lock = threading.Lock()

# Session processing queue — serializes heavy transcription work
_processing_queue: queue.Queue = queue.Queue()
_processing_worker_thread: threading.Thread | None = None

_BASE_DIR: str = ""

# AudioSocket frame type constants
FRAME_HANGUP = 0x00
FRAME_UUID   = 0x01
FRAME_AUDIO  = 0x10


# ---------------------------------------------------------------------------
# Public interface (called by web.py — runs in FastAPI's thread)
# ---------------------------------------------------------------------------

def set_base_dir(base_dir: str) -> None:
    global _BASE_DIR
    _BASE_DIR = base_dir


def get_status() -> dict:
    with _connections_lock:
        conns = list(_active_connections.values())
        count = len(conns)
    with _config_lock:
        port = _config.get("port", 9092)
    return {
        "listening": _server is not None and _thread is not None and _thread.is_alive(),
        "port": port,
        "active_connections": count,
        "sessions": conns,
    }


def get_active_connections() -> dict:
    with _connections_lock:
        return dict(_active_connections)


def get_event() -> dict | None:
    """
    OBSOLETE: Prefer subscribe() for real-time SSE.
    Remains for backward compatibility if needed.
    """
    return None


def subscribe() -> queue.Queue:
    """
    Create a new thread-safe queue for a client to receive events.
    Returns the queue instance.
    """
    q = queue.Queue()
    with _event_queues_lock:
        _event_queues.add(q)
    return q


def unsubscribe(q: queue.Queue) -> None:
    """Remove a client queue from the active event set."""
    with _event_queues_lock:
        if q in _event_queues:
            _event_queues.remove(q)


def load_config(config_path: str) -> dict:
    """Load audiosocket.json; return defaults if file missing."""
    defaults = {
        "port": 9092,
        "target_lang": "en",
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
        
        # Deep merge helper for dicts
        def deep_merge(target, source):
            for k, v in source.items():
                if k in target and isinstance(target[k], dict) and isinstance(v, dict):
                    deep_merge(target[k], v)
                elif k not in target:
                    target[k] = v
        
        deep_merge(loaded, defaults)
        return loaded
    return defaults


def start_server(config_path: str) -> None:
    """Start (or restart) the AudioSocket TCP server in a dedicated thread."""
    global _thread, _loop, _config, _processing_worker_thread

    # Stop existing server if running
    stop_server()

    with _config_lock:
        _config = load_config(config_path)
        port = _config.get("port", 9092)

    # Start session processing worker (serializes transcription jobs)
    # This thread stays alive even if the TCP server restarts due to config changes.
    if _processing_worker_thread is None or not _processing_worker_thread.is_alive():
        _processing_worker_thread = threading.Thread(
            target=_session_processing_worker,
            daemon=True,
            name="AS-SessionQueue"
        )
        _processing_worker_thread.start()

    _loop = asyncio.new_event_loop()

    def _run():
        asyncio.set_event_loop(_loop)
        _loop.run_until_complete(_start_tcp(port))
        _loop.run_forever()

    _thread = threading.Thread(target=_run, daemon=True, name="AudioSocket-Thread")
    _thread.start()
    print(f"[AudioSocket] Server thread started — listening on port {port}")


def stop_server() -> None:
    global _server, _thread, _loop
    if _loop is not None and _server is not None:
        try:
            asyncio.run_coroutine_threadsafe(_stop_tcp(), _loop).result(timeout=5)
        except Exception:
            pass
    if _loop is not None:
        _loop.call_soon_threadsafe(_loop.stop)
    if _thread is not None:
        _thread.join(timeout=5)
    _server = None
    _thread = None
    _loop = None


def shutdown_worker() -> None:
    """Shutdown the background processing queue worker."""
    global _processing_worker_thread
    if _processing_worker_thread and _processing_worker_thread.is_alive():
        print("[AudioSocket] Shutting down session worker...")
        _processing_queue.put(None)
        _processing_worker_thread.join(timeout=2)
    _processing_worker_thread = None


def _session_processing_worker() -> None:
    """
    Single worker thread that drains the session processing queue.
    Ensures only one session is transcribed at a time, preventing
    model contention when multiple AudioSocket connections overlap.
    """
    print("[AudioSocket] Session processing queue started.")
    while True:
        try:
            job = _processing_queue.get(timeout=1.0)
            if job is None:
                break  # shutdown signal
            session_id, pcm_data, out_dir, duration_s = job
            print(f"[AudioSocket] Processing session {session_id[:8]} "
                  f"(queue size: {_processing_queue.qsize()} remaining)")
            
            # Update status from queued to processing
            with _connections_lock:
                if session_id in _active_connections:
                    _active_connections[session_id]["status"] = "processing"

            _process_session_blocking(session_id, pcm_data, out_dir, duration_s)
            _processing_queue.task_done()
        except queue.Empty:
            continue
        except Exception:
            traceback.print_exc()


# ---------------------------------------------------------------------------
# Internal async functions (run inside the AS thread's event loop)
# ---------------------------------------------------------------------------

async def _start_tcp(port: int) -> None:
    global _server
    _server = await asyncio.start_server(
        _connection_handler,
        host="0.0.0.0",
        port=port
    )
    print(f"[AudioSocket] TCP server bound to 0.0.0.0:{port}")


async def _stop_tcp() -> None:
    global _server
    if _server:
        _server.close()
        await _server.wait_closed()
        _server = None


# ---------------------------------------------------------------------------
# Connection handler (runs inside the AS thread)
# ---------------------------------------------------------------------------

def _is_silent_frame(payload: bytes, threshold: int = 300) -> bool:
    """
    Check silence by RMS energy of the PCM frame.
    threshold: RMS amplitude value below which frame is considered silent.
    Tune this value based on your environment (300-500 is good for 8kHz slin).
    """
    if len(payload) < 2:
        return True
    # slin (signed linear) is big-endian (network byte order) in AudioSocket
    count = len(payload) // 2
    samples = struct.unpack(f">{count}h", payload)
    rms = (sum(s * s for s in samples) / count) ** 0.5
    return rms < threshold


async def _connection_handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:

    remote = writer.get_extra_info("peername")
    session_id = None
    start_time = datetime.now(timezone.utc)
    processing_started = False

    try:
        # Read the UUID frame first
        session_id = await _read_uuid_frame(reader)
        if session_id is None:
            print(f"[AudioSocket] No UUID received from {remote}. Closing.")
            writer.close()
            return

        with _connections_lock:
            if session_id in _active_connections:
                session_id = f"{session_id}-{_uuid.uuid4().hex[:4]}"

        print(f"[AudioSocket] Connection from {remote} — session {session_id}")

        out_dir = _session_dir(session_id)
        os.makedirs(out_dir, exist_ok=True)

        # Register active connection
        with _connections_lock:
            _active_connections[session_id] = {
                "uuid": session_id,
                "remote": str(remote),
                "started": start_time.isoformat(),
                "chunks": 0,
                "status": "active"
            }

        _emit_sync("connection_open", {
            "uuid": session_id,
            "remote_addr": str(remote),
            "timestamp": start_time.isoformat()
        })

        # Save session metadata
        _save_session_meta_sync(session_id, out_dir, "active")

        audio_buf = bytearray()
        total_bytes_received = 0
        connection_alive = True

        # VAD state for instant transcription
        with _config_lock:
            cfg = dict(_config)
            trans_mode = cfg.get("transcription_mode", "on_close")
            silence_ms = cfg.get("vad_silence_threshold_ms", 1500)
            min_chunk_ms = cfg.get("vad_min_chunk_ms", 1000)
            sample_rate = cfg.get("input_sample_rate", 8000)
            channels = cfg.get("input_channels", 1)
            sample_width = cfg.get("input_sample_width", 2)

        chunk_buf = bytearray()
        silence_bytes_threshold = (sample_rate * channels * sample_width * silence_ms) // 1000
        min_chunk_bytes = (sample_rate * channels * sample_width * min_chunk_ms) // 1000
        consecutive_silence = 0
        chunk_counter = 0

        # Build a silence frame to send back to Asterisk
        silence_frame_ms = 20
        silence_frame_bytes = (sample_rate * channels * sample_width * silence_frame_ms) // 1000
        silence_payload = b'\x00' * silence_frame_bytes
        silence_header = struct.pack("B", FRAME_AUDIO) + struct.pack(">H", silence_frame_bytes)
        silence_frame = silence_header + silence_payload

        async def _send_silence():
            nonlocal connection_alive
            try:
                while connection_alive:
                    writer.write(silence_frame)
                    await writer.drain()
                    await asyncio.sleep(silence_frame_ms / 1000.0)
            except (ConnectionResetError, BrokenPipeError, OSError):
                connection_alive = False

        async def _read_audio():
            nonlocal connection_alive, consecutive_silence, chunk_counter, total_bytes_received
            try:
                while connection_alive:
                    frame_type, payload = await _read_frame(reader)
                    if frame_type is None or frame_type == FRAME_HANGUP:
                        break
                    if frame_type == FRAME_AUDIO:
                        total_bytes_received += len(payload)
                        
                        # RMS-based VAD for real-world audio (before byteswap, slin16 is big-endian)
                        is_silent = _is_silent_frame(payload)

                        # Swap to little-endian for WAV saving and Whisper processing
                        payload = audioop.byteswap(payload, 2)
                        audio_buf.extend(payload)

                        if trans_mode == "instant":
                            chunk_buf.extend(payload)
                            
                            if is_silent:
                                consecutive_silence += len(payload)
                            else:
                                # Soft reset: reduce counter instead of zeroing out immediately
                                consecutive_silence = max(0, consecutive_silence - len(payload) // 2)

                            if consecutive_silence >= silence_bytes_threshold and len(chunk_buf) >= min_chunk_bytes:
                                # Chunk ended! Transcribe this segment.
                                chunk_counter += 1
                                current_chunk = bytes(chunk_buf)
                                chunk_buf.clear()
                                consecutive_silence = 0
                                
                                # Process in background task so we don't block the stream
                                asyncio.create_task(audiosocket_processor.process_chunk(
                                    session_id, chunk_counter, current_chunk, cfg, out_dir, _emit_async
                                ))

            except (asyncio.IncompleteReadError, ConnectionResetError, OSError):
                pass
            finally:
                connection_alive = False

        # Run both tasks concurrently
        silence_task = asyncio.create_task(_send_silence())
        await _read_audio()
        silence_task.cancel()
        try:
            await silence_task
        except asyncio.CancelledError:
            pass

        # Final chunk for instant mode if buffer not empty
        if trans_mode == "instant" and len(chunk_buf) > (sample_rate * channels * sample_width * 0.1):
            chunk_counter += 1
            asyncio.create_task(audiosocket_processor.process_chunk(
                session_id, chunk_counter, bytes(chunk_buf), cfg, out_dir, _emit_async
            ))

        # Connection ended
        duration_s = (datetime.now(timezone.utc) - start_time).total_seconds()
        print(f"[AudioSocket] Connection ended — session {session_id}, "
              f"{total_bytes_received} bytes, {round(duration_s, 1)}s")

        if trans_mode == "on_close" and len(audio_buf) > 0:
            with _connections_lock:
                if session_id in _active_connections:
                    _active_connections[session_id]["status"] = "processing"

            _emit_sync("connection_close", {
                "uuid": session_id,
                "total_chunks": 0,
                "duration_s": round(duration_s, 1),
                "status": "processing"
            })

            # Queue session for processing
            queue_pos = _processing_queue.qsize() + 1
            print(f"[AudioSocket] Session {session_id[:8]} queued for processing "
                  f"(position: {queue_pos})")

            # Update status to show it's queued, not just processing
            with _connections_lock:
                if session_id in _active_connections:
                    _active_connections[session_id]["status"] = "queued"

            _emit_sync("session_queued", {
                "uuid": session_id,
                "queue_position": queue_pos,
                "duration_s": round(duration_s, 1)
            })

            _processing_queue.put((session_id, bytes(audio_buf), out_dir, duration_s))
            processing_started = True
        else:
            # If instant mode, we don't spawn a session process thread, 
            # cleanup is done when connection closes.
            with _connections_lock:
                _active_connections.pop(session_id, None)
            _save_session_meta_sync(session_id, out_dir, "completed",
                                    total_chunks=chunk_counter,
                                    duration_s=round(duration_s, 1))
            _emit_sync("connection_close", {
                "uuid": session_id,
                "total_chunks": chunk_counter,
                "duration_s": round(duration_s, 1)
            })

    except Exception as e:
        traceback.print_exc()
        if session_id:
            with _connections_lock:
                _active_connections.pop(session_id, None)
            _emit_sync("error", {"uuid": session_id, "message": str(e)})
            _emit_sync("connection_close", {
                "uuid": session_id,
                "total_chunks": 0,
                "duration_s": 0
            })
    finally:
        # Only remove from active_connections here if no processing thread was
        # spawned — otherwise the processing thread handles cleanup.
        if session_id and not processing_started:
            with _connections_lock:
                _active_connections.pop(session_id, None)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# AudioSocket protocol helpers
# ---------------------------------------------------------------------------

async def _read_frame(reader: asyncio.StreamReader,
                      timeout: float = 30.0) -> tuple[int | None, bytes]:
    """Read one AudioSocket frame. Returns (type, payload) or (None, b'')."""
    try:
        header = await asyncio.wait_for(reader.readexactly(3), timeout=timeout)
    except (asyncio.IncompleteReadError, asyncio.TimeoutError):
        return None, b""

    frame_type = header[0]
    length = struct.unpack(">H", header[1:3])[0]

    if length > 0:
        try:
            payload = await asyncio.wait_for(reader.readexactly(length), timeout=timeout)
        except (asyncio.IncompleteReadError, asyncio.TimeoutError):
            return None, b""
    else:
        payload = b""

    return frame_type, payload


async def _read_uuid_frame(reader: asyncio.StreamReader) -> str | None:
    """
    Read frames until we get the UUID frame (type 0x01).
    Returns UUID as a hex string, or None on failure.
    """
    for _ in range(10):
        frame_type, payload = await _read_frame(reader)
        if frame_type is None:
            return None
        if frame_type == FRAME_UUID and len(payload) == 16:
            return str(_uuid.UUID(bytes=payload))
        if frame_type == FRAME_HANGUP:
            return None
    return None


def _save_wav(path: str, pcm_data: bytes, sample_rate: int,
              channels: int, sample_width: int) -> None:
    """Save raw PCM bytes as a WAV file."""
    with wave.open(path, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)


def _to_srt(segments: list, tag: str = "") -> str:
    """Convert whisper-style segment list to SRT string."""
    srt = []
    for i, s in enumerate(segments):
        def ts(x):
            return f"{time.strftime('%H:%M:%S', time.gmtime(x))},{int((x % 1) * 1000):03d}"
        txt = s["text"].strip()
        srt.append(f"{i+1}\n{ts(s['start'])} --> {ts(s['end'])}\n[{tag}] {txt}\n")
    return "\n".join(srt)


def _process_session_blocking(session_id: str, pcm_data: bytes,
                               out_dir: str, duration_s: float) -> None:
    """
    Process a completed AudioSocket session:
      1. Save WAV from raw PCM
      2. Transcribe via model_manager (shared Whisper process — no duplicate model)
      3. Translate with local_translator (argostranslate)
      4. Save SRT / result metadata

    Runs in a background thread. Transcription is offloaded to the
    dedicated model worker process via model_manager.transcribe(),
    so there is NO GIL contention with the web server.
    """
    processing_ok = False
    try:
        with _config_lock:
            cfg = dict(_config)

        sample_rate  = cfg.get("input_sample_rate", 8000)
        channels     = cfg.get("input_channels", 1)
        sample_width = cfg.get("input_sample_width", 2)
        target_lang  = cfg.get("target_lang", "en")

        wav_path = os.path.join(out_dir, "chunk_001.wav")
        orig_srt = os.path.join(out_dir, "chunk_001_orig.srt")
        tran_srt = os.path.join(out_dir, "chunk_001_tran.srt")

        _emit_sync("processing_started", {
            "uuid": session_id,
            "duration_s": round(duration_s, 1)
        })

        # 1. Save WAV
        _save_wav(wav_path, pcm_data, sample_rate, channels, sample_width)
        print(f"[AudioSocket] WAV saved for session {session_id[:8]}")

        # 2. Transcribe via shared model process (thread-safe, blocking).
        # If another session is already transcribing, this call queues and waits.
        print(f"[AudioSocket] Queued for transcription: session {session_id[:8]}")
        whisper_result = model_manager.transcribe(wav_path)
        segments      = whisper_result.get("segments", [])
        detected_lang = whisper_result.get("language", "") or "en"
        orig_text     = " ".join(s["text"].strip() for s in segments)
        print(f"[AudioSocket] Transcribed ({detected_lang}): {orig_text[:100]}...")

        _emit_sync("transcribed", {
            "uuid": session_id, "text": orig_text[:200],
            "detected_lang": detected_lang
        })

        # 3. Translate (offline — local_translator uses argostranslate)
        translated_segments = []
        if segments and target_lang and detected_lang != target_lang:
            print(f"[AudioSocket] Translating {detected_lang}→{target_lang} "
                  f"({len(segments)} segments) ...")
            for seg in segments:
                txt = seg["text"].strip()
                try:
                    translated = (local_translator.translate(txt, detected_lang, target_lang)
                                  if txt else "")
                except Exception:
                    translated = txt
                translated_segments.append({**seg, "text": translated})
        else:
            translated_segments = list(segments)

        tran_text = " ".join(s["text"].strip() for s in translated_segments)
        print(f"[AudioSocket] Translated: {tran_text[:100]}...")

        _emit_sync("translated", {
            "uuid": session_id, "text": tran_text[:200]
        })

        # 4. Save SRT files
        with open(orig_srt, "w", encoding="utf-8") as f:
            f.write(_to_srt(segments, "ORIG"))
        with open(tran_srt, "w", encoding="utf-8") as f:
            f.write(_to_srt(translated_segments, "TRAN"))

        # 5. REST Delivery (on_close mode delivery)
        wav_bytes = audiosocket_processor.pcm_bytes_to_wav_bytes(pcm_data, sample_rate, channels, sample_width)
        status_code = audiosocket_processor.deliver_chunk_sync(wav_bytes, cfg, session_id, 1)
        if status_code > 0:
            print(f"[AudioSocket] Session {session_id[:8]} delivered (HTTP {status_code})")
            _emit_sync("delivered", {
                "uuid": session_id, "chunk_idx": 1, "status_code": status_code
            })

        # 6. Write result metadata
        result_path = os.path.join(out_dir, "result.json")
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump({
                "status": "completed",
                "orig_text": orig_text,
                "tran_text": tran_text,
                "completed": datetime.now(timezone.utc).isoformat()
            }, f, ensure_ascii=False, indent=2)

        _emit_sync("session_processed", {
            "uuid": session_id,
            "total_chunks": 1,
            "duration_s": round(duration_s, 1)
        })
        print(f"[AudioSocket] Session {session_id[:8]} processing complete.")
        processing_ok = True

    except Exception as e:
        traceback.print_exc()
        _emit_sync("error", {"uuid": session_id, "message": str(e)})
    finally:
        with _connections_lock:
            _active_connections.pop(session_id, None)
        _save_session_meta_sync(session_id, out_dir,
                                "completed" if processing_ok else "error",
                                total_chunks=1,
                                duration_s=round(duration_s, 1))


# ---------------------------------------------------------------------------
# Event + IO helpers (thread-safe, synchronous)
# ---------------------------------------------------------------------------

def _emit_sync(event_type: str, payload: dict) -> None:
    """Thread-safe: push event to all subscribed queues."""
    msg = {"event": event_type, "data": payload}
    with _event_queues_lock:
        # copy to a list to avoid issues if set changes during iteration, though lock should protect it
        for q in list(_event_queues):
            q.put(msg)


async def _emit_async(event_type: str, payload: dict) -> None:
    """Async wrapper for _emit_sync (used as event_cb in processor)."""
    _emit_sync(event_type, payload)


def _session_dir(session_id: str) -> str:
    base = _BASE_DIR or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "audiosocket", session_id)


def _save_session_meta_sync(session_id: str, out_dir: str, status: str,
                             total_chunks: int = 0, duration_s: float = 0.0) -> None:
    """Synchronous session metadata writer (safe from any thread)."""
    meta_path = os.path.join(out_dir, "session.json")
    existing = {}
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            pass

    with _config_lock:
        cfg = dict(_config)

    existing.update({
        "uuid": session_id,
        "status": status,
        "config": cfg,
        "updated": datetime.now(timezone.utc).isoformat(),
    })
    if status == "active" and "started" not in existing:
        existing["started"] = datetime.now(timezone.utc).isoformat()
    if status == "completed":
        existing["total_chunks"] = total_chunks
        existing["duration_s"] = duration_s
        existing["completed"] = datetime.now(timezone.utc).isoformat()

    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)

