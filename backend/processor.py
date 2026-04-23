import os
import time
import uuid
import asyncio
from pydub import AudioSegment
from deep_translator import GoogleTranslator

import model_manager

# ---------------------------------------------------------------------------
# Expose model status from model_manager so web.py stats loop still works
# ---------------------------------------------------------------------------

def _get_model_status():
    return model_manager.model_status

def _set_model_status(value):
    model_manager.model_status = value

def _get_current_task():
    return model_manager.current_task

def _set_current_task(value):
    model_manager.current_task = value

# These module-level attributes are now properties backed by model_manager
# Access them via processor.model_status / processor.current_task
class _StatusProxy:
    """Tiny descriptor-like proxy so web.py can read/write
    processor.model_status and processor.current_task transparently."""
    @property
    def model_status(self):
        return model_manager.model_status
    @model_status.setter
    def model_status(self, v):
        model_manager.model_status = v
    @property
    def current_task(self):
        return model_manager.current_task
    @current_task.setter
    def current_task(self, v):
        model_manager.current_task = v

_proxy = _StatusProxy()

# Module-level variables that web.py reads/writes directly.
# We keep them as plain strings and sync from model_manager in update_stats.
model_status = "loading"
current_task = "Waking up AI..."

def load_model(model_name="medium"):
    """Start the shared model worker process.
    Called once at startup from web.py.
    """
    global model_status, current_task
    model_manager.start(model_name)
    # Status will be updated by sync_status() calls from web.py

def to_srt(segments, tag=""):
    srt = []
    for i, s in enumerate(segments):
        ts = lambda x: f"{time.strftime('%H:%M:%S', time.gmtime(x))},{int((x%1)*1000):03d}"
        txt = s['text'].strip()
        srt.append(f"{i+1}\n{ts(s['start'])} --> {ts(s['end'])}\n[{tag}] {txt}\n")
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

def sync_status():
    """Sync model_manager status into module-level variables
    so web.py's update_stats loop can read them."""
    global model_status, current_task
    model_status = model_manager.model_status
    current_task = model_manager.current_task


async def transcribe_audio(file_path, target_lang, output_dir="outputs"):
    if not model_manager.is_ready():
        raise Exception("AI Model is still loading.")

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

    translator = GoogleTranslator(source='auto', target=target_lang)
    async def trans_segs(segs):
        out = []
        for s in segs:
            txt = s['text'].strip()
            if txt == "[MUSIC]":
                translated = "[MUSIC]"
            elif txt:
                translated = await asyncio.to_thread(translator.translate, txt)
            else:
                translated = ""
            out.append({**s, "text": translated})
        return out

    t_l = await trans_segs(segs_l)
    t_r = await trans_segs(segs_r)

    return {
        "unique_id": unique_id,
        "is_mono": original_channels == 1,
        "t_l": t_l, "t_r": t_r,
        "orig_l_srt": to_srt(segs_l, "ORIG-L"), "orig_r_srt": to_srt(segs_r, "ORIG-R"),
        "tran_l_srt": to_srt(t_l, "TRAN-L"), "tran_r_srt": to_srt(t_r, "TRAN-R"),
        "duration": total_ms
    }

