"""
model_manager.py

Manages a SINGLE dedicated Whisper model process.
Both the web pipeline (processor.py) and the AudioSocket pipeline
send transcription requests through the same queue — only ONE model
is ever loaded in memory.

Architecture:
    Main Process (FastAPI)
        ├── model_manager  (this module — queues + listener thread)
        │       └── Model Worker Process  (holds Whisper, transcribes)
        ├── processor.py  (calls model_manager.transcribe)
        └── audiosocket_server.py  (calls model_manager.transcribe)

Thread-safe: multiple callers can call transcribe() concurrently.
The model worker serializes them (one at a time).
"""

from __future__ import annotations

import multiprocessing
import threading
import os
import sys
import uuid
import time
import traceback

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_process: multiprocessing.Process | None = None
_request_queue: multiprocessing.Queue | None = None
_response_queue: multiprocessing.Queue | None = None

# Pending requests: req_id → {"event": threading.Event, "result": dict}
_pending: dict[str, dict] = {}
_pending_lock = threading.Lock()

_listener_thread: threading.Thread | None = None

# Observable status (read by web.py stats loop)
model_status: str = "loading"
current_task: str = "Waking up AI..."

_model_name: str = "medium"
_engine: str = "openai"


# ---------------------------------------------------------------------------
# Public API  (called from the MAIN process)
# ---------------------------------------------------------------------------


def start(model_name: str = "medium", engine: str = "openai") -> None:
    """Start the model worker process (call once at app startup)."""
    global _process, _request_queue, _response_queue, _listener_thread
    global model_status, current_task, _model_name, _engine

    _model_name = model_name
    _engine = engine
    model_status = "loading"
    current_task = f"Loading {model_name} ({engine})..."

    model_dir = os.path.join(os.getcwd(), "models", "whisper")
    os.makedirs(model_dir, exist_ok=True)

    _request_queue = multiprocessing.Queue()
    _response_queue = multiprocessing.Queue()

    _process = multiprocessing.Process(
        target=_worker_main,
        args=(_request_queue, _response_queue, model_name, model_dir, engine),
        daemon=True,
        name="WhisperModelWorker",
    )
    _process.start()
    print(f"[ModelManager] Worker process started (PID {_process.pid}, engine={engine})")

    # Background thread routes responses back to callers
    _listener_thread = threading.Thread(
        target=_response_listener,
        daemon=True,
        name="ModelManager-Listener",
    )
    _listener_thread.start()


def stop() -> None:
    """Graceful shutdown."""
    global _process, _request_queue, _response_queue, _listener_thread
    if _request_queue is not None:
        try:
            _request_queue.put(None)  # poison pill for worker process
        except Exception:
            pass

    if _response_queue is not None:
        try:
            _response_queue.put(None)  # poison pill for listener thread
        except Exception:
            pass

    if _process is not None:
        _process.join(timeout=10)
        if _process.is_alive():
            _process.terminate()
        _process = None

    if _listener_thread is not None:
        _listener_thread.join(timeout=2)
        _listener_thread = None

    _request_queue = None
    _response_queue = None


def transcribe(
    audio_path: str, *, timeout: float = 300.0, options: dict | None = None, label: str = "Task"
) -> dict:
    """
    Thread-safe transcription request.
    """
    global model_status, current_task

    if _request_queue is None or _process is None or not _process.is_alive():
        raise RuntimeError("Model worker is not running.")

    req_id = uuid.uuid4().hex
    event = threading.Event()
    entry = {"event": event, "result": None, "label": label, "start_time": time.time()}

    with _pending_lock:
        _pending[req_id] = entry
        # Immediate status update for pollers
        model_status = "processing"
        current_task = f"Transcribing {label}..."

    _request_queue.put(
        {"id": req_id, "audio_path": audio_path, "options": options or {}}
    )

    if not event.wait(timeout=timeout):
        with _pending_lock:
            _pending.pop(req_id, None)
        raise RuntimeError(f"Transcription timed out after {timeout}s")

    with _pending_lock:
        _pending.pop(req_id, None)

    msg = entry["result"]
    if msg.get("type") == "error":
        raise RuntimeError(msg["error"])

    return msg


async def transcribe_async(
    audio_path: str, *, timeout: float = 300.0, options: dict | None = None, label: str = "Task"
) -> dict:
    """Async wrapper for transcribe()."""
    import asyncio

    return await asyncio.to_thread(
        transcribe, audio_path, timeout=timeout, options=options, label=label
    )


def is_ready() -> bool:
    return model_status == "idle"


# ---------------------------------------------------------------------------
# Response listener  (runs in a background thread in the MAIN process)
# ---------------------------------------------------------------------------


def _response_listener() -> None:
    global model_status, current_task

    while True:
        try:
            msg = _response_queue.get()
            if msg is None:
                break

            if msg.get("type") == "status":
                with _pending_lock:
                    model_status = msg.get("status", model_status)
                    current_task = msg.get("task", current_task)
                continue

            req_id = msg.get("id")
            if req_id is None:
                continue

            with _pending_lock:
                entry = _pending.get(req_id)
            if entry is not None:
                entry["result"] = msg
                entry["event"].set()

        except Exception:
            traceback.print_exc()


# ---------------------------------------------------------------------------
# Worker process  (SEPARATE PROCESS — holds the Whisper model)
# ---------------------------------------------------------------------------


def _worker_main(
    req_q: multiprocessing.Queue,
    resp_q: multiprocessing.Queue,
    model_name: str,
    model_dir: str,
    engine: str = "openai",
) -> None:
    """Entry point for the model worker process."""
    # Fix encoding on Windows
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if sys.stderr and hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    try:
        import torch

        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"[ModelWorker] Engine: {engine.upper()}, Device: {device.upper()}")

        resp_q.put(
            {
                "type": "status",
                "status": "loading",
                "task": f"Loading {model_name} ({engine})...",
            }
        )

        model = None
        if engine == "faster":
            from faster_whisper import WhisperModel

            # Faster-whisper uses compute_type for quantization
            compute_type = "float16" if device == "cuda" else "int8"
            print(f"[ModelWorker] Loading faster-whisper '{model_name}' ({compute_type}) ...")
            model = WhisperModel(
                model_name,
                device=device,
                compute_type=compute_type,
                download_root=model_dir,
            )
        else:
            import whisper

            print(f"[ModelWorker] Loading openai-whisper '{model_name}' ...")
            model = whisper.load_model(
                model_name, device=device, download_root=model_dir
            )

        print("[ModelWorker] Model loaded. Ready for requests.")
        resp_q.put({"type": "status", "status": "idle", "task": "Ready"})

    except Exception as e:
        traceback.print_exc()
        resp_q.put(
            {"type": "status", "status": "error", "task": f"Error: {e}"}
        )
        return

    # Main request loop
    while True:
        try:
            request = req_q.get()
            if request is None:  # shutdown signal
                print("[ModelWorker] Shutting down.")
                break

            req_id = request["id"]
            audio_path = request["audio_path"]
            options = request.get("options", {})

            resp_q.put(
                {"type": "status", "status": "processing", "task": "AI..."}
            )

            try:
                if engine == "faster":
                    # Map openai options to faster-whisper options
                    if "logprob_threshold" in options:
                        options["log_prob_threshold"] = options.pop("logprob_threshold")
                    
                    segments_gen, info = model.transcribe(audio_path, **options)
                    
                    duration = info.duration
                    segments = []
                    text_parts = []
                    
                    for s in segments_gen:
                        seg_dict = {
                            "start": s.start,
                            "end": s.end,
                            "text": s.text,
                            "avg_logprob": s.avg_logprob,
                            "no_speech_prob": s.no_speech_prob,
                        }
                        segments.append(seg_dict)
                        text_parts.append(s.text)
                        
                        # Calculate progress percentage
                        if duration > 0:
                            pct = min(99, int((s.end / duration) * 100))
                            resp_q.put({
                                "type": "status", 
                                "status": "processing", 
                                "task": f"Transcribing... {pct}%"
                            })
                    
                    resp_q.put(
                        {
                            "type": "result",
                            "id": req_id,
                            "segments": segments,
                            "text": "".join(text_parts),
                            "language": info.language,
                        }
                    )
                else:
                    # Determine FP16 based on device to suppress CPU warnings
                    if "fp16" not in options:
                        options["fp16"] = device == "cuda"

                    # Remove unsupported options for openai whisper
                    options.pop("vad_filter", None)

                    result = model.transcribe(audio_path, **options)
                    resp_q.put(
                        {
                            "type": "result",
                            "id": req_id,
                            "segments": result.get("segments", []),
                            "text": result.get("text", ""),
                            "language": result.get("language", ""),
                        }
                    )
            except Exception as e:
                traceback.print_exc()
                resp_q.put(
                    {
                        "type": "error",
                        "id": req_id,
                        "error": str(e),
                    }
                )

            resp_q.put({"type": "status", "status": "idle", "task": "Ready"})

        except Exception:
            traceback.print_exc()
