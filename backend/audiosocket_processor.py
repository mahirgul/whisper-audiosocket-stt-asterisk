"""
audiosocket_processor.py

Adapter between raw PCM audio chunks (from AudioSocket) and the existing
processor.py transcription / translation / TTS pipeline.
"""

import os
import io
import wave
import uuid
import asyncio
import aiohttp
import aiofiles
import json
import struct
import traceback
from pydub import AudioSegment
from deep_translator import GoogleTranslator
import edge_tts

# Reuse Whisper model and helpers from the main processor
import processor as main_processor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def pcm_bytes_to_wav_bytes(pcm_data: bytes, sample_rate: int, channels: int,
                            sample_width: int) -> bytes:
    """Wrap raw PCM bytes into an in-memory WAV container."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    return buf.getvalue()


def save_wav(path: str, pcm_data: bytes, sample_rate: int, channels: int,
             sample_width: int) -> None:
    """Save raw PCM bytes as a WAV file."""
    with wave.open(path, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)


def to_srt(segments: list, tag: str = "") -> str:
    """Convert whisper segment list to SRT string."""
    import time as _time
    srt = []
    for i, s in enumerate(segments):
        def ts(x):
            return f"{_time.strftime('%H:%M:%S', _time.gmtime(x))},{int((x % 1) * 1000):03d}"
        txt = s["text"].strip()
        srt.append(f"{i+1}\n{ts(s['start'])} --> {ts(s['end'])}\n[{tag}] {txt}\n")
    return "\n".join(srt)


def build_extra_fields(extra_fields: dict, uuid_str: str, target_lang: str) -> dict:
    """Replace {uuid} and {target_lang} placeholders in extra_fields."""
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
    Full pipeline for one VAD audio chunk:
      1. Save raw WAV
      2. Transcribe with Whisper
      3. Translate segments
      4. Build SRT files
      5. Synthesize dubbed audio (TTS)
      6. Optionally POST dubbed audio to REST endpoint
    Returns a result dict with file paths and texts.
    """
    sample_rate  = config.get("input_sample_rate", 8000)
    channels     = config.get("input_channels", 1)
    sample_width = config.get("input_sample_width", 2)
    target_lang  = config.get("target_lang", "en")
    voice_type   = config.get("voice_type", "M")

    chunk_name = f"chunk_{chunk_idx:03d}"
    wav_path   = os.path.join(out_dir, f"{chunk_name}.wav")
    orig_srt   = os.path.join(out_dir, f"{chunk_name}_orig.srt")
    tran_srt   = os.path.join(out_dir, f"{chunk_name}_tran.srt")
    dub_mp3    = os.path.join(out_dir, f"{chunk_name}_dub.mp3")

    result = {
        "chunk_idx": chunk_idx,
        "wav": wav_path,
        "orig_srt": orig_srt,
        "tran_srt": tran_srt,
        "dub_mp3": dub_mp3,
        "orig_text": "",
        "tran_text": "",
        "delivery_status": None
    }

    try:
        # 1. Save raw WAV
        save_wav(wav_path, pcm_data, sample_rate, channels, sample_width)

        # 2. Transcribe
        if main_processor.model is None:
            raise RuntimeError("Whisper model not loaded yet.")

        await event_cb("chunk_received", {
            "uuid": session_id, "chunk_idx": chunk_idx,
            "duration_ms": int(len(pcm_data) / (sample_rate * channels * sample_width) * 1000)
        })

        def _locked_transcribe():
            with main_processor.whisper_lock:
                return main_processor.model.transcribe(wav_path)

        whisper_result = await asyncio.to_thread(_locked_transcribe)
        segments = whisper_result.get("segments", [])
        orig_text = " ".join(s["text"].strip() for s in segments)
        result["orig_text"] = orig_text

        await event_cb("transcribed", {
            "uuid": session_id, "chunk_idx": chunk_idx, "text": orig_text
        })

        # 3. Translate
        translated_segments = []
        if segments and target_lang:
            translator = GoogleTranslator(source="auto", target=target_lang)
            for seg in segments:
                txt = seg["text"].strip()
                try:
                    translated = await asyncio.to_thread(translator.translate, txt) if txt else ""
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

        # 5. Synthesize dubbed audio
        voice = _pick_voice(voice_type, target_lang)
        duration_ms = int(len(pcm_data) / (sample_rate * channels * sample_width) * 1000)
        track = await main_processor.generate_mono_channel_indep(translated_segments, voice, duration_ms)
        await asyncio.to_thread(track.export, dub_mp3, format="mp3")

        await event_cb("dubbed", {
            "uuid": session_id, "chunk_idx": chunk_idx,
            "file": f"{session_id}/chunk_{chunk_idx:03d}_dub.mp3"
        })

        # 6. Optional REST delivery
        delivery_cfg = config.get("delivery", {})
        if delivery_cfg.get("enabled") and os.path.exists(dub_mp3):
            status = await _deliver(dub_mp3, session_id, target_lang, delivery_cfg)
            result["delivery_status"] = status
            await event_cb("delivered", {
                "uuid": session_id, "chunk_idx": chunk_idx, "status_code": status
            })

    except Exception as e:
        traceback.print_exc()
        await event_cb("error", {"uuid": session_id, "message": str(e)})

    return result


def _pick_voice(voice_type: str, target_lang: str) -> str:
    """Select an edge-tts voice based on voice_type and language."""
    if "-" in voice_type and "Neural" in voice_type:
        return voice_type  # Direct voice ID

    voices = {
        "tr": {"M": "tr-TR-AhmetNeural",   "F": "tr-TR-EmelNeural"},
        "en": {"M": "en-US-AndrewNeural",  "F": "en-US-AvaNeural"},
        "de": {"M": "de-DE-ConradNeural",  "F": "de-DE-KatjaNeural"},
        "fr": {"M": "fr-FR-RemyNeural",    "F": "fr-FR-VivienneBruyanteNeural"},
        "es": {"M": "es-ES-AlvaroNeural",  "F": "es-ES-ElviraNeural"},
        "it": {"M": "it-IT-GiuseppeNeural","F": "it-IT-ElsaNeural"},
        "ru": {"M": "ru-RU-DmitryNeural",  "F": "ru-RU-SvetlanaNeural"},
        "ar": {"M": "ar-SA-HamedNeural",   "F": "ar-SA-ZariyahNeural"},
        "zh": {"M": "zh-CN-YunxiNeural",   "F": "zh-CN-XiaoxiaoNeural"},
        "ja": {"M": "ja-JP-KeitaNeural",   "F": "ja-JP-NanamiNeural"},
        "ko": {"M": "ko-KR-HyunsuNeural",  "F": "ko-KR-SunHiNeural"},
        "pt": {"M": "pt-BR-AntonioNeural", "F": "pt-BR-FranciscaNeural"},
        "hi": {"M": "hi-IN-MadhurNeural",  "F": "hi-IN-SwararaNeural"},
    }
    lang_voices = voices.get(target_lang, voices["en"])
    return lang_voices.get(voice_type, lang_voices["M"])


async def _deliver(mp3_path: str, session_id: str, target_lang: str,
                   delivery_cfg: dict) -> int:
    """POST dubbed audio file to the configured REST endpoint."""
    url        = delivery_cfg.get("url", "")
    method     = delivery_cfg.get("method", "POST").upper()
    field_name = delivery_cfg.get("field_name", "audio")
    timeout    = delivery_cfg.get("timeout_s", 10)
    raw_extra  = delivery_cfg.get("extra_fields", {})
    extra      = build_extra_fields(raw_extra, session_id, target_lang)

    try:
        timeout_obj = aiohttp.ClientTimeout(total=timeout)
        async with aiohttp.ClientSession(timeout=timeout_obj) as session:
            async with aiofiles.open(mp3_path, "rb") as f:
                audio_bytes = await f.read()

            data = aiohttp.FormData()
            data.add_field(field_name, audio_bytes,
                           filename=os.path.basename(mp3_path),
                           content_type="audio/mpeg")
            for k, v in extra.items():
                data.add_field(k, str(v))

            if method == "POST":
                async with session.post(url, data=data) as resp:
                    return resp.status
            else:
                async with session.request(method, url, data=data) as resp:
                    return resp.status
    except Exception as e:
        print(f"[AudioSocket] Delivery error: {e}")
        return -1
