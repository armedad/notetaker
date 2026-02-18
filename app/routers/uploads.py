import json
import logging
import os
import re
import uuid

from fastapi import APIRouter, File, HTTPException, UploadFile


def _sanitize_filename(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]", "_", name or "")
    return cleaned or "audio.wav"


def create_uploads_router(ctx) -> APIRouter:
    router = APIRouter()
    logger = logging.getLogger("notetaker.api.uploads")
    os.makedirs(ctx.uploads_dir, exist_ok=True)

    @router.post("/api/uploads/audio")
    async def upload_audio(file: UploadFile = File(...)) -> dict:
        original_name = _sanitize_filename(file.filename or "audio")
        _, ext = os.path.splitext(original_name)
        safe_ext = ext.lower() if ext else ""
        target_name = f"{uuid.uuid4().hex}{safe_ext}"
        target_path = os.path.join(ctx.uploads_dir, target_name)

        try:
            contents = await file.read()
            with open(target_path, "wb") as output:
                output.write(contents)
        except Exception as exc:
            logger.exception("Upload failed: %s", exc)
            raise HTTPException(status_code=500, detail="Upload failed") from exc

        data: dict = {}
        if os.path.exists(ctx.config_path):
            with open(ctx.config_path, "r", encoding="utf-8") as config_file:
                data = json.load(config_file)
        testing = data.get("testing", {})
        testing["audio_path"] = target_path
        testing["audio_name"] = original_name
        data["testing"] = testing
        with open(ctx.config_path, "w", encoding="utf-8") as config_file:
            json.dump(data, config_file, indent=2)

        logger.info("Audio uploaded: %s", target_path)
        return {"audio_path": target_path, "audio_name": original_name}

    return router
