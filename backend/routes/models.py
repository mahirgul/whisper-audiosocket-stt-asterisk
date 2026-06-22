from fastapi import APIRouter, HTTPException
import os
import downloader
import state

router = APIRouter()

@router.post("/models/download/{model_id}")
async def download_model(model_id: str, engine: str = "faster"):
    """Trigger a background download for a Whisper model or VibeVoice."""
    valid_whisper = ["tiny", "base", "small", "medium", "large-v3", "turbo"]
    
    if engine == "vibevoice":
        if model_id != "vibevoice-asr":
            raise HTTPException(status_code=400, detail="Invalid VibeVoice model ID")
    elif model_id not in valid_whisper:
        raise HTTPException(status_code=400, detail="Invalid model ID")
    
    key = f"{model_id}_{engine}"
    with downloader.download_lock:
        if key in downloader.downloading_models:
            return {"status": "already_downloading"}
        downloader.downloading_models.add(key)
        # Mark as queued so UI can show a pending status
        downloader.download_progress[key] = {
            "current_mb": 0,
            "total_mb": 0,
            "percent": 0.0,
            "status": "queued"
        }
        
    downloader.download_queue.put((model_id, engine, key, state.BASE_DIR))
    return {"status": "queued", "model": model_id, "engine": engine}


@router.get("/models/download-status")
async def get_download_status():
    """Returns the list of models currently being downloaded and their progress."""
    with downloader.download_lock:
        return {
            "downloading": list(downloader.downloading_models),
            "progress": dict(downloader.download_progress)
        }


@router.get("/models/list")
async def list_models():
    """Checks the models directory for downloaded models (Whisper & VibeVoice)."""
    model_dir = os.path.join(state.BASE_DIR, "models", "whisper")
    whisper_models = ["tiny", "base", "small", "medium", "large-v3", "turbo"]
    
    results = []
    for m in whisper_models:
        # OpenAI format
        openai_exists = os.path.exists(os.path.join(model_dir, f"{m}.pt"))
        # Faster-Whisper format
        from faster_whisper.utils import _MODELS
        repo_id = _MODELS.get(m)
        if not repo_id:
            repo_id = f"Systran/faster-whisper-{m}"
        hf_name = f"models--{repo_id.replace('/', '--')}"
        faster_exists = os.path.exists(os.path.join(model_dir, hf_name))
        
        results.append({
            "id": m,
            "openai": openai_exists,
            "faster": faster_exists,
            "type": "whisper"
        })
        
    # VibeVoice check
    vibevoice_dir = os.path.join(state.BASE_DIR, "models", "vibevoice")
    vibevoice_exists = os.path.exists(os.path.join(vibevoice_dir, "models--microsoft--VibeVoice-ASR-HF"))
    
    results.append({
        "id": "vibevoice-asr",
        "vibevoice": vibevoice_exists,
        "type": "vibevoice"
    })
    
    return results
