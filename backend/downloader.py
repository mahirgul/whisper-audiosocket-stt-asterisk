import os
import time
import threading
import queue
import urllib.request
from tqdm.auto import tqdm
import huggingface_hub
from faster_whisper.utils import _MODELS

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

# ---------------------------------------------------------------------------
# Global State & Queue
# ---------------------------------------------------------------------------
downloading_models = set()
download_progress = {}  # key -> {current_mb, total_mb, percent, status}
download_lock = threading.Lock()
download_queue = queue.Queue()

# Callback to log messages to the FastAPI frontend UI logs
_system_log_callback = None

def set_system_log_callback(cb):
    global _system_log_callback
    _system_log_callback = cb

def add_system_log(msg, category="SYSTEM"):
    if _system_log_callback:
        _system_log_callback(msg, category)

# ---------------------------------------------------------------------------
# Progress Tracking
# ---------------------------------------------------------------------------
def update_progress(key, current_bytes, total_bytes):
    with download_lock:
        current_mb = round(current_bytes / (1024 * 1024), 1)
        total_mb = round(total_bytes / (1024 * 1024), 1)
        percent = round((current_bytes / total_bytes) * 100, 1) if total_bytes > 0 else 0
        download_progress[key] = {
            "current_mb": current_mb,
            "total_mb": total_mb,
            "percent": percent
        }

class WebProgressTqdm(tqdm):
    current_key = None
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_percent = 0.0
        
    def update(self, n=1):
        super().update(n)
        # Update progress in UI only for model.bin weights (usually > 10MB)
        if self.total and self.total > 10 * 1024 * 1024:
            percent = round((self.n / self.total) * 100, 1)
            if percent != self._last_percent:
                self._last_percent = percent
                if WebProgressTqdm.current_key:
                    update_progress(WebProgressTqdm.current_key, self.n, self.total)

# ---------------------------------------------------------------------------
# Core Downloading Logic
# ---------------------------------------------------------------------------
def download_file_with_progress(url, dest_path, key):
    pbar = None
    try:
        print(f"{Colors.OKCYAN}[DOWNLOAD]{Colors.ENDC} Starting download for {key}...")
        
        def _report(block_num, block_size, total_size):
            nonlocal pbar
            current_bytes = block_num * block_size
            update_progress(key, current_bytes, total_size)
            
            if pbar is None:
                total_val = total_size if total_size > 0 else None
                pbar = tqdm(
                    total=total_val,
                    unit="B",
                    unit_scale=True,
                    unit_divisor=1024,
                    desc=f"[DOWNLOAD] {key}",
                    leave=True
                )
            
            pbar.n = current_bytes
            pbar.refresh()
            
        urllib.request.urlretrieve(url, dest_path, reporthook=_report)
        if pbar:
            pbar.n = pbar.total if pbar.total else pbar.n
            pbar.refresh()
            pbar.close()
        print(f"{Colors.OKGREEN}[DOWNLOAD COMPLETE]{Colors.ENDC} {key} completed.")
    except Exception as e:
        if pbar:
            pbar.close()
        raise e

def download_model_task(model_id: str, engine: str, base_dir: str):
    """Executes a single download task based on the target engine."""
    key = f"{model_id}_{engine}"
    try:
        log_info(f"Starting download: {model_id} ({engine})")
        add_system_log(f"Starting download: {model_id} ({engine})")
        
        if engine == "nvidia":
            log_warn("NVIDIA models cannot be downloaded or executed locally.")
            add_system_log("NVIDIA models cannot be downloaded or executed locally.", "WARNING")
            raise RuntimeError("NVIDIA models must be executed via the NVIDIA API Catalog provider.")
            
        elif engine == "faster":
            # Faster-Whisper models download via huggingface_hub snapshot_download
            model_dir = os.path.join(base_dir, "models", "whisper")
            repo_id = _MODELS.get(model_id)
            if not repo_id:
                repo_id = f"Systran/faster-whisper-{model_id}"
                
            WebProgressTqdm.current_key = key
            allow_patterns = [
                "config.json",
                "preprocessor_config.json",
                "model.bin",
                "tokenizer.json",
                "vocabulary.*",
            ]
            
            print(f"{Colors.OKCYAN}[DOWNLOAD]{Colors.ENDC} Starting download for {key} via Hugging Face...")
            huggingface_hub.snapshot_download(
                repo_id,
                allow_patterns=allow_patterns,
                cache_dir=model_dir,
                tqdm_class=WebProgressTqdm
            )
            print(f"\n{Colors.OKGREEN}[DOWNLOAD COMPLETE]{Colors.ENDC} {key} completed.")
            update_progress(key, 100, 100)
            
            # Instantiate WhisperModel to ensure it loads cleanly
            from faster_whisper import WhisperModel
            WhisperModel(model_id, device="cpu", compute_type="int8", download_root=model_dir)
            
        else:
            # OpenAI models direct download
            model_dir = os.path.join(base_dir, "models", "whisper")
            os.makedirs(model_dir, exist_ok=True)
            urls = {
                "tiny": "https://openaipublic.azureedge.net/main/whisper/models/65147644a518d12f04e32d6f3b26facc3f8dd46e5390956a9424a650c0ce22b9/tiny.pt",
                "base": "https://openaipublic.azureedge.net/main/whisper/models/ed3a0b6b1c0edf879ad9b11b1af5a0e6ab5db9205f891f668f8b0e6c6326e34e/base.pt",
                "small": "https://openaipublic.azureedge.net/main/whisper/models/9ecf779972d90ba49c06d968637d720dd632c55bbf19d441fb42bf17a411e794/small.pt",
                "medium": "https://openaipublic.azureedge.net/main/whisper/models/345ae4da62f9b3d59415adc60127b97c714f32e89e936602e85993674d08dcb1/medium.pt",
                "large-v3": "https://openaipublic.azureedge.net/main/whisper/models/e5b1a55b89c1367dacf97e3e19bfd829a01529dbfdeefa8caeb59b3f1b81dadb/large-v3.pt",
                "turbo": "https://openaipublic.azureedge.net/main/whisper/models/aff26ae408abcba5fbf8813c21e62b0941638c5f6eebfb145be0c9839262a19a/large-v3-turbo.pt"
            }
            if model_id in urls:
                download_file_with_progress(urls[model_id], os.path.join(model_dir, f"{model_id}.pt"), key)
            else:
                import download_models as dm
                dm.download_models([model_id])
            
        log_success(f"Download complete: {model_id} ({engine})")
        add_system_log(f"Download complete: {model_id} ({engine})")
    except Exception as e:
        log_err(f"Error downloading {model_id} ({engine}): {e}")
        add_system_log(f"Download failed: {model_id} ({engine}) - {e}", "ERROR")
    finally:
        with download_lock:
            downloading_models.discard(key)
            # Remove progress info after 10 seconds
            def _cleanup():
                time.sleep(10)
                with download_lock:
                    download_progress.pop(key, None)
            threading.Thread(target=_cleanup, daemon=True).start()

# ---------------------------------------------------------------------------
# Sequential Queue Worker
# ---------------------------------------------------------------------------
def download_queue_worker():
    global downloading_models, download_progress
    while True:
        try:
            model_id, engine, key, base_dir = download_queue.get()
            
            # Remove queued status before starting
            with download_lock:
                if key in download_progress and download_progress[key].get("status") == "queued":
                    download_progress.pop(key, None)
            
            download_model_task(model_id, engine, base_dir)
            download_queue.task_done()
        except Exception as e:
            log_err(f"Error in download queue worker: {e}")
            time.sleep(1)

# Start single background downloader thread
threading.Thread(target=download_queue_worker, daemon=True, name="DownloadQueueWorker").start()
