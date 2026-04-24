import os
import time
import uuid
import asyncio
import json
from pydub import AudioSegment

import model_manager

# ---------------------------------------------------------------------------
# Module-level status variables (read/written by web.py)
# ---------------------------------------------------------------------------
model_status = "idle"
current_task = "Ready"

def sync_status():
    """Sync model_manager status into module-level variables
    so web.py's update_stats loop can read them."""
    global model_status, current_task
    model_status = model_manager.model_status
    current_task = model_manager.current_task

def load_ai_config():
    """Load AI specific thresholds from audiosocket.json."""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg_path = os.path.join(base, "audiosocket.json")
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def to_srt(segments, tag=""):
    def ts(x):
        return f"{time.strftime('%H:%M:%S', time.gmtime(x))},{int((x % 1) * 1000):03d}"
    srt = []
    for i, s in enumerate(segments):
        txt = s['text'].strip()
        srt.append(f"{i+1}\n{ts(s['start'])} --> {ts(s['end'])}\n{txt}\n")
    return "\n".join(srt)

def process_segments_with_music(segments, min_gap=3.0, no_speech_threshold=0.6):
    processed = []
    if not segments: return processed
    for i, s in enumerate(segments):
        if s.get('no_speech_prob', 0) > no_speech_threshold or not s['text'].strip():
            s['text'] = "[MUSIC]"
        if i > 0:
            prev_end = processed[-1]['end']
            curr_start = s['start']
            if curr_start - prev_end > min_gap:
                processed.append({'start': prev_end, 'end': curr_start, 'text': "[MUSIC]"})
        processed.append(s)
    return processed


async def transcribe_audio(file_path, output_dir="outputs"):
    if model_manager.model_status == "loading":
        raise Exception("AI Model is still loading. Please wait a moment...")

    cfg = load_ai_config()
    min_gap = cfg.get("ai_min_music_gap", 3.0)
    no_speech_threshold = cfg.get("ai_no_speech_threshold", 0.6)
    
    whisper_opts = cfg.get("whisper", {})

    unique_id = str(uuid.uuid4())[:8]
    audio = AudioSegment.from_file(file_path)
    original_channels = audio.channels
    total_ms = len(audio)

    channels = audio.split_to_mono()
    if len(channels) < 2:
        channels = [channels[0], channels[0]]

    # Transcribe L & R via the shared model process
    l_path = file_path + "_l.wav"
    channels[0].export(l_path, format="wav")
    res_l = await model_manager.transcribe_async(l_path, options=whisper_opts)
    os.unlink(l_path)

    r_path = file_path + "_r.wav"
    channels[1].export(r_path, format="wav")
    res_r = await model_manager.transcribe_async(r_path, options=whisper_opts)
    os.unlink(r_path)

    segs_l = process_segments_with_music(res_l.get('segments', []), min_gap, no_speech_threshold)
    segs_r = process_segments_with_music(res_r.get('segments', []), min_gap, no_speech_threshold)

    return {
        "unique_id": unique_id,
        "is_mono": original_channels == 1,
        "orig_l_srt": to_srt(segs_l), "orig_r_srt": to_srt(segs_r),
        "duration": total_ms
    }

