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
import json
import requests

# ---------------------------------------------------------------------------
# Console Colors
# ---------------------------------------------------------------------------
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def log_info(msg): print(f"{Colors.OKBLUE}[INFO]{Colors.ENDC} {msg}")
def log_success(msg): print(f"{Colors.OKGREEN}[SUCCESS]{Colors.ENDC} {msg}")
def log_warn(msg): print(f"{Colors.WARNING}[WARN]{Colors.ENDC} {msg}")
def log_err(msg): print(f"{Colors.FAIL}[ERROR]{Colors.ENDC} {msg}")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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

_watchdog_thread: threading.Thread | None = None
_watchdog_stop_event = threading.Event()

# Observable status (read by web.py stats loop)
model_status: str = "loading"
current_task: str = "Waking up AI..."

_model_name: str = "medium"
_engine: str = "openai"


# ---------------------------------------------------------------------------
# Watchdog loop and check helper
# ---------------------------------------------------------------------------


def check_and_restart_worker() -> None:
    global _process, _model_name, _engine
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg_path = os.path.join(base, "audiosocket.json")
    auto_restart = True
    provider = "local"
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                auto_restart = cfg.get("auto_restart_worker", True)
                provider = cfg.get("api_provider", "local")
        except Exception:
            pass

    if provider != "local":
        # If API provider is selected, release local resources
        if _process is not None and _process.is_alive():
            log_info(f"Provider is '{provider}'. Stopping local model worker...")
            stop()
        return

    if _process is None:
        return

    if not _process.is_alive():
        if auto_restart and model_status != "error":
            log_warn("Whisper worker process died. Auto-restarting...")
            stop()
            start(_model_name, _engine)


def _watchdog_loop() -> None:
    while not _watchdog_stop_event.is_set():
        try:
            check_and_restart_worker()
        except Exception as e:
            print(f"[ModelManager-Watchdog] Error in watchdog: {e}")
        _watchdog_stop_event.wait(timeout=5.0)


# ---------------------------------------------------------------------------
# Public API  (called from the MAIN process)
# ---------------------------------------------------------------------------


def start(model_name: str = "medium", engine: str = "openai") -> None:
    """Start the model worker process (call once at app startup)."""
    global _process, _request_queue, _response_queue, _listener_thread
    global model_status, current_task, _model_name, _engine
    global _watchdog_thread

    _model_name = model_name
    _engine = engine
    model_status = "loading"
    current_task = f"Loading {model_name} ({engine})..."

    model_dir = os.path.join(BASE_DIR, "models", "whisper")
    os.makedirs(model_dir, exist_ok=True)

    # Load device and compute_type configurations from settings JSON
    device_config = "auto"
    compute_type_config = "default"
    config_path = os.path.join(BASE_DIR, "audiosocket.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                device_config = cfg.get("local_whisper_device", "auto")
                compute_type_config = cfg.get("local_whisper_compute_type", "default")
        except Exception:
            pass

    _request_queue = multiprocessing.Queue()
    _response_queue = multiprocessing.Queue()

    _process = multiprocessing.Process(
        target=_worker_main,
        args=(_request_queue, _response_queue, model_name, model_dir, engine, device_config, compute_type_config),
        daemon=True,
        name="WhisperModelWorker",
    )
    _process.start()
    print(f"[ModelManager] Worker process started (PID {_process.pid}, engine={engine}, device={device_config}, compute_type={compute_type_config})")

    # Background thread routes responses back to callers
    _listener_thread = threading.Thread(
        target=_response_listener,
        daemon=True,
        name="ModelManager-Listener",
    )
    _listener_thread.start()

    # Start the watchdog thread if not already running
    if _watchdog_thread is None or not _watchdog_thread.is_alive():
        _watchdog_stop_event.clear()
        _watchdog_thread = threading.Thread(
            target=_watchdog_loop,
            daemon=True,
            name="ModelManager-Watchdog",
        )
        _watchdog_thread.start()


def stop() -> None:
    """Graceful shutdown."""
    global _process, _request_queue, _response_queue, _listener_thread
    global _watchdog_thread, _watchdog_stop_event

    if _watchdog_thread is not None and threading.current_thread() != _watchdog_thread:
        _watchdog_stop_event.set()
        _watchdog_thread.join(timeout=2)
        _watchdog_thread = None

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


def transcribe_api(
    audio_path: str, base_url: str, api_key: str, model_name: str, options: dict
) -> dict:
    """Send audio file to an OpenAI-compatible Speech-to-Text API endpoint."""
    url = f"{base_url.rstrip('/')}/audio/transcriptions"
    
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        
    data = {
        "model": model_name,
        "response_format": "verbose_json"
    }
    
    if "temperature" in options:
        data["temperature"] = str(options["temperature"])
    if "initial_prompt" in options and options["initial_prompt"]:
        data["prompt"] = options["initial_prompt"]
    if "task" in options:
        # Route to translation if task is set to translate
        if options["task"] == "translate":
            url = f"{base_url.rstrip('/')}/audio/translations"
    if "language" in options and options["language"]:
        data["language"] = options["language"]

    with open(audio_path, "rb") as f:
        files = {
            "file": (os.path.basename(audio_path), f, "audio/wav")
        }
        resp = requests.post(url, headers=headers, data=data, files=files, timeout=120)
        
    if resp.status_code != 200:
        raise RuntimeError(f"API Error ({resp.status_code}): {resp.text}")
        
    return resp.json()


def transcribe(
    audio_path: str, *, timeout: float = 300.0, options: dict | None = None, label: str = "Task"
) -> dict:
    """
    Thread-safe transcription request.
    """
    global model_status, current_task

    # Load provider configuration
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg_path = os.path.join(base, "audiosocket.json")
    provider = "local"
    api_url = ""
    api_key = ""
    api_model = ""
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                provider = cfg.get("api_provider", "local")
                api_url = cfg.get("api_base_url", "")
                api_key = cfg.get("api_key", "")
                api_model = cfg.get("api_model_name", "")
        except Exception:
            pass

    if provider != "local":
        # Route to External API
        with _pending_lock:
            # Immediate status update for pollers
            model_status = "processing"
            current_task = f"Cloud AI: Transcribing {label}..."
        try:
            res = transcribe_api(audio_path, api_url, api_key, api_model, options or {})
            return {
                "type": "result",
                "segments": res.get("segments", []),
                "text": res.get("text", ""),
                "language": res.get("language", ""),
            }
        except Exception as e:
            traceback.print_exc()
            raise e
        finally:
            with _pending_lock:
                model_status = "idle"
                current_task = "Ready"

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
    device_config: str = "auto",
    compute_type_config: str = "default",
) -> None:
    """Entry point for the model worker process."""
    # Fix encoding on Windows
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if sys.stderr and hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    try:
        import torch

        # Device selection
        if device_config == "cuda":
            device = "cuda"
        elif device_config == "cpu":
            device = "cpu"
        else:
            device = "cuda" if torch.cuda.is_available() else "cpu"

        # Compute type selection
        if compute_type_config == "default":
            compute_type = "float16" if device == "cuda" else "int8"
        else:
            compute_type = compute_type_config

        print(f"[ModelWorker] Engine: {engine.upper()}, Device: {device.upper()}, Compute Type: {compute_type.upper()}")

        resp_q.put(
            {
                "type": "status",
                "status": "loading",
                "task": f"Loading {model_name} ({engine}, {device}, {compute_type})...",
            }
        )

        model = None
        if engine == "vibevoice":
            import vibevoice_helper
            vibevoice_dir = os.path.join(BASE_DIR, "models", "vibevoice")
            model = vibevoice_helper.load_vibevoice_model(device, compute_type, vibevoice_dir)
        elif engine == "faster":
            from faster_whisper import WhisperModel

            print(f"[ModelWorker] Loading faster-whisper '{model_name}' ({compute_type}) ...")
            model = WhisperModel(
                model_name,
                device=device,
                compute_type=compute_type,
                download_root=model_dir,
            )
        elif engine == "nvidia":
            # NVIDIA NeMo Models
            print(f"[ModelWorker] Checking for local NVIDIA NeMo model '{model_name}'...")
            nv_path = os.path.join(BASE_DIR, "models", "nvidia", f"{model_name}.nemo")
            if not os.path.exists(nv_path):
                raise RuntimeError(f"NVIDIA model file not found locally: {nv_path}")
            
            # NOTE: NeMo toolkit is NOT installed by default (it is very large).
            # We would need 'import nemo.collections.asr as nemo_asr' here.
            # For now, we will show a descriptive error if trying to RUN locally.
            print(f"[ModelWorker] Found {model_name}.nemo, but local NeMo engine is not yet implemented.")
            raise RuntimeError("Local NVIDIA NeMo execution is currently not implemented in this build. Please use NVIDIA API Provider for these models.")
        else:
            import whisper

            print(f"[ModelWorker] Loading openai-whisper '{model_name}' on {device}...")
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
                if engine == "vibevoice":
                    import vibevoice_helper
                    res = vibevoice_helper.transcribe_vibevoice(model, audio_path, options)
                    resp_q.put(
                        {
                            "type": "result",
                            "id": req_id,
                            "segments": res.get("segments", []),
                            "text": res.get("text", ""),
                            "language": res.get("language", ""),
                        }
                    )
                elif engine == "faster":
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
