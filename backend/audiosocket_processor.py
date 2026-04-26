"""
audiosocket_processor.py

Adapter between raw PCM audio chunks (from AudioSocket) and the
transcription / translation pipeline.
"""

import io
import wave
import asyncio
import aiohttp
import time as _time

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def pcm_bytes_to_wav_bytes(
    pcm_data: bytes, sample_rate: int, channels: int, sample_width: int
) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    return buf.getvalue()


def save_wav(
    path: str,
    pcm_data: bytes,
    sample_rate: int,
    channels: int,
    sample_width: int,
) -> None:
    with wave.open(path, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)


def to_srt(segments: list, tag: str = "") -> str:
    srt = []
    for i, s in enumerate(segments):

        def ts(x):
            return (
                f"{_time.strftime('%H:%M:%S', _time.gmtime(x))},"
                f"{int((x % 1) * 1000):03d}"
            )

        txt = s["text"].strip()
        srt.append(f"{i+1}\n{ts(s['start'])} --> {ts(s['end'])}\n{txt}\n")
    return "\n".join(srt)


def build_extra_fields(extra_fields: dict, uuid_str: str) -> dict:
    result = {}
    for k, v in extra_fields.items():
        if isinstance(v, str):
            v = v.replace("{uuid}", uuid_str)
        result[k] = v
    return result


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------


async def deliver_chunk(
    wav_bytes: bytes, config: dict, session_id: str, chunk_idx: int
) -> int:
    """Deliver one chunk to a REST endpoint if enabled."""
    d = config.get("delivery", {})
    if not d.get("enabled") or not d.get("url"):
        return 0

    url = d.get("url")
    method = d.get("method", "POST").upper()
    field_name = d.get("field_name", "audio")
    timeout_s = d.get("timeout_s", 10)
    extra = build_extra_fields(d.get("extra_fields", {}), session_id)

    # Add metadata
    extra["chunk_index"] = str(chunk_idx)

    timeout = aiohttp.ClientTimeout(total=timeout_s)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            data = aiohttp.FormData()
            for k, v in extra.items():
                data.add_field(k, str(v))

            data.add_field(
                field_name,
                wav_bytes,
                filename=f"chunk_{chunk_idx:03d}.wav",
                content_type="audio/wav",
            )

            async with session.request(method, url, data=data) as resp:
                return resp.status
    except Exception as e:
        print(f"[Delivery] Error sending chunk {chunk_idx}: {e}")
        return 500


def deliver_chunk_sync(
    wav_bytes: bytes, config: dict, session_id: str, chunk_idx: int
) -> int:
    """Synchronous wrapper for deliver_chunk (used in on_close mode)."""
    try:
        # Create a new loop for the synchronous call in the background thread
        loop = asyncio.new_event_loop()
        return loop.run_until_complete(
            deliver_chunk(wav_bytes, config, session_id, chunk_idx)
        )
    except Exception as e:
        print(f"[Delivery] Sync error: {e}")
        return 500
    finally:
        try:
            loop.close()
        except Exception:
            pass
