from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse
from contextlib import asynccontextmanager
import os
import psutil
import threading
import time
import uuid
import tempfile
import json
import shutil
import asyncio
import sys
import argparse
import processor
import model_manager
import audiosocket_server as as_srv

# ---------------------------------------------------------------------------
# Startup / shutdown lifecycle
# ---------------------------------------------------------------------------

# Parse command line arguments (safe at import time — no side effects)
parser = argparse.ArgumentParser()
parser.add_argument("--model", type=str, default="medium", help="Whisper model to use")
args, unknown = parser.parse_known_args()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)

AUDIOSOCKET_DIR = os.path.join(BASE_DIR, "audiosocket")
os.makedirs(AUDIOSOCKET_DIR, exist_ok=True)

AUDIOSOCKET_CONFIG = os.path.join(BASE_DIR, "audiosocket.json")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start the shared Whisper model worker process
    model_manager.start(args.model)
    # Tell the AudioSocket server where the project root is
    as_srv.set_base_dir(BASE_DIR)
    config_path = os.path.join(BASE_DIR, "audiosocket.json")
    as_srv.start_server(config_path)
    yield
    as_srv.stop_server()
    model_manager.stop()

app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

job_store = {}
job_stats = {
    "status": "loading", "cpu_usage": 0, "ram_usage_gb": 0, 
    "ram_total_gb": round(psutil.virtual_memory().total / (1024**3), 1), 
    "current_task": "Waking up AI..."
}

def update_stats():
    while True:
        # Sync model status from the dedicated model worker process
        processor.sync_status()
        job_stats["status"] = processor.model_status
        job_stats["current_task"] = processor.current_task
        job_stats["cpu_usage"] = psutil.cpu_percent(interval=1)
        job_stats["ram_usage_gb"] = round(psutil.virtual_memory().used / (1024**3), 2)
        time.sleep(1)

threading.Thread(target=update_stats, daemon=True).start()

# ---------------------------------------------------------------------------
# Existing routes — unchanged
# ---------------------------------------------------------------------------

@app.get("/stats")
async def get_stats(): return job_stats

@app.post("/transcribe")
async def transcribe(file: UploadFile = File(...), target_lang: str = Form("en")):
    job_id = str(uuid.uuid4())
    processor.model_status = "processing"
    processor.current_task = "Transcribing..."
    fd, tmp_path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        with open(tmp_path, "wb") as f: f.write(await file.read())
        results = await processor.transcribe_audio(tmp_path, target_lang, output_dir=OUTPUT_DIR)
        job_store[job_id] = {**results, "lang": target_lang}
        return {
            "job_id": job_id,
            "orig_l": results["orig_l_srt"], "orig_r": results["orig_r_srt"],
            "tran_l": results["tran_l_srt"], "tran_r": results["tran_r_srt"]
        }
    except Exception as e:
        processor.model_status = "idle"
        processor.current_task = "Ready"
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        processor.model_status = "idle"
        if os.path.exists(tmp_path): os.unlink(tmp_path)

# ---------------------------------------------------------------------------
# AudioSocket routes
# ---------------------------------------------------------------------------

@app.get("/audiosocket/status")
async def as_status():
    """Returns AudioSocket server status and active connection list."""
    return as_srv.get_status()


@app.get("/audiosocket/config")
async def as_get_config():
    """Read the current audiosocket.json configuration."""
    return as_srv.load_config(AUDIOSOCKET_CONFIG)


@app.post("/audiosocket/config")
async def as_save_config(config: dict):
    """
    Save a new audiosocket.json and hot-reload the TCP server.
    The server will restart on the new port (if changed).
    """
    with open(AUDIOSOCKET_CONFIG, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    as_srv.start_server(AUDIOSOCKET_CONFIG)
    return {"status": "saved", "config": config}


@app.get("/audiosocket/sessions")
async def as_sessions(page: int = 1, limit: int = 20):
    """Paginated list of AudioSocket sessions (from audiosocket/ folder)."""
    sessions = []
    if os.path.exists(AUDIOSOCKET_DIR):
        for entry in os.scandir(AUDIOSOCKET_DIR):
            if entry.is_dir():
                meta_path = os.path.join(entry.path, "session.json")
                meta = {}
                if os.path.exists(meta_path):
                    try:
                        with open(meta_path, "r", encoding="utf-8") as f:
                            meta = json.load(f)
                    except Exception:
                        pass
                sessions.append({
                    "uuid": entry.name,
                    "status": meta.get("status", "unknown"),
                    "started": meta.get("started"),
                    "completed": meta.get("completed"),
                    "total_chunks": meta.get("total_chunks", 0),
                    "duration_s": meta.get("duration_s"),
                    "target_lang": meta.get("config", {}).get("target_lang", "?"),
                })

    sessions.sort(key=lambda x: x.get("started") or "", reverse=True)
    start_idx = (page - 1) * limit
    end_idx = start_idx + limit
    return {
        "items": sessions[start_idx:end_idx],
        "total": len(sessions),
        "page": page,
        "pages": max(1, (len(sessions) + limit - 1) // limit)
    }


@app.get("/audiosocket/sessions/{session_uuid}")
async def as_session_detail(session_uuid: str):
    """Full detail of one AudioSocket session including chunk list."""
    session_dir = os.path.join(AUDIOSOCKET_DIR, session_uuid)
    if not os.path.exists(session_dir):
        raise HTTPException(status_code=404, detail="Session not found")

    meta_path = os.path.join(session_dir, "session.json")
    meta = {}
    if os.path.exists(meta_path):
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

    # Enumerate chunks
    chunks = []
    files = sorted(os.listdir(session_dir))
    chunk_indices = sorted({
        int(n.split("_")[1].split(".")[0])
        for n in files
        if n.startswith("chunk_") and "_" in n
    })

    for idx in chunk_indices:
        name = f"chunk_{idx:03d}"
        chunk_info = {"index": idx}
        for suffix, key in [("_orig.srt", "orig_srt"), ("_tran.srt", "tran_srt"),
                             (".wav", "wav")]:
            fn = name + suffix
            if fn in files:
                chunk_info[key] = f"/audiosocket-files/{session_uuid}/{fn}"
                # Read SRT content inline
                if suffix.endswith(".srt"):
                    try:
                        with open(os.path.join(session_dir, fn), "r", encoding="utf-8") as f:
                            chunk_info[key + "_content"] = f.read()
                    except Exception:
                        pass
        chunks.append(chunk_info)

    return {"uuid": session_uuid, "meta": meta, "chunks": chunks}


@app.delete("/audiosocket/sessions/{session_uuid}")
async def as_delete_session(session_uuid: str):
    """Delete an entire AudioSocket session folder."""
    session_dir = os.path.join(AUDIOSOCKET_DIR, session_uuid)
    if not os.path.exists(session_dir):
        raise HTTPException(status_code=404, detail="Session not found")
    shutil.rmtree(session_dir)
    return {"status": "deleted", "uuid": session_uuid}


@app.get("/audiosocket/stream")
async def as_sse_stream():
    """
    Server-Sent Events endpoint for real-time AudioSocket monitoring.
    Polls the thread-safe queue from the AudioSocket thread.
    """
    async def event_generator():
        yield "data: {\"event\": \"connected\"}\n\n"
        while True:
            event = as_srv.get_event()
            if event is not None:
                payload = json.dumps({"event": event["event"], "data": event["data"]})
                yield f"data: {payload}\n\n"
            else:
                # No event — send keep-alive ping after a short sleep
                await asyncio.sleep(0.1)
                # Check again before sending ping
                event = as_srv.get_event()
                if event is not None:
                    payload = json.dumps({"event": event["event"], "data": event["data"]})
                    yield f"data: {payload}\n\n"
                else:
                    yield ": ping\n\n"
                    await asyncio.sleep(1.0)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        }
    )

# ---------------------------------------------------------------------------
# Static file mounts (order matters — most specific first)
# ---------------------------------------------------------------------------

app.mount("/outputs", StaticFiles(directory=OUTPUT_DIR), name="outputs")
app.mount("/audiosocket-files", StaticFiles(directory=AUDIOSOCKET_DIR), name="audiosocket_files")
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
