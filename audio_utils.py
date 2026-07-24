import hashlib
import os
from pathlib import Path
from pydub import AudioSegment
from config import CACHE_DIR

def prepare_reference_audio(input_path: str, output_path: str) -> str:
    """
    Reference audio ko clean 22050Hz Mono WAV format mein convert karta hai.
    Yeh step XTTS-v2 voice accuracy ke liye sabse important hai.
    """
    audio = AudioSegment.from_file(input_path)
    
    # 3 sec minimum, max 12 sec crop for best cloning precision
    if len(audio) > 12000:
        audio = audio[:12000]
        
    audio = audio.set_frame_rate(22050).set_channels(1)
    audio.export(output_path, format="wav")
    return output_path

def get_cache_key(text: str, voice_id: str, language: str) -> str:
    raw = f"{text.strip()}|{voice_id}|{language}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def get_cached_path(cache_key: str) -> Path:
    return CACHE_DIR / f"{cache_key}.wav"

def is_cached(cache_key: str) -> bool:
    return get_cached_path(cache_key).exists()

def combine_audio_chunks(chunk_paths: list[str], output_path: str) -> str:
    combined = AudioSegment.empty()
    silence = AudioSegment.silent(duration=150)  # 150ms natural sentence pause

    for i, path in enumerate(chunk_paths):
        segment = AudioSegment.from_wav(path)
        combined += segment
        if i < len(chunk_paths) - 1:
            combined += silence

    combined.export(output_path, format="wav")
    return output_path