import os
import sys
import psutil
from fastapi import HTTPException

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Add root directory to sys.path to allow importing download_models.py
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)

AUDIOSOCKET_DIR = os.path.join(BASE_DIR, "audiosocket")
os.makedirs(AUDIOSOCKET_DIR, exist_ok=True)

AUDIOSOCKET_CONFIG = os.path.join(BASE_DIR, "audiosocket.json")

job_stats = {
    "status": "loading",
    "cpu_usage": 0,
    "ram_usage_gb": 0,
    "ram_total_gb": round(psutil.virtual_memory().total / (1024**3), 1),
    "current_task": "Starting...",
    "system_logs": []
}

def add_system_log(message: str, category: str = "SYSTEM"):
    """Adds a timestamped message to the system logs."""
    from datetime import datetime
    now = datetime.now().strftime("%H:%M:%S")
    log_entry = f"[{now}] [{category}] {message}"
    job_stats["system_logs"].insert(0, log_entry)
    # Keep only last 100 logs
    job_stats["system_logs"] = job_stats["system_logs"][:100]

def get_safe_path(base_dir, user_input, is_file=True):
    """
    Constructs a safe path by resolving real paths and ensuring the result
    is within the intended base directory.
    """
    safe_root = os.path.realpath(base_dir)
    target_path = os.path.realpath(os.path.join(safe_root, user_input))
    if not target_path.startswith(safe_root + os.sep):
        # Also allow the root itself if it's a directory
        if not is_file and target_path == safe_root:
            return target_path
        raise HTTPException(status_code=400, detail="Invalid path or ID")
    return target_path
