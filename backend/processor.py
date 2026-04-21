import os
import time
import tempfile
import uuid
import asyncio
import threading
import whisper
import json
import traceback
import numpy as np
from pydub import AudioSegment
from deep_translator import GoogleTranslator
import edge_tts

# Global variables for AI model state
model = None
model_status = "loading"
current_task = "Waking up AI..."

def load_model(model_name="medium"):
    global model, model_status, current_task
    try:
        model_dir = os.path.join(os.getcwd(), "models", "whisper")
        if not os.path.exists(model_dir): os.makedirs(model_dir)
        
        # Check if model likely exists (simplified check)
        model_path = os.path.join(model_dir, f"{model_name}.pt")
        if not os.path.exists(model_path):
            current_task = f"Downloading {model_name} model (this may take a while)..."
        else:
            current_task = f"Loading {model_name} model from disk..."
            
        model = whisper.load_model(model_name, device="cpu", download_root=model_dir)
        model_status = "idle"
        current_task = "Ready"
    except Exception as e:
        print(f"MODEL LOAD ERROR: {e}")
        current_task = f"Error loading model: {str(e)}"
        model_status = "error"

def detect_gender(audio_segment):
    """
    Estimates gender based on fundamental frequency (Pitch/F0) using FFT.
    > 165 Hz generally correlates to Female, < 165 Hz to Male.
    """
    try:
        samples = np.array(audio_segment.get_array_of_samples())
        if audio_segment.channels == 2:
            samples = samples[::2] # take one channel if stereo
            
        # Apply Hanning window to reduce spectral leakage
        window = np.hanning(len(samples))
        samples = samples * window
        
        w = np.abs(np.fft.rfft(samples))
        freqs = np.fft.rfftfreq(len(samples), 1.0/audio_segment.frame_rate)
        
        # Filter for typical human vocal fundamental frequency range (80Hz - 260Hz)
        valid_idx = np.where((freqs > 80) & (freqs < 260))
        if len(valid_idx[0]) == 0: return "M"
        
        valid_freqs = freqs[valid_idx]
        valid_w = w[valid_idx]
        
        peak_freq = valid_freqs[np.argmax(valid_w)]
        if peak_freq > 165:
            return "F"
        return "M"
    except Exception as e:
        print(f"Gender detection failed: {e}")
        return "M"

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

async def transcribe_audio(file_path, target_lang, output_dir="outputs"):
    global model
    if model is None: raise Exception("AI Model is still loading.")
    
    unique_id = str(uuid.uuid4())[:8]
    input_copy_path = os.path.join(output_dir, f"input_{unique_id}.mp3")
    
    audio = AudioSegment.from_file(file_path)
    audio.export(input_copy_path, format="mp3")
    
    original_channels = audio.channels
    total_ms = len(audio)
    
    channels = audio.split_to_mono()
    if len(channels) < 2:
        channels = [channels[0], channels[0]]

    # Transcribe L & R
    l_path = file_path + "_l.wav"
    channels[0].export(l_path, format="wav")
    res_l = await asyncio.to_thread(model.transcribe, l_path)
    os.unlink(l_path)

    r_path = file_path + "_r.wav"
    channels[1].export(r_path, format="wav")
    res_r = await asyncio.to_thread(model.transcribe, r_path)
    os.unlink(r_path)

    segs_l = process_segments_with_music(res_l['segments'])
    segs_r = process_segments_with_music(res_r['segments'])

    translator = GoogleTranslator(source='auto', target=target_lang)
    def trans_segs(segs):
        out = []
        for s in segs:
            txt = s['text'].strip()
            translated = "[MUSIC]" if txt == "[MUSIC]" else (translator.translate(txt) if txt else "")
            out.append({**s, "text": translated})
        return out

    t_l = trans_segs(segs_l)
    t_r = trans_segs(segs_r)

    return {
        "unique_id": unique_id,
        "input_path": input_copy_path,
        "is_mono": original_channels == 1,
        "t_l": t_l, "t_r": t_r,
        "orig_l_srt": to_srt(segs_l, "ORIG-L"), "orig_r_srt": to_srt(segs_r, "ORIG-R"),
        "tran_l_srt": to_srt(t_l, "TRAN-L"), "tran_r_srt": to_srt(t_r, "TRAN-R"),
        "duration": total_ms
    }

async def generate_mono_channel_indep(segments, voice, duration_ms):
    track = AudioSegment.silent(duration=duration_ms)
    last_end_ms = 0
    for seg in segments:
        text = seg['text'].strip()
        if not text or "[MUSIC]" in text.upper(): continue
        tmp_fn = f"tts_{uuid.uuid4()}.mp3"
        tmp_p = os.path.join(tempfile.gettempdir(), tmp_fn)
        try:
            await edge_tts.Communicate(text, voice).save(tmp_p)
            if not os.path.exists(tmp_p) or os.path.getsize(tmp_p) == 0: continue
            seg_audio = AudioSegment.from_file(tmp_p)
            start_ms = max(int(seg['start'] * 1000), last_end_ms)
            if len(track) < start_ms + len(seg_audio):
                track += AudioSegment.silent(duration=(start_ms + len(seg_audio)) - len(track))
            track = track.overlay(seg_audio, position=start_ms)
            last_end_ms = start_ms + len(seg_audio)
        except: continue
        finally:
            if os.path.exists(tmp_p): os.unlink(tmp_p)
    return track

async def generate_mono_channel_original(segments, voice, duration_ms):
    track = AudioSegment.silent(duration=duration_ms)
    for seg in segments:
        text = seg['text'].strip()
        if not text or "[MUSIC]" in text.upper(): continue
        tmp_fn = f"tts_{uuid.uuid4()}.mp3"
        tmp_p = os.path.join(tempfile.gettempdir(), tmp_fn)
        try:
            await edge_tts.Communicate(text, voice).save(tmp_p)
            if not os.path.exists(tmp_p) or os.path.getsize(tmp_p) == 0: continue
            seg_audio = AudioSegment.from_file(tmp_p)
            start_ms = int(seg['start'] * 1000)
            if len(track) < start_ms + len(seg_audio):
                track += AudioSegment.silent(duration=(start_ms + len(seg_audio)) - len(track))
            track = track.overlay(seg_audio, position=start_ms)
        except: continue
        finally:
            if os.path.exists(tmp_p): os.unlink(tmp_p)
    return track

async def process_text_to_dub(text, target_lang, output_dir="outputs"):
    unique_id = str(uuid.uuid4())[:8]
    try:
        translator = GoogleTranslator(source='auto', target=target_lang)
        translated_text = translator.translate(text)
    except:
        translated_text = text # Fallback to original text if translation fails
    
    # Create mock segments for synthesis (one big segment)
    segments = [{
        "start": 0.0,
        "end": 0.0, # Will be determined by TTS length in synthesis
        "text": translated_text
    }]
    
    return {
        "unique_id": unique_id,
        "input_path": None, 
        "is_mono": False,
        "lang": target_lang,
        "t_l": segments, "t_r": segments,
        "orig_l_srt": f"1\n00:00:00,000 --> 00:00:10,000\n{text}",
        "orig_r_srt": f"1\n00:00:00,000 --> 00:00:10,000\n{text}",
        "tran_l_srt": f"1\n00:00:00,000 --> 00:00:10,000\n{translated_text}",
        "tran_r_srt": f"1\n00:00:00,000 --> 00:00:10,000\n{translated_text}",
        "duration": 10000 # Increased default buffer to 10s for text
    }

async def convert_to_asterisk(input_path, output_path):
    """
    Converts audio to Asterisk compatible format:
    WAV, 8000Hz, Mono, 16-bit PCM.
    """
    audio = AudioSegment.from_file(input_path)
    audio = audio.set_frame_rate(8000).set_channels(1).set_sample_width(2)
    audio.export(output_path, format="wav")
    return output_path

async def get_available_voices():
    """Returns a list of all available edge-tts voices."""
    return await edge_tts.list_voices()

async def create_stereo_dub(data, output_dir, sync_mode="independent", voice_type="M", asterisk_format=False):
    try:
        target_lang = data["lang"]
        is_mono = data.get("is_mono", False)
        
        channels = [None, None]
        if data.get("input_path"):
            input_audio = AudioSegment.from_file(data["input_path"])
            channels = input_audio.split_to_mono()
            if len(channels) < 2: channels = [channels[0], channels[0]]
        
        def get_voice_for_channel(chan_idx):
            v = voice_type
            
            # If it's a direct voice ID (e.g. "en-US-AndrewNeural"), use it directly
            if "-" in v and "Neural" in v:
                return v

            if v == "auto":
                if channels[chan_idx]:
                    v = detect_gender(channels[chan_idx])
                else:
                    v = "M" # Fallback
            
            voices = {
                "tr": {"M": "tr-TR-AhmetNeural", "F": "tr-TR-EmelNeural"},
                "en": {"M": "en-US-AndrewNeural", "F": "en-US-AvaNeural"},
                "de": {"M": "de-DE-ConradNeural", "F": "de-DE-KatjaNeural"},
                "fr": {"M": "fr-FR-RemyNeural", "F": "fr-FR-VivienneBruyanteNeural"},
                "es": {"M": "es-ES-AlvaroNeural", "F": "es-ES-ElviraNeural"},
                "it": {"M": "it-IT-GiuseppeNeural", "F": "it-IT-ElsaNeural"},
                "ru": {"M": "ru-RU-DmitryNeural", "F": "ru-RU-SvetlanaNeural"},
                "ar": {"M": "ar-SA-HamedNeural", "F": "ar-SA-ZariyahNeural"},
                "zh": {"M": "zh-CN-YunxiNeural", "F": "zh-CN-XiaoxiaoNeural"},
                "ja": {"M": "ja-JP-KeitaNeural", "F": "ja-JP-NanamiNeural"},
                "ko": {"M": "ko-KR-HyunsuNeural", "F": "ko-KR-SunHiNeural"},
                "pt": {"M": "pt-BR-AntonioNeural", "F": "pt-BR-FranciscaNeural"},
                "hi": {"M": "hi-IN-MadhurNeural", "F": "hi-IN-SwararaNeural"}
            }
            return voices.get(target_lang, voices["en"]).get(v, voices["en"]["M"])

        voice_l = get_voice_for_channel(0)
        voice_r = get_voice_for_channel(1)

        if sync_mode == "original":
            track_l = await generate_mono_channel_original(data["t_l"], voice_l, data["duration"])
            track_r = await generate_mono_channel_original(data["t_r"], voice_r, data["duration"])
        elif sync_mode == "independent":
            track_l = await generate_mono_channel_indep(data["t_l"], voice_l, data["duration"])
            track_r = await generate_mono_channel_indep(data["t_r"], voice_r, data["duration"])
        else: # Unified
            all_segments = []
            for s in data["t_l"]: all_segments.append({**s, "chan": "L"})
            for s in data["t_r"]: all_segments.append({**s, "chan": "R"})
            all_segments.sort(key=lambda x: x['start'])
            track_l = AudioSegment.silent(duration=data["duration"])
            track_r = AudioSegment.silent(duration=data["duration"])
            last_finished_time_ms = 0
            for seg in all_segments:
                text = seg['text'].strip()
                if not text or "[MUSIC]" in text.upper(): continue
                tmp_fn = f"tts_{uuid.uuid4()}.mp3"
                tmp_p = os.path.join(tempfile.gettempdir(), tmp_fn)
                try:
                    c_voice = voice_l if seg["chan"] == "L" else voice_r
                    await edge_tts.Communicate(text, c_voice).save(tmp_p)
                    if not os.path.exists(tmp_p) or os.path.getsize(tmp_p) == 0: continue
                    seg_audio = AudioSegment.from_file(tmp_p)
                    start_ms = max(int(seg['start'] * 1000), last_finished_time_ms)
                    if seg["chan"] == "L":
                        if len(track_l) < start_ms + len(seg_audio): track_l += AudioSegment.silent(duration=(start_ms + len(seg_audio)) - len(track_l))
                        track_l = track_l.overlay(seg_audio, position=start_ms)
                    else:
                        if len(track_r) < start_ms + len(seg_audio): track_r += AudioSegment.silent(duration=(start_ms + len(seg_audio)) - len(track_r))
                        track_r = track_r.overlay(seg_audio, position=start_ms)
                    last_finished_time_ms = start_ms + len(seg_audio)
                except: continue
                finally:
                    if os.path.exists(tmp_p): os.unlink(tmp_p)

        track_l = track_l.set_frame_rate(44100).set_channels(1)
        track_r = track_r.set_frame_rate(44100).set_channels(1)
        
        if is_mono:
            final_audio = track_l
            out_prefix = "mono"
        else:
            max_len = max(len(track_l), len(track_r))
            if len(track_l) < max_len: track_l += AudioSegment.silent(duration=max_len - len(track_l), frame_rate=44100)
            if len(track_r) < max_len: track_r += AudioSegment.silent(duration=max_len - len(track_r), frame_rate=44100)
            final_audio = track_l.pan(-1).overlay(track_r.pan(1))
            out_prefix = "stereo"
        
        unique_id = data["unique_id"]
        out_fn = f"{out_prefix}_{unique_id}_{sync_mode}_{voice_type}.mp3"
        meta_fn = f"{out_prefix}_{unique_id}_{sync_mode}_{voice_type}.json"
        out_p = os.path.join(output_dir, out_fn)
        meta_p = os.path.join(output_dir, meta_fn)
        
        meta_data = {
            "orig_l": data["orig_l_srt"], "orig_r": data["orig_r_srt"],
            "tran_l": data["tran_l_srt"], "tran_r": data["tran_r_srt"],
            "sync_mode": sync_mode,
            "voice_type": voice_type,
            "unique_id": unique_id,
            "is_mono": is_mono
        }
        with open(meta_p, "w", encoding="utf-8") as f:
            json.dump(meta_data, f, ensure_ascii=False, indent=2)

        await asyncio.to_thread(final_audio.export, out_p, format="mp3")
        return f"/outputs/{out_fn}"
    except Exception as e:
        traceback.print_exc()
        raise e
