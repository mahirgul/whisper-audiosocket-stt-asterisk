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
import zipfile
import os
import utils

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


async def deliver_session_zip(
    session_dir: str, config: dict, session_id: str
) -> int:
    """Deliver a ZIP of the entire session directory to a REST endpoint."""
    d = config.get("delivery", {})
    if not d.get("enabled") or not d.get("url"):
        return 0

    url = d.get("url")
    method = d.get("method", "POST").upper()
    field_name = d.get("field_name", "session_zip")
    timeout_s = d.get("timeout_s", 30)  # Zips might take longer
    extra = build_extra_fields(d.get("extra_fields", {}), session_id)

    # Create ZIP in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for root, dirs, files in os.walk(session_dir):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, session_dir)
                zip_file.write(file_path, arcname=arcname)

    zip_bytes = zip_buffer.getvalue()
    timeout = aiohttp.ClientTimeout(total=timeout_s)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            data = aiohttp.FormData()
            for k, v in extra.items():
                data.add_field(k, str(v))

            data.add_field(
                field_name,
                zip_bytes,
                filename=f"{session_id}.zip",
                content_type="application/zip",
            )

            async with session.request(method, url, data=data) as resp:
                return resp.status
    except Exception as e:
        print(f"[Delivery] Error sending session zip {session_id}: {e}")
        return 500


def deliver_session_zip_sync(
    session_dir: str, config: dict, session_id: str
) -> int:
    """Synchronous wrapper for deliver_session_zip."""
    try:
        loop = asyncio.new_event_loop()
        return loop.run_until_complete(
            deliver_session_zip(session_dir, config, session_id)
        )
    except Exception as e:
        print(f"[Delivery] Sync zip error: {e}")
        return 500
    finally:
        try:
            loop.close()
        except Exception:
            pass
