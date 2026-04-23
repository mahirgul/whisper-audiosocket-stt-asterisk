import os
import time
import uuid
import asyncio
from pydub import AudioSegment

import model_manager
import local_translator

# ---------------------------------------------------------------------------
# Module-level status variables (read/written by web.py)
# ---------------------------------------------------------------------------
model_status = "loading"
current_task = "Waking up AI..."

def sync_status():
    """Sync model_manager status into module-level variables
    so web.py's update_stats loop can read them."""
    global model_status, current_task
    model_status = model_manager.model_status
    current_task = model_manager.current_task

def to_srt(segments, tag=""):
    def ts(x):
        return f"{time.strftime('%H:%M:%S', time.gmtime(x))},{int((x % 1) * 1000):03d}"
    srt = []
    for i, s in enumerate(segments):
        txt = s['text'].strip()
        srt.append(f"{i+1}\n{ts(s['start'])} --> {ts(s['end'])}\n{txt}\n")
    return "\n".join(srt)

def process_segments_with_music(segments, min_gap=3.0):
    processed = []
    if not segments: return processed
    for i, s in enumerate(segments):
        if s.get('no_speech_prob', 0) > 0.6 or not s['text'].strip():
            s['text'] = "[MUSIC]"
        if i > 0:
            prev_end = processed[-1]['end']
            curr_start = s['start']
            if curr_start - prev_end > min_gap:
                processed.append({'start': prev_end, 'end': curr_start, 'text': "[MUSIC]"})
        processed.append(s)
    return processed


async def transcribe_audio(file_path, target_lang, output_dir="outputs"):
    if model_manager.model_status == "loading":
        raise Exception("AI Model is still loading. Please wait a moment...")

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
    res_l = await model_manager.transcribe_async(l_path)
    os.unlink(l_path)

    r_path = file_path + "_r.wav"
    channels[1].export(r_path, format="wav")
    res_r = await model_manager.transcribe_async(r_path)
    os.unlink(r_path)

    segs_l = process_segments_with_music(res_l.get('segments', []))
    segs_r = process_segments_with_music(res_r.get('segments', []))

    from_l = res_l.get('language', 'auto')
    from_r = res_r.get('language', 'auto')

    async def trans_segs(segs, from_code):
        out = []
        for s in segs:
            txt = s['text'].strip()
            if txt == "[MUSIC]":
                translated = "[MUSIC]"
            elif txt:
                translated = await asyncio.to_thread(local_translator.translate, txt, from_code, target_lang)
            else:
                translated = ""
            out.append({**s, "text": translated})
        return out

    t_l = await trans_segs(segs_l, from_l)
    t_r = await trans_segs(segs_r, from_r)

    return {
        "unique_id": unique_id,
        "is_mono": original_channels == 1,
        "t_l": t_l, "t_r": t_r,
        "orig_l_srt": to_srt(segs_l), "orig_r_srt": to_srt(segs_r),
        "tran_l_srt": to_srt(t_l), "tran_r_srt": to_srt(t_r),
        "duration": total_ms
    }

