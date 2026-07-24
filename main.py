"""
Main FastAPI application for XTTS-v2 TTS system.

Endpoints:
POST   /v1/voices/add
GET    /v1/voices
GET    /v1/voices/builtin
GET    /v1/voices/{voice_id}
GET    /v1/voices/{voice_id}/sample
DELETE /v1/voices/{voice_id}

POST   /v1/text-to-speech/{voice_id}

GET    /v1/history
GET    /health
GET    /v1/models
"""

import os
import shutil
import uuid
from contextlib import asynccontextmanager

from fastapi import (
    FastAPI,
    Form,
    UploadFile,
    File,
    Depends,
    HTTPException,
    status
)
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from config import VOICES_DIR, DEFAULT_LANGUAGE
from database import (
    init_db,
    get_db,
    Voice,
    GenerationHistory,
)
from tts_engine import engine
from audio_utils import prepare_reference_audio


# ============================================================
# STARTUP / SHUTDOWN
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("\n======================================")
    print("Starting TTS Application")
    print("======================================")

    # Initialize DB schema
    init_db()

    # Ensure audio storage directory exists
    VOICES_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[Startup] Voices directory: {VOICES_DIR}")

    # Load XTTS model state once
    engine.load()

    print(f"[Startup] Model loaded: {engine.model is not None}")
    print(f"[Startup] Execution Device: {engine.device}")
    print(f"[Startup] Built-in speakers available: {len(engine.builtin_speakers)}")

    yield

    print("[Shutdown] TTS application stopped.")


# ============================================================
# FASTAPI APP INITIALIZATION
# ============================================================

app = FastAPI(
    title="TTS System - XTTS-v2",
    version="1.0.0",
    lifespan=lifespan,
)


# ============================================================
# VOICE MANAGEMENT
# ============================================================

@app.post("/v1/voices/add", status_code=status.HTTP_201_CREATED)
def add_voice(
    name: str = Form(...),
    language: str = Form(DEFAULT_LANGUAGE),
    voice_sample: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    Upload reference audio, convert to optimal sample settings (22.05kHz mono WAV),
    and store record in the database.
    """
    if not voice_sample.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Voice sample file is required."
        )

    # Generate explicit unique ID upfront to avoid flush dependency issues
    voice_id = f"voice_{uuid.uuid4().hex[:10]}"

    raw_sample_path = VOICES_DIR / f"raw_{voice_id}.wav"
    clean_sample_path = VOICES_DIR / f"{voice_id}.wav"

    try:
        # 1. Save uploaded file temporarily
        with open(raw_sample_path, "wb") as buffer:
            shutil.copyfileobj(voice_sample.file, buffer)

        if not raw_sample_path.exists() or raw_sample_path.stat().st_size == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded audio sample is empty or corrupt."
            )

        # 2. Convert and preprocess reference audio for optimal XTTS cloning accuracy
        prepare_reference_audio(str(raw_sample_path), str(clean_sample_path))

        # 3. DB Insertion
        voice = Voice(
            id=voice_id,
            name=name,
            language=language,
            sample_path=str(clean_sample_path)
        )

        db.add(voice)
        db.commit()
        db.refresh(voice)

    except Exception as e:
        db.rollback()
        # Clean up files on error
        if raw_sample_path.exists():
            raw_sample_path.unlink()
        if clean_sample_path.exists():
            clean_sample_path.unlink()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to add voice: {str(e)}"
        )
    finally:
        # Always remove temporary raw input file
        if raw_sample_path.exists():
            raw_sample_path.unlink()

    print("\n========== VOICE ADDED ==========")
    print(f"Voice ID: {voice.id}")
    print(f"Name: {voice.name}")
    print(f"Language: {voice.language}")
    print(f"Sample path: {voice.sample_path}")

    return {
        "status": "success",
        "voice_id": voice.id,
        "name": voice.name,
        "language": voice.language,
        "sample_path": voice.sample_path,
        "file_exists": os.path.exists(voice.sample_path),
    }


@app.get("/v1/voices")
def list_voices(db: Session = Depends(get_db)):
    """Fetch all available cloned voices sorted by creation date."""
    voices = db.query(Voice).order_by(Voice.created_at.desc()).all()

    return [
        {
            "voice_id": voice.id,
            "name": voice.name,
            "language": voice.language,
            "sample_path": voice.sample_path,
            "file_exists": os.path.exists(voice.sample_path) if voice.sample_path else False,
            "created_at": voice.created_at,
        }
        for voice in voices
    ]


# ============================================================
# IMPORTANT: static route "/v1/voices/builtin" MUST be defined
# BEFORE the dynamic route "/v1/voices/{voice_id}".
# FastAPI matches routes top-to-bottom — if the dynamic route
# comes first, a request to /v1/voices/builtin gets swallowed
# by {voice_id} with voice_id="builtin", causing a false 404.
# ============================================================

@app.get("/v1/voices/builtin")
def list_builtin_voices():
    """List all preloaded XTTS-v2 speakers that don't require voice cloning."""
    if not engine.builtin_speakers:
        return {"count": 0, "voices": []}

    return {
        "count": len(engine.builtin_speakers),
        "voices": [
            {"voice_id": vid, "name": name}
            for vid, name in engine.builtin_speakers.items()
        ],
    }


@app.get("/v1/voices/{voice_id}")
def get_voice(voice_id: str, db: Session = Depends(get_db)):
    """Fetch details of a single cloned voice by ID."""
    voice = db.query(Voice).filter(Voice.id == voice_id).first()

    if not voice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Voice with ID {voice_id} not found."
        )

    file_exists = os.path.exists(voice.sample_path) if voice.sample_path else False

    return {
        "voice_id": voice.id,
        "name": voice.name,
        "language": voice.language,
        "sample_path": voice.sample_path,
        "file_exists": file_exists,
        "file_size": os.path.getsize(voice.sample_path) if file_exists else 0,
        "created_at": voice.created_at,
    }


@app.get("/v1/voices/{voice_id}/sample")
def get_voice_sample(voice_id: str, db: Session = Depends(get_db)):
    """Stream back the original sample WAV file for testing/playback."""
    voice = db.query(Voice).filter(Voice.id == voice_id).first()

    if not voice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Voice record not found."
        )

    if not voice.sample_path or not os.path.exists(voice.sample_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Voice sample file does not exist on disk."
        )

    return FileResponse(
        voice.sample_path,
        media_type="audio/wav",
        filename=f"{voice_id}_sample.wav"
    )


@app.delete("/v1/voices/{voice_id}")
def delete_voice(voice_id: str, db: Session = Depends(get_db)):
    """Remove voice from database and delete its WAV audio file from disk."""
    voice = db.query(Voice).filter(Voice.id == voice_id).first()

    if not voice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Voice not found."
        )

    # Delete audio file from storage if present
    if voice.sample_path and os.path.exists(voice.sample_path):
        try:
            os.remove(voice.sample_path)
        except OSError as e:
            print(f"[Warning] Failed to delete file {voice.sample_path}: {e}")

    # Delete record from database
    db.delete(voice)
    db.commit()

    return {
        "status": "deleted",
        "voice_id": voice_id
    }


# ============================================================
# TEXT TO SPEECH
# ============================================================

@app.post("/v1/text-to-speech/{voice_id}")
def generate_speech(
    voice_id: str,
    text: str = Form(...),
    language: str = Form(None),
    db: Session = Depends(get_db),
):
    """
    Synthesize audio using either:
      - a built-in preloaded XTTS voice (voice_id like 'builtin_claribel_dervla'), or
      - a user-cloned voice stored in the database.
    """
    if not text.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Text payload cannot be empty."
        )

    speaker_wav = None
    speaker_name = None
    voice_name_for_log = voice_id
    lang = language or DEFAULT_LANGUAGE

    # ---- Case 1: Built-in preloaded voice ----
    if engine.is_builtin_voice(voice_id):
        speaker_name = engine.builtin_speakers[voice_id]
        voice_name_for_log = speaker_name

    # ---- Case 2: Cloned voice from DB ----
    else:
        voice = db.query(Voice).filter(Voice.id == voice_id).first()
        if not voice:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Voice '{voice_id}' not found (not a builtin voice or a saved clone)."
            )
        if not voice.sample_path or not os.path.exists(voice.sample_path):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Voice sample file is missing at path: {voice.sample_path}"
            )
        speaker_wav = voice.sample_path
        lang = language or voice.language or DEFAULT_LANGUAGE
        voice_name_for_log = voice.name

    print("\n======================================")
    print("TTS REQUEST")
    print("======================================")
    print(f"Voice ID: {voice_id} | Name: {voice_name_for_log} | Lang: {lang}")
    print(f"Mode: {'builtin' if speaker_name else 'cloned'}")
    print(f"Text Input: {text}")

    # ---- Generate ----
    try:
        result = engine.generate(
            text=text,
            language=lang,
            voice_id=voice_id,
            speaker_wav=speaker_wav,
            speaker_name=speaker_name,
        )
    except Exception as e:
        print(f"[TTS ERROR] {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"TTS synthesis generation failed: {str(e)}"
        )

    # ---- Save history ----
    history = GenerationHistory(
        voice_id=voice_id,
        text=text,
        output_path=result["path"],
        cache_key=result.get("cache_key", ""),
        generation_time_seconds=int(result.get("time_seconds", 0)),
    )
    db.add(history)
    db.commit()

    return FileResponse(
        result["path"],
        media_type="audio/wav",
        filename=f"{voice_id}_output.wav",
        headers={
            "X-Voice-ID": voice_id,
            "X-Voice-Name": voice_name_for_log,
            "X-Cache-Hit": str(result.get("is_cached", False)),
            "X-Generation-Time": str(result.get("time_seconds", 0)),
        }
    )


# ============================================================
# HISTORY & HEALTH ENDPOINTS
# ============================================================

@app.get("/v1/history")
def get_history(db: Session = Depends(get_db), limit: int = 20):
    """Retrieve recent generation log records."""
    records = (
        db.query(GenerationHistory)
        .order_by(GenerationHistory.created_at.desc())
        .limit(limit)
        .all()
    )

    return [
        {
            "id": r.id,
            "voice_id": r.voice_id,
            "text": r.text,
            "output_path": r.output_path,
            "time_seconds": r.generation_time_seconds,
            "created_at": r.created_at,
        }
        for r in records
    ]


@app.get("/health")
def health():
    """Service health state endpoint."""
    return {
        "status": "running",
        "model_loaded": engine.model is not None,
        "device": engine.device,
    }


@app.get("/v1/models")
def list_models():
    """Get active TTS models metadata."""
    return {
        "models": ["xtts_v2"],
        "current": "xtts_v2",
        "device": engine.device,
        "model_loaded": engine.model is not None,
    }