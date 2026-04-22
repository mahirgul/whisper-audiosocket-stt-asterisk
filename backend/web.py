from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from contextlib import asynccontextmanager
import os
import psutil
import threading
import time
import uuid
import tempfile
import json
import zipfile
import shutil
import traceback
import asyncio
import sys
import argparse
import processor
import audiosocket_server as as_srv

# ---------------------------------------------------------------------------
# Startup / shutdown lifecycle
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Tell the AudioSocket server where the project root is
    as_srv.set_base_dir(BASE_DIR)
    config_path = os.path.join(BASE_DIR, "audiosocket.json")
    await as_srv.start_server(config_path)
    yield
    await as_srv.stop_server()

app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# Parse command line arguments
parser = argparse.ArgumentParser()
parser.add_argument("--model", type=str, default="medium", help="Whisper model to use")
args, unknown = parser.parse_known_args()

# Load model in background
threading.Thread(target=processor.load_model, args=(args.model,), daemon=True).start()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")
if not os.path.exists(OUTPUT_DIR): os.makedirs(OUTPUT_DIR)

AUDIOSOCKET_DIR = os.path.join(BASE_DIR, "audiosocket")
if not os.path.exists(AUDIOSOCKET_DIR): os.makedirs(AUDIOSOCKET_DIR)

AUDIOSOCKET_CONFIG = os.path.join(BASE_DIR, "audiosocket.json")

job_store = {}
job_stats = {
    "status": "loading", "cpu_usage": 0, "ram_usage_gb": 0, 
    "ram_total_gb": round(psutil.virtual_memory().total / (1024**3), 1), 
    "current_task": "Waking up AI..."
}

def update_stats():
    while True:
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

@app.get("/voices")
async def get_voices():
    """Returns all available edge-tts voices."""
    return await processor.get_available_voices()

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

@app.post("/process-text")
async def process_text(text: str = Form(...), target_lang: str = Form("en")):
    job_id = str(uuid.uuid4())
    processor.model_status = "processing"
    processor.current_task = "Translating text..."
    try:
        results = await processor.process_text_to_dub(text, target_lang, output_dir=OUTPUT_DIR)
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

@app.post("/synthesize/{job_id}")
async def synthesize(job_id: str, sync_mode: str = Form("independent"), voice_type: str = Form("M"), asterisk: bool = Form(False)):
    if job_id not in job_store: raise HTTPException(status_code=404, detail="Job not found")
    data = job_store[job_id]
    processor.model_status = "processing"
    processor.current_task = f"Generating Dubs ({sync_mode})..."
    try:
        audio_url = await processor.create_stereo_dub(data, OUTPUT_DIR, sync_mode=sync_mode, voice_type=voice_type)
        
        if asterisk:
            # Create Asterisk version
            mp3_filename = audio_url.split("/")[-1]
            mp3_path = os.path.join(OUTPUT_DIR, mp3_filename)
            wav_filename = mp3_filename.replace(".mp3", "_asterisk.wav")
            wav_path = os.path.join(OUTPUT_DIR, wav_filename)
            await processor.convert_to_asterisk(mp3_path, wav_path)
            
        del job_store[job_id] 
        return {"audio_url": audio_url}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        processor.model_status = "idle"
        processor.current_task = "Ready"

@app.get("/download/{filename}")
async def download_bundle(filename: str):
    base = filename.replace(".mp3", "")
    parts = base.split("_")
    if len(parts) < 2: raise HTTPException(status_code=400, detail="Invalid filename")
    
    unique_id = parts[1]
    zip_path = os.path.join(tempfile.gettempdir(), f"bundle_{base}.zip")
    
    try:
        with zipfile.ZipFile(zip_path, 'w') as zf:
            out_p = os.path.join(OUTPUT_DIR, f"{base}.mp3")
            if os.path.exists(out_p): zf.write(out_p, "dubbed_output.mp3")
            
            asterisk_p = os.path.join(OUTPUT_DIR, f"{base}_asterisk.wav")
            if os.path.exists(asterisk_p): zf.write(asterisk_p, "asterisk_8khz.wav")
            
            in_p = os.path.join(OUTPUT_DIR, f"input_{unique_id}.mp3")
            if os.path.exists(in_p): zf.write(in_p, "original_input.mp3")
            
            json_p = os.path.join(OUTPUT_DIR, f"{base}.json")
            if os.path.exists(json_p):
                with open(json_p, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                    zf.writestr("original_left.srt", meta.get("orig_l", ""))
                    zf.writestr("original_right.srt", meta.get("orig_r", ""))
                    zf.writestr("translated_left.srt", meta.get("tran_l", ""))
                    zf.writestr("translated_right.srt", meta.get("tran_r", ""))
        return FileResponse(zip_path, filename=f"bundle_{base}.zip", media_type="application/zip")
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

@app.get("/history")
async def get_history(page: int = 1, limit: int = 10):
    files = []
    for f in os.listdir(OUTPUT_DIR):
        # List both stereo and mono output files
        if (f.startswith("stereo_") or f.startswith("mono_")) and f.endswith(".mp3"):
            path = os.path.join(OUTPUT_DIR, f)
            meta_path = path.replace(".mp3", ".json")
            meta = {}
            if os.path.exists(meta_path):
                with open(meta_path, "r", encoding="utf-8") as m: meta = json.load(m)
            
            # Check for asterisk version
            has_asterisk = os.path.exists(path.replace(".mp3", "_asterisk.wav"))
            
            files.append({
                "name": f, "url": f"/outputs/{f}", 
                "time": os.path.getmtime(path), "meta": meta,
                "asterisk": has_asterisk
            })
    files.sort(key=lambda x: x['time'], reverse=True)
    start_idx = (page - 1) * limit
    end_idx = start_idx + limit
    return {
        "items": files[start_idx:end_idx],
        "total": len(files),
        "page": page,
        "pages": (len(files) + limit - 1) // limit
    }

@app.delete("/delete/{filename}")
async def delete_item(filename: str):
    """
    Deletes the generated MP3, its JSON metadata, and the original input file.
    """
    base = filename.replace(".mp3", "")
    parts = base.split("_")
    if len(parts) < 2: raise HTTPException(status_code=400, detail="Invalid filename")
    
    unique_id = parts[1]
    
    # Files to delete
    targets = [
        os.path.join(OUTPUT_DIR, f"{base}.mp3"),
        os.path.join(OUTPUT_DIR, f"{base}.json"),
        os.path.join(OUTPUT_DIR, f"{base}_asterisk.wav"),
        os.path.join(OUTPUT_DIR, f"input_{unique_id}.mp3")
    ]
    
    deleted_count = 0
    for t in targets:
        if os.path.exists(t):
            os.remove(t)
            deleted_count += 1
            
    return {"status": "deleted", "files_removed": deleted_count}

@app.delete("/delete-multiple")
async def delete_multiple(filenames: list[str]):
    """
    Deletes multiple generated recordings and their associated metadata/input files.
    """
    total_removed = 0
    for filename in filenames:
        base = filename.replace(".mp3", "")
        parts = base.split("_")
        if len(parts) < 2: continue
        
        unique_id = parts[1]
        targets = [
            os.path.join(OUTPUT_DIR, f"{base}.mp3"),
            os.path.join(OUTPUT_DIR, f"{base}.json"),
            os.path.join(OUTPUT_DIR, f"{base}_asterisk.wav"),
            os.path.join(OUTPUT_DIR, f"input_{unique_id}.mp3")
        ]
        for t in targets:
            if os.path.exists(t):
                os.remove(t)
                total_removed += 1
                
    return {"status": "deleted", "files_removed": total_removed}

@app.post("/api/v1/dub-text")
async def api_dub_text(
    text: str = Form(...), 
    target_lang: str = Form("en"), 
    sync_mode: str = Form("independent"), 
    voice_type: str = Form("M"),
    asterisk: bool = Form(False)
):
    """
    One-shot API to translate and dub text.
    Returns the final audio URL directly.
    """
    processor.model_status = "processing"
    processor.current_task = "API Request: Dubbing text..."
    try:
        # Step 1: Process text (translate)
        results = await processor.process_text_to_dub(text, target_lang, output_dir=OUTPUT_DIR)
        
        # Step 2: Synthesize directly
        audio_url = await processor.create_stereo_dub(
            results, OUTPUT_DIR, sync_mode=sync_mode, voice_type=voice_type
        )
        
        if asterisk:
            mp3_filename = audio_url.split("/")[-1]
            wav_path = os.path.join(OUTPUT_DIR, mp3_filename.replace(".mp3", "_asterisk.wav"))
            await processor.convert_to_asterisk(os.path.join(OUTPUT_DIR, mp3_filename), wav_path)

        return {
            "status": "success",
            "audio_url": audio_url,
            "filename": audio_url.split("/")[-1],
            "asterisk_url": audio_url.replace(".mp3", "_asterisk.wav") if asterisk else None
        }
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        processor.model_status = "idle"
        processor.current_task = "Ready"

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
    await as_srv.start_server(AUDIOSOCKET_CONFIG)
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
                # Count artifact files
                chunks = [
                    n for n in os.listdir(entry.path)
                    if n.startswith("chunk_") and n.endswith("_dub.mp3")
                ]
                sessions.append({
                    "uuid": entry.name,
                    "status": meta.get("status", "unknown"),
                    "started": meta.get("started"),
                    "completed": meta.get("completed"),
                    "total_chunks": meta.get("total_chunks", len(chunks)),
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
        int(n.split("_")[1])
        for n in files
        if n.startswith("chunk_") and "_" in n
    })

    for idx in chunk_indices:
        name = f"chunk_{idx:03d}"
        chunk_info = {"index": idx}
        for suffix, key in [("_orig.srt", "orig_srt"), ("_tran.srt", "tran_srt"),
                             ("_dub.mp3", "dub_mp3"), (".wav", "wav")]:
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
    Clients connect once and receive all events as they happen.
    """
    queue = as_srv._event_queue

    async def event_generator():
        # Send initial connection confirmation
        yield "data: {\"event\": \"connected\"}\n\n"
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=15.0)
                payload = json.dumps({"event": event["event"], "data": event["data"]})
                yield f"data: {payload}\n\n"
            except asyncio.TimeoutError:
                # Keep-alive ping
                yield ": ping\n\n"

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
