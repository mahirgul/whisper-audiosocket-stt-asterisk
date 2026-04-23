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


# ---------------------------------------------------------------------------
# Public API  (called from the MAIN process)
# ---------------------------------------------------------------------------

def start(model_name: str = "medium") -> None:
    """Start the model worker process (call once at app startup)."""
    global _process, _request_queue, _response_queue, _listener_thread
    global model_status, current_task, _model_name

    _model_name = model_name
    model_status = "loading"
    current_task = f"Loading {model_name} model..."

    model_dir = os.path.join(os.getcwd(), "models", "whisper")
    os.makedirs(model_dir, exist_ok=True)

    _request_queue = multiprocessing.Queue()
    _response_queue = multiprocessing.Queue()

    _process = multiprocessing.Process(
        target=_worker_main,
        args=(_request_queue, _response_queue, model_name, model_dir),
        daemon=True,
        name="WhisperModelWorker",
    )
    _process.start()
    print(f"[ModelManager] Worker process started (PID {_process.pid})")

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
            _request_queue.put(None)        # poison pill for worker process
        except Exception:
            pass
    
    if _response_queue is not None:
        try:
            _response_queue.put(None)       # poison pill for listener thread
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


def transcribe(audio_path: str, *, timeout: float = 300.0) -> dict:
    """
    Thread-safe transcription request.

    Sends the audio file path to the model worker and blocks until the
    result is ready.  Returns a dict with keys:
        segments, text, language

    Raises RuntimeError on model error or timeout.
    """
    global model_status, current_task

    if _request_queue is None or _process is None or not _process.is_alive():
        raise RuntimeError("Model worker is not running.")

    req_id = uuid.uuid4().hex
    event = threading.Event()
    entry = {"event": event, "result": None}

    with _pending_lock:
        _pending[req_id] = entry
        # Set status to processing immediately to avoid race conditions with web.py pollers
        model_status = "processing"
        current_task = "Transcribing..."

    _request_queue.put({"id": req_id, "audio_path": audio_path})

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


async def transcribe_async(audio_path: str, *, timeout: float = 300.0) -> dict:
    """Async wrapper — runs transcribe() in a thread so it doesn't block the event loop."""
    import asyncio
    return await asyncio.to_thread(transcribe, audio_path, timeout=timeout)


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

def _worker_main(req_q: multiprocessing.Queue,
                 resp_q: multiprocessing.Queue,
                 model_name: str,
                 model_dir: str) -> None:
    """Entry point for the model worker process."""
    # Fix encoding on Windows
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if sys.stderr and hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    try:
        import whisper

        # Check if model file exists on disk
        model_path = os.path.join(model_dir, f"{model_name}.pt")
        if os.path.exists(model_path):
            resp_q.put({"type": "status", "status": "loading",
                        "task": f"Loading {model_name} model from disk..."})
        else:
            resp_q.put({"type": "status", "status": "loading",
                        "task": f"Downloading {model_name} model (this may take a while)..."})

        print(f"[ModelWorker] Loading Whisper '{model_name}' ...")
        model = whisper.load_model(model_name, device="cpu", download_root=model_dir)
        print(f"[ModelWorker] Model loaded. Ready for requests.")

        resp_q.put({"type": "status", "status": "idle", "task": "Ready"})

    except Exception as e:
        traceback.print_exc()
        resp_q.put({"type": "status", "status": "error",
                    "task": f"Error loading model: {e}"})
        return

    # Main request loop
    while True:
        try:
            request = req_q.get()
            if request is None:                     # shutdown signal
                print("[ModelWorker] Shutting down.")
                break

            req_id = request["id"]
            audio_path = request["audio_path"]

            resp_q.put({"type": "status", "status": "processing",
                        "task": "Transcribing..."})

            try:
                result = model.transcribe(audio_path)
                resp_q.put({
                    "type": "result",
                    "id": req_id,
                    "segments": result.get("segments", []),
                    "text": result.get("text", ""),
                    "language": result.get("language", ""),
                })
            except Exception as e:
                traceback.print_exc()
                resp_q.put({
                    "type": "error",
                    "id": req_id,
                    "error": str(e),
                })

            resp_q.put({"type": "status", "status": "idle", "task": "Ready"})

        except Exception:
            traceback.print_exc()
