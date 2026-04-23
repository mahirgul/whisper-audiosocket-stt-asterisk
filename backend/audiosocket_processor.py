"""
audiosocket_processor.py

Adapter between raw PCM audio chunks (from AudioSocket) and the
transcription / translation pipeline.
"""

import os
import io
import wave
import asyncio
import aiofiles
import traceback
import local_translator

import model_manager


# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------

_transcription_semaphore = asyncio.Semaphore(1)  # one transcription at a time


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def pcm_bytes_to_wav_bytes(pcm_data: bytes, sample_rate: int, channels: int,
                            sample_width: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    return buf.getvalue()


def save_wav(path: str, pcm_data: bytes, sample_rate: int, channels: int,
             sample_width: int) -> None:
    with wave.open(path, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)


def to_srt(segments: list, tag: str = "") -> str:
    import time as _time
    srt = []
    for i, s in enumerate(segments):
        def ts(x):
            return f"{_time.strftime('%H:%M:%S', _time.gmtime(x))},{int((x % 1) * 1000):03d}"
        txt = s["text"].strip()
        srt.append(f"{i+1}\n{ts(s['start'])} --> {ts(s['end'])}\n[{tag}] {txt}\n")
    return "\n".join(srt)


def build_extra_fields(extra_fields: dict, uuid_str: str, target_lang: str) -> dict:
    result = {}
    for k, v in extra_fields.items():
        if isinstance(v, str):
            v = v.replace("{uuid}", uuid_str).replace("{target_lang}", target_lang)
        result[k] = v
    return result


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------

async def process_chunk(
    session_id: str,
    chunk_idx: int,
    pcm_data: bytes,
    config: dict,
    out_dir: str,
    event_cb  # async callable(event_type: str, payload: dict)
) -> dict:
    """
    Pipeline for one audio chunk:
      1. Save raw WAV
      2. Transcribe with Whisper
      3. Translate segments
      4. Build SRT files
    Returns a result dict with file paths and texts.
    """
    sample_rate  = config.get("input_sample_rate", 8000)
    channels     = config.get("input_channels", 1)
    sample_width = config.get("input_sample_width", 2)
    target_lang  = config.get("target_lang", "en")

    chunk_name = f"chunk_{chunk_idx:03d}"
    wav_path   = os.path.join(out_dir, f"{chunk_name}.wav")
    orig_srt   = os.path.join(out_dir, f"{chunk_name}_orig.srt")
    tran_srt   = os.path.join(out_dir, f"{chunk_name}_tran.srt")

    result = {
        "chunk_idx": chunk_idx,
        "wav": wav_path,
        "orig_srt": orig_srt,
        "tran_srt": tran_srt,
        "orig_text": "",
        "tran_text": "",
    }

    try:
        # 1. Save raw WAV
        save_wav(wav_path, pcm_data, sample_rate, channels, sample_width)

        # 2. Transcribe
        await event_cb("chunk_received", {
            "uuid": session_id, "chunk_idx": chunk_idx,
            "duration_ms": int(len(pcm_data) / (sample_rate * channels * sample_width) * 1000)
        })

        async with _transcription_semaphore:
            whisper_result = await model_manager.transcribe_async(wav_path)
        
        segments = whisper_result.get("segments", [])
        detected_lang = whisper_result.get("language", "en")
        orig_text = " ".join(s["text"].strip() for s in segments)
        result["orig_text"] = orig_text

        await event_cb("transcribed", {
            "uuid": session_id, "chunk_idx": chunk_idx, "text": orig_text,
            "detected_lang": detected_lang
        })

        # 3. Translate
        translated_segments = []
        if segments and target_lang:
            for seg in segments:
                txt = seg["text"].strip()
                try:
                    translated = await asyncio.to_thread(local_translator.translate, txt, detected_lang, target_lang) if txt else ""
                except Exception:
                    translated = txt
                translated_segments.append({**seg, "text": translated})
        else:
            translated_segments = segments

        tran_text = " ".join(s["text"].strip() for s in translated_segments)
        result["tran_text"] = tran_text

        await event_cb("translated", {
            "uuid": session_id, "chunk_idx": chunk_idx, "text": tran_text
        })

        # 4. Save SRT files
        async with aiofiles.open(orig_srt, "w", encoding="utf-8") as f:
            await f.write(to_srt(segments, "ORIG"))
        async with aiofiles.open(tran_srt, "w", encoding="utf-8") as f:
            await f.write(to_srt(translated_segments, "TRAN"))

    except Exception as e:
        traceback.print_exc()
        await event_cb("error", {"uuid": session_id, "message": str(e)})

    return result
