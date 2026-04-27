from fastapi import FastAPI, UploadFile, File, Form, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse, FileResponse
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
import argparse
import queue
import zipfile
import io
import processor
import model_manager
import audiosocket_server as as_srv
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Startup / shutdown lifecycle
# ---------------------------------------------------------------------------

# Parse command line arguments (safe at import time — no side effects)
parser = argparse.ArgumentParser()
parser.add_argument(
    "--model", type=str, default="medium", help="Whisper model to use"
)
parser.add_argument(
    "--engine", type=str, default="openai", choices=["openai", "faster"], help="Whisper engine to use"
)
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
    model_manager.start(args.model, args.engine)
    # Tell the AudioSocket server where the project root is
    as_srv.set_base_dir(BASE_DIR)
    config_path = os.path.join(BASE_DIR, "audiosocket.json")
    as_srv.start_server(config_path)
    yield
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

job_stats = {
    "status": "loading",
    "cpu_usage": 0,
    "ram_usage_gb": 0,
    "ram_total_gb": round(psutil.virtual_memory().total / (1024**3), 1),
    "current_task": "Starting...",
}


def update_stats():
    # Initial call to avoid 0.0 on first read
    psutil.cpu_percent(interval=None)
    while True:
        # Sync model status from the dedicated model worker process
        processor.sync_status()
        job_stats["status"] = processor.model_status
        job_stats["current_task"] = processor.current_task
        job_stats["cpu_usage"] = psutil.cpu_percent(interval=None)
        job_stats["ram_usage_gb"] = round(
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
            job_stats["active_tasks"] = tasks

        time.sleep(1)


threading.Thread(target=update_stats, daemon=True).start()


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


# ---------------------------------------------------------------------------
# Existing routes
# ---------------------------------------------------------------------------


@app.get("/stats")
async def get_stats():
    return job_stats


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    # This prevents attempts to connect to /ws from hitting the static mount
    await websocket.accept()
    await websocket.close()


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


@app.post("/transcribe")
async def transcribe(
    file: UploadFile = File(...),
    initial_prompt: str = Form(None),
    task: str = Form("transcribe"),
):
    job_id = str(uuid.uuid4())
    filename = file.filename
    fd, tmp_path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        with open(tmp_path, "wb") as f:
            f.write(await file.read())

        # Save original file to outputs for playback
        out_wav = os.path.join(OUTPUT_DIR, f"{job_id}.wav")
        shutil.copy2(tmp_path, out_wav)
        audio_url = f"/outputs/{job_id}.wav"

        results = await processor.transcribe_audio(
            tmp_path,
            output_dir=OUTPUT_DIR,
            label=filename,
            initial_prompt=initial_prompt,
            task=task,
        )

        # Save metadata for history
        meta = {
            "job_id": job_id,
            "audio_url": audio_url,
            "orig_l": results["orig_l_srt"],
            "orig_r": results["orig_r_srt"],
            "time": time.time(),
        }
        with open(
            os.path.join(OUTPUT_DIR, f"{job_id}.json"), "w", encoding="utf-8"
        ) as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        return {
            "job_id": job_id,
            "audio_url": audio_url,
            "orig_l": results["orig_l_srt"],
            "orig_r": results["orig_r_srt"],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


@app.get("/history")
async def get_history(page: int = 1, limit: int = 20):
    items = []
    for fn in os.listdir(OUTPUT_DIR):
        if fn.endswith(".json"):
            try:
                meta_p = os.path.join(OUTPUT_DIR, fn)
                with open(meta_p, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                    # Use meta 'time', or file mtime as float
                    ts = meta.get("time")
                    if ts is None:
                        ts = os.path.getmtime(meta_p)
                    
                    items.append(
                        {
                            "name": fn.replace(".json", ""),
                            "time": float(ts),
                            "url": meta.get("audio_url"),
                            "meta": meta,
                        }
                    )
            except Exception:
                pass

    # Sort by time descending (newest first)
    items.sort(key=lambda x: x.get("time", 0) or 0, reverse=True)
    start = (page - 1) * limit
    end = start + limit
    return {
        "items": items[start:end],
        "total": len(items),
        "page": page,
        "pages": max(1, (len(items) + limit - 1) // limit),
    }


@app.delete("/delete/{job_id}")
async def delete_job(job_id: str):
    for ext in [".json", ".wav"]:
        try:
            p = get_safe_path(OUTPUT_DIR, job_id + ext)
            if os.path.exists(p):
                os.unlink(p)
        except HTTPException:
            continue
    return {"status": "deleted"}


@app.delete("/delete-multiple")
async def delete_multiple(job_ids: list[str]):
    for job_id in job_ids:
        for ext in [".json", ".wav"]:
            try:
                p = get_safe_path(OUTPUT_DIR, job_id + ext)
                if os.path.exists(p):
                    os.unlink(p)
            except HTTPException:
                continue
    return {"status": "deleted"}


@app.get("/download/{job_id}")
async def download_bundle(job_id: str):
    # Just a simple redirect or direct file serve for now
    # In a full version, we could zip SRTs + WAV here
    p = get_safe_path(OUTPUT_DIR, job_id + ".wav")
    if not os.path.exists(p):
        raise HTTPException(status_code=404)
    from fastapi.responses import FileResponse

    return FileResponse(p, filename=f"{job_id}.wav")


@app.get("/history/download-zip/{job_id}")
async def download_history_zip(job_id: str):
    """Zips the metadata and audio for a history item."""
    zip_buffer = io.BytesIO()
    found = False
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for ext in [".json", ".wav"]:
            try:
                p = get_safe_path(OUTPUT_DIR, job_id + ext)
                if os.path.exists(p):
                    zip_file.write(p, arcname=job_id + ext)
                    found = True
            except HTTPException:
                continue

    if not found:
        raise HTTPException(status_code=404, detail="Item not found")

    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/x-zip-compressed",
        headers={"Content-Disposition": f"attachment; filename={job_id}.zip"},
    )


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
                # Ensure started is always a string (ISO format)
                started_val = meta.get("started")
                if not started_val:
                    started_val = datetime.fromtimestamp(
                        os.path.getmtime(entry.path), tz=timezone.utc
                    ).isoformat()
                else:
                    started_val = str(started_val)

                # Calculate fallback duration if missing
                duration = meta.get("duration_s")
                if not duration or duration == 0:
                    wav_p = os.path.join(entry.path, "chunk_001.wav")
                    if os.path.exists(wav_p):
                        duration = os.path.getsize(wav_p) / 16000.0
                    else:
                        duration = 0

                sessions.append(
                    {
                        "uuid": entry.name,
                        "status": meta.get("status", "unknown"),
                        "started": started_val,
                        "completed": meta.get("completed"),
                        "total_chunks": meta.get("total_chunks", 0),
                        "duration_s": float(duration or 0),
                        "target_lang": meta.get("target_lang", "original"),
                    }
                )

    # Sort by started timestamp descending (newest first)
    sessions.sort(key=lambda x: x["started"], reverse=True)
    start_idx = (page - 1) * limit
    end_idx = start_idx + limit
    return {
        "items": sessions[start_idx:end_idx],
        "total": len(sessions),
        "page": page,
        "pages": max(1, (len(sessions) + limit - 1) // limit),
    }


@app.get("/audiosocket/sessions/{session_uuid}")
async def as_session_detail(session_uuid: str):
    """Full detail of one AudioSocket session including chunk list."""
    session_dir = get_safe_path(AUDIOSOCKET_DIR, session_uuid, is_file=False)
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
    chunk_indices = sorted(
        {
            int(n.split("_")[1].split(".")[0])
            for n in files
            if n.startswith("chunk_") and "_" in n
        }
    )

    for idx in chunk_indices:
        name = f"chunk_{idx:03d}"
        chunk_info = {"index": idx}
        for suffix, key in [("_orig.srt", "orig_srt"), (".wav", "wav")]:
            fn = name + suffix
            if fn in files:
                chunk_info[key] = f"/audiosocket-files/{session_uuid}/{fn}"
                # Read SRT content inline
                if suffix.endswith(".srt"):
                    try:
                        srt_p = os.path.join(session_dir, fn)
                        with open(srt_p, "r", encoding="utf-8") as f:
                            chunk_info[key + "_content"] = f.read()
                    except Exception:
                        pass
        chunks.append(chunk_info)

    return {"uuid": session_uuid, "meta": meta, "chunks": chunks}


@app.delete("/audiosocket/sessions/{session_uuid}")
async def as_delete_session(session_uuid: str):
    """Delete an entire AudioSocket session folder."""
    try:
        session_dir = get_safe_path(AUDIOSOCKET_DIR, session_uuid, is_file=False)
        if not os.path.exists(session_dir):
            raise HTTPException(status_code=404, detail="Session not found")
        
        # On Windows, files might be locked. Try a retry or just ignore errors on single files.
        shutil.rmtree(session_dir, ignore_errors=True)
        
        # Double check if it's gone
        if os.path.exists(session_dir):
             # If still exists, try one more time without ignoring errors to get the real exception
             shutil.rmtree(session_dir)
             
        return {"status": "deleted", "uuid": session_uuid}
    except Exception as e:
        print(f"[Web] Error deleting session {session_uuid}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/audiosocket/bulk-delete")
async def as_bulk_delete(session_uuids: list[str]):
    """Delete multiple AudioSocket session folders."""
    deleted_count = 0
    for uuid_str in session_uuids:
        try:
            session_dir = get_safe_path(AUDIOSOCKET_DIR, uuid_str, is_file=False)
            if os.path.exists(session_dir):
                shutil.rmtree(session_dir, ignore_errors=True)
                deleted_count += 1
        except Exception as e:
            print(f"[Web] Error in bulk delete for {uuid_str}: {e}")
            continue
    return {"status": "deleted", "count": deleted_count}


@app.get("/audiosocket/sessions/{session_uuid}/download-zip")
async def as_download_session_zip(session_uuid: str):
    """Zips the entire session directory."""
    session_dir = get_safe_path(AUDIOSOCKET_DIR, session_uuid, is_file=False)
    if not os.path.exists(session_dir):
        raise HTTPException(status_code=404, detail="Session not found")

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for root, dirs, files in os.walk(session_dir):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, session_dir)
                zip_file.write(file_path, arcname=arcname)

    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/x-zip-compressed",
        headers={"Content-Disposition": f"attachment; filename={session_uuid}.zip"},
    )


@app.get("/audiosocket/stream")
async def as_sse_stream():
    """
    Server-Sent Events endpoint for real-time AudioSocket monitoring.
    Polls the thread-safe queue from the AudioSocket thread.
    """

    async def event_generator():
        q = as_srv.subscribe()
        yield 'data: {"event": "connected"}\n\n'
        last_ping = time.time()
        try:
            while True:
                try:
                    event = q.get_nowait()
                    if event["event"] == "shutdown":
                        break
                    pld = json.dumps(
                        {"event": event["event"], "data": event["data"]}
                    )
                    yield f"data: {pld}\n\n"
                except queue.Empty:
                    # Keep-alive ping (every 15s)
                    now = time.time()
                    if now - last_ping > 15:
                        yield ": ping\n\n"
                        last_ping = now

                    await asyncio.sleep(0.2)
        finally:
            as_srv.unsubscribe(q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ---------------------------------------------------------------------------
# Static file mounts (order matters — most specific first)
# ---------------------------------------------------------------------------

app.mount("/outputs", StaticFiles(directory=OUTPUT_DIR), name="outputs")
app.mount(
    "/audiosocket-files",
    StaticFiles(directory=AUDIOSOCKET_DIR),
    name="audiosocket_files",
)
app.mount(
    "/",
    StaticFiles(directory=os.path.join(BASE_DIR, "frontend"), html=True),
    name="frontend",
)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, access_log=False)

