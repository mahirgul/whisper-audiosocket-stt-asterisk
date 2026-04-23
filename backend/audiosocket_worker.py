"""
audiosocket_worker.py

Standalone worker script that processes an AudioSocket session's audio.
Runs as a SEPARATE PROCESS to avoid GIL contention with the web server.

Usage:
    python audiosocket_worker.py <session_dir> <config_json_path> <model_name>
"""

import sys
import os
import io
import json
import wave
import asyncio
import traceback
from datetime import datetime, timezone

def save_wav(path, pcm_data, sample_rate, channels, sample_width):
    with wave.open(path, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)

def to_srt(segments, tag=""):
    import time as _time
    srt = []
    for i, s in enumerate(segments):
        def ts(x):
            return f"{_time.strftime('%H:%M:%S', _time.gmtime(x))},{int((x % 1) * 1000):03d}"
        txt = s["text"].strip()
        srt.append(f"{i+1}\n{ts(s['start'])} --> {ts(s['end'])}\n[{tag}] {txt}\n")
    return "\n".join(srt)

def pick_voice(voice_type, target_lang):
    if "-" in voice_type and "Neural" in voice_type:
        return voice_type
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


async def generate_dubbed_audio(segments, voice, duration_ms, output_path):
    """Generate TTS audio from translated segments, time-aligned."""
    import uuid
    import tempfile
    import edge_tts
    from pydub import AudioSegment

    track = AudioSegment.silent(duration=duration_ms)
    last_end_ms = 0

    for seg in segments:
        text = seg["text"].strip()
        if not text or "[MUSIC]" in text.upper():
            continue
        tmp_p = os.path.join(tempfile.gettempdir(), f"tts_{uuid.uuid4()}.mp3")
        try:
            await edge_tts.Communicate(text, voice).save(tmp_p)
            if not os.path.exists(tmp_p) or os.path.getsize(tmp_p) == 0:
                continue
            seg_audio = AudioSegment.from_file(tmp_p)
            start_ms = max(int(seg["start"] * 1000), last_end_ms)
            if len(track) < start_ms + len(seg_audio):
                track += AudioSegment.silent(
                    duration=(start_ms + len(seg_audio)) - len(track)
                )
            track = track.overlay(seg_audio, position=start_ms)
            last_end_ms = start_ms + len(seg_audio)
        except Exception:
            traceback.print_exc()
            continue
        finally:
            if os.path.exists(tmp_p):
                os.unlink(tmp_p)

    track.export(output_path, format="mp3")


def process(session_dir, config, model_name):
    """Main processing pipeline — runs in this isolated process."""
    import whisper
    from deep_translator import GoogleTranslator

    sample_rate  = config.get("input_sample_rate", 8000)
    channels     = config.get("input_channels", 1)
    sample_width = config.get("input_sample_width", 2)
    target_lang  = config.get("target_lang", "en")
    voice_type   = config.get("voice_type", "M")

    pcm_path = os.path.join(session_dir, "raw.pcm")
    wav_path = os.path.join(session_dir, "chunk_001.wav")
    orig_srt = os.path.join(session_dir, "chunk_001_orig.srt")
    tran_srt = os.path.join(session_dir, "chunk_001_tran.srt")
    dub_mp3  = os.path.join(session_dir, "chunk_001_dub.mp3")

    if not os.path.exists(pcm_path):
        print(f"[Worker] No raw.pcm in {session_dir}", file=sys.stderr)
        return False

    with open(pcm_path, "rb") as f:
        pcm_data = f.read()

    print(f"[Worker] Processing {len(pcm_data)} bytes of audio...")

    # 1. Save WAV
    save_wav(wav_path, pcm_data, sample_rate, channels, sample_width)
    print("[Worker] WAV saved.")

    # 2. Transcribe with Whisper
    model_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "models", "whisper")
    print(f"[Worker] Loading Whisper model '{model_name}'...")
    model = whisper.load_model(model_name, device="cpu", download_root=model_dir)
    print("[Worker] Transcribing...")
    whisper_result = model.transcribe(wav_path)
    segments = whisper_result.get("segments", [])
    orig_text = " ".join(s["text"].strip() for s in segments)
    print(f"[Worker] Transcribed: {orig_text[:100]}...")

    # 3. Translate
    translated_segments = []
    if segments and target_lang:
        translator = GoogleTranslator(source="auto", target=target_lang)
        for seg in segments:
            txt = seg["text"].strip()
            try:
                translated = translator.translate(txt) if txt else ""
            except Exception:
                translated = txt
            translated_segments.append({**seg, "text": translated})
    else:
        translated_segments = segments

    tran_text = " ".join(s["text"].strip() for s in translated_segments)
    print(f"[Worker] Translated: {tran_text[:100]}...")

    # 4. Save SRT files
    with open(orig_srt, "w", encoding="utf-8") as f:
        f.write(to_srt(segments, "ORIG"))
    with open(tran_srt, "w", encoding="utf-8") as f:
        f.write(to_srt(translated_segments, "TRAN"))

    # 5. Synthesize dubbed audio
    voice = pick_voice(voice_type, target_lang)
    duration_ms = int(len(pcm_data) / (sample_rate * channels * sample_width) * 1000)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(generate_dubbed_audio(
            translated_segments, voice, duration_ms, dub_mp3
        ))
    finally:
        loop.close()

    print("[Worker] TTS dubbed audio saved.")

    # 6. Clean up raw PCM (no longer needed)
    try:
        os.unlink(pcm_path)
    except Exception:
        pass

    # 7. Write result metadata
    result_path = os.path.join(session_dir, "result.json")
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump({
            "status": "completed",
            "orig_text": orig_text,
            "tran_text": tran_text,
            "completed": datetime.now(timezone.utc).isoformat()
        }, f, ensure_ascii=False, indent=2)

    print("[Worker] Done.")
    return True


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python audiosocket_worker.py <session_dir> <config_json> <model_name>",
              file=sys.stderr)
        sys.exit(1)

    session_dir = sys.argv[1]
    config_json = sys.argv[2]
    model_name  = sys.argv[3]

    with open(config_json, "r", encoding="utf-8") as f:
        config = json.load(f)

    try:
        ok = process(session_dir, config, model_name)
        sys.exit(0 if ok else 1)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
