from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
import os
import json
import shutil
import asyncio
import queue
from datetime import datetime, timezone
import audiosocket_server as as_srv
import model_manager
import state

router = APIRouter()

@router.get("/audiosocket/status")
async def as_status():
    return as_srv.get_status()


@router.get("/audiosocket/config")
async def as_get_config():
    return as_srv.load_config(state.AUDIOSOCKET_CONFIG)


@router.post("/audiosocket/config")
async def as_save_config(config: dict):
    """
    Save a new audiosocket.json and hot-reload the TCP server.
    The server will restart on the new port (if changed).
    """
    # Load old config for comparison
    old_cfg = {}
    if os.path.exists(state.AUDIOSOCKET_CONFIG):
        try:
            with open(state.AUDIOSOCKET_CONFIG, "r", encoding="utf-8") as f:
                old_cfg = json.load(f)
        except: pass

    with open(state.AUDIOSOCKET_CONFIG, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    
    # Reload the server settings
    as_srv.start_server(state.AUDIOSOCKET_CONFIG)

    # Log changes
    changes = []
    if config.get("port") != old_cfg.get("port"):
        changes.append(f"Port: {old_cfg.get('port')}->{config.get('port')}")
    if config.get("whisper_model") != old_cfg.get("whisper_model") or config.get("whisper_engine") != old_cfg.get("whisper_engine"):
        changes.append(f"AI: {config.get('whisper_model')} ({config.get('whisper_engine')})")
    if config.get("api_provider") != old_cfg.get("api_provider"):
        changes.append(f"Provider: {config.get('api_provider')}")
    
    if changes:
        state.add_system_log(" | ".join(changes), "SETTINGS")
    else:
        state.add_system_log("Settings saved", "SETTINGS")

    # Check provider and hot-swap local worker process
    new_provider = config.get("api_provider", "local")
    new_model = config.get("whisper_model", "medium")
    new_engine = config.get("whisper_engine", "faster")
    
    if new_provider == "local":
        # Check if local process is dead or if model/engine/device/compute_type has changed
        device_changed = config.get("local_whisper_device") != old_cfg.get("local_whisper_device")
        compute_changed = config.get("local_whisper_compute_type") != old_cfg.get("local_whisper_compute_type")
        
        if (
            model_manager._process is None 
            or not model_manager._process.is_alive() 
            or model_manager._model_name != new_model 
            or model_manager._engine != new_engine
            or device_changed
            or compute_changed
        ):
            model_manager.stop()
            model_manager.start(new_model, new_engine)
    else:
        if model_manager._process is not None and model_manager._process.is_alive():
            model_manager.stop()

    return {"status": "saved", "config": config}


@router.get("/audiosocket/sessions")
async def as_sessions(page: int = 1, limit: int = 20):
    sessions = []
    if os.path.exists(state.AUDIOSOCKET_DIR):
        for entry in os.scandir(state.AUDIOSOCKET_DIR):
            if entry.is_dir():
                meta = {}
                try:
                    with open(os.path.join(entry.path, "session.json"), "r", encoding="utf-8") as f:
                        meta = json.load(f)
                except: pass
                sessions.append({
                    "uuid": entry.name,
                    "status": meta.get("status", "unknown"),
                    "started": meta.get("started", datetime.fromtimestamp(os.path.getmtime(entry.path), tz=timezone.utc).isoformat()),
                    "duration_s": float(meta.get("duration_s", 0)),
                })
    sessions.sort(key=lambda x: x["started"], reverse=True)
    start = (page - 1) * limit
    return {"items": sessions[start:start+limit], "total": len(sessions), "page": page, "pages": max(1, (len(sessions)+limit-1)//limit)}


@router.get("/audiosocket/sessions/{session_uuid}")
async def as_session_detail(session_uuid: str):
    session_dir = state.get_safe_path(state.AUDIOSOCKET_DIR, session_uuid, is_file=False)
    meta = {}
    try:
        with open(os.path.join(session_dir, "session.json"), "r", encoding="utf-8") as f:
            meta = json.load(f)
    except: pass
    chunks = []
    files = sorted(os.listdir(session_dir))
    for fn in files:
        if fn.startswith("chunk_") and fn.endswith(".wav"):
            idx = int(fn.split("_")[1].split(".")[0])
            chunks.append({"index": idx, "wav": f"/audiosocket-files/{session_uuid}/{fn}"})
    return {"uuid": session_uuid, "meta": meta, "chunks": chunks}


@router.delete("/audiosocket/sessions/{session_uuid}")
async def as_delete_session(session_uuid: str):
    session_dir = state.get_safe_path(state.AUDIOSOCKET_DIR, session_uuid, is_file=False)
    shutil.rmtree(session_dir, ignore_errors=True)
    return {"status": "deleted"}


@router.get("/audiosocket/stream")
async def as_sse_stream():
    async def event_generator():
        q = as_srv.subscribe()
        yield 'data: {"event": "connected"}\n\n'
        try:
            while True:
                try:
                    event = q.get_nowait()
                    yield f"data: {json.dumps(event)}\n\n"
                except queue.Empty: await asyncio.sleep(0.5)
        finally: as_srv.unsubscribe(q)
    return StreamingResponse(event_generator(), media_type="text/event-stream")
