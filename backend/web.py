from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import os
import sys
import psutil
import threading
import time
import json
import argparse
import processor
import model_manager
import audiosocket_server as as_srv
import downloader
from downloader import log_info, log_success
import state

# Import sub-routers
from backend.routes.models import router as models_router
from backend.routes.history import router as history_router
from backend.routes.audiosocket import router as audiosocket_router

# ---------------------------------------------------------------------------
# CLI Argument Parsing
# ---------------------------------------------------------------------------
parser = argparse.ArgumentParser()
parser.add_argument(
    "--model", type=str, default="medium", help="Whisper model to use"
)
parser.add_argument(
    "--engine", type=str, default="openai", choices=["openai", "faster"], help="Whisper engine to use"
)
parser.add_argument(
    "--host", type=str, default=None, help="FastAPI host address"
)
parser.add_argument(
    "--port", type=int, default=None, help="FastAPI port"
)
args, unknown = parser.parse_known_args()

# ---------------------------------------------------------------------------
# Startup / shutdown lifecycle
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Setup system log callback for downloader
    downloader.set_system_log_callback(state.add_system_log)
    
    # Load default model/engine from config
    model_name = args.model
    engine_name = args.engine
    provider = "local"
    
    if os.path.exists(state.AUDIOSOCKET_CONFIG):
        try:
            with open(state.AUDIOSOCKET_CONFIG, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                model_name = cfg.get("whisper_model", model_name)
                engine_name = cfg.get("whisper_engine", engine_name)
                provider = cfg.get("api_provider", "local")
        except Exception:
            pass

    # Start the shared Whisper model worker process ONLY if provider is local
    if provider == "local":
        log_info(f"Starting local model worker: {model_name} ({engine_name})")
        model_manager.start(model_name, engine_name)
        
    # Tell the AudioSocket server where the project root is
    as_srv.set_base_dir(state.BASE_DIR)
    log_info("Starting AudioSocket server...")
    as_srv.start_server(state.AUDIOSOCKET_CONFIG)
    yield
    log_info("Shutting down servers...")
    as_srv.stop_server()
    as_srv.shutdown_worker()
    model_manager.stop()


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register sub-routers
app.include_router(models_router)
app.include_router(history_router)
app.include_router(audiosocket_router)

# ---------------------------------------------------------------------------
# Core server stats & live updates
# ---------------------------------------------------------------------------
def update_stats():
    # Initial call to avoid 0.0 on first read
    psutil.cpu_percent(interval=None)
    while True:
        # Sync model status from the dedicated model worker process
        processor.sync_status()
        state.job_stats["status"] = processor.model_status
        state.job_stats["current_task"] = processor.current_task
        state.job_stats["cpu_usage"] = psutil.cpu_percent(interval=None)
        state.job_stats["ram_usage_gb"] = round(
            psutil.virtual_memory().used / (1024**3), 2
        )
        
        # Include active tasks for the task list UI
        with model_manager._pending_lock:
            tasks = []
            for req_id, entry in model_manager._pending.items():
                tasks.append({
                    "id": req_id,
                    "label": entry.get("label", "Unknown"),
                    "elapsed": round(time.time() - entry.get("start_time", time.time()), 1)
                })
            state.job_stats["active_tasks"] = tasks

        time.sleep(1)


threading.Thread(target=update_stats, daemon=True).start()


@app.get("/stats")
async def get_stats():
    return state.job_stats


@app.get("/tasks")
async def get_tasks():
    with model_manager._pending_lock:
        tasks = []
        for req_id, entry in model_manager._pending.items():
            tasks.append({
                "id": req_id,
                "label": entry.get("label", "Unknown"),
                "elapsed": round(time.time() - entry.get("start_time", time.time()), 1)
            })
        return {
            "active_tasks": tasks,
            "count": len(tasks),
            "engine": model_manager._engine
        }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    await websocket.close()


# Static file mounts
app.mount("/outputs", StaticFiles(directory=state.OUTPUT_DIR), name="outputs")
app.mount("/audiosocket-files", StaticFiles(directory=state.AUDIOSOCKET_DIR), name="audiosocket_files")
app.mount("/", StaticFiles(directory=os.path.join(state.BASE_DIR, "frontend"), html=True), name="frontend")


if __name__ == "__main__":
    # Load configuration defaults for web server host/port
    web_host = "0.0.0.0"
    web_port = 8000
    if os.path.exists(state.AUDIOSOCKET_CONFIG):
        try:
            with open(state.AUDIOSOCKET_CONFIG, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                web_host = cfg.get("web_host", web_host)
                web_port = cfg.get("web_port", web_port)
        except Exception:
            pass

    # CLI args override configuration file defaults
    host = args.host if args.host is not None else web_host
    port = args.port if args.port is not None else web_port

    import uvicorn
    uvicorn.run(app, host=host, port=port, access_log=False)
