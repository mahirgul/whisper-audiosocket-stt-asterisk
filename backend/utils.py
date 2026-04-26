import time

def to_srt(segments: list) -> str:
    """Convert whisper-style segment list to SRT string."""
    srt = []
    for i, s in enumerate(segments):
        def ts(x):
            return (
                f"{time.strftime('%H:%M:%S', time.gmtime(x))},"
                f"{int((x % 1) * 1000):03d}"
            )
        txt = s["text"].strip()
        srt.append(f"{i+1}\n{ts(s['start'])} --> {ts(s['end'])}\n{txt}\n")
    return "\n".join(srt)

def process_segments_with_music(
    segments, min_gap=3.0, no_speech_threshold=0.6
):
    """
    Identifies silence gaps and low-probability speech to tag [MUSIC].
    """
    processed = []
    if not segments:
        return processed
    for i, s in enumerate(segments):
        prob = s.get("no_speech_prob", 0)
        is_music = prob > no_speech_threshold or not s["text"].strip()
        if is_music:
            s["text"] = "[MUSIC]"
        if i > 0:
            prev_end = processed[-1]["end"]
            curr_start = s["start"]
            if curr_start - prev_end > min_gap:
                processed.append(
                    {"start": prev_end, "end": curr_start, "text": "[MUSIC]"}
                )
        processed.append(s)
    return processed
