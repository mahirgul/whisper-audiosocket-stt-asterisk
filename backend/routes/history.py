from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse, FileResponse
import os
import uuid
import tempfile
import shutil
import time
import json
import zipfile
import io
import processor
import state

router = APIRouter()

@router.post("/transcribe")
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

        out_wav = os.path.join(state.OUTPUT_DIR, f"{job_id}.wav")
        shutil.copy2(tmp_path, out_wav)
        audio_url = f"/outputs/{job_id}.wav"

        results = await processor.transcribe_audio(
            tmp_path,
            output_dir=state.OUTPUT_DIR,
            label=filename,
            initial_prompt=initial_prompt,
            task=task,
        )

        meta = {
            "job_id": job_id,
            "audio_url": audio_url,
            "orig_l": results["orig_l_srt"],
            "orig_r": results["orig_r_srt"],
            "time": time.time(),
        }
        with open(os.path.join(state.OUTPUT_DIR, f"{job_id}.json"), "w", encoding="utf-8") as f:
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


@router.get("/history")
async def get_history(page: int = 1, limit: int = 20):
    items = []
    if os.path.exists(state.OUTPUT_DIR):
        for fn in os.listdir(state.OUTPUT_DIR):
            if fn.endswith(".json"):
                try:
                    meta_p = os.path.join(state.OUTPUT_DIR, fn)
                    with open(meta_p, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                        ts = meta.get("time") or os.path.getmtime(meta_p)
                        items.append({
                            "name": fn.replace(".json", ""),
                            "time": float(ts),
                            "url": meta.get("audio_url"),
                            "meta": meta,
                        })
                except Exception: pass

    items.sort(key=lambda x: x.get("time", 0), reverse=True)
    start = (page - 1) * limit
    return {
        "items": items[start : start + limit],
        "total": len(items),
        "page": page,
        "pages": max(1, (len(items) + limit - 1) // limit),
    }


@router.delete("/delete/{job_id}")
async def delete_job(job_id: str):
    for ext in [".json", ".wav"]:
        try:
            p = state.get_safe_path(state.OUTPUT_DIR, job_id + ext)
            if os.path.exists(p): os.unlink(p)
        except HTTPException: continue
    return {"status": "deleted"}


@router.delete("/delete-multiple")
async def delete_multiple(job_ids: list[str]):
    for job_id in job_ids:
        for ext in [".json", ".wav"]:
            try:
                p = state.get_safe_path(state.OUTPUT_DIR, job_id + ext)
                if os.path.exists(p): os.unlink(p)
            except HTTPException: continue
    return {"status": "deleted"}


@router.get("/download/{job_id}")
async def download_bundle(job_id: str):
    p = state.get_safe_path(state.OUTPUT_DIR, job_id + ".wav")
    if not os.path.exists(p): raise HTTPException(status_code=404)
    return FileResponse(p, filename=f"{job_id}.wav")


@router.get("/history/download-zip/{job_id}")
async def download_history_zip(job_id: str):
    zip_buffer = io.BytesIO()
    found = False
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for ext in [".json", ".wav"]:
            try:
                p = state.get_safe_path(state.OUTPUT_DIR, job_id + ext)
                if os.path.exists(p):
                    zip_file.write(p, arcname=job_id + ext)
                    found = True
            except HTTPException: continue
    if not found: raise HTTPException(status_code=404)
    zip_buffer.seek(0)
    return StreamingResponse(zip_buffer, media_type="application/zip", headers={"Content-Disposition": f"attachment; filename={job_id}.zip"})
