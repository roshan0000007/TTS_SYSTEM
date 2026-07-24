"""
Saari settings yahan se load hoti hain (.env file se).
Kisi bhi file me hardcoded values nahi honi chahiye — sab yahan se aayega.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

# --- Database ---
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "3306")
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "tts_system")

DATABASE_URL = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# --- Ngrok ---
NGROK_TOKEN = os.getenv("NGROK_TOKEN", "")

# --- Folders (sab BASE_DIR ke andar hi honge) ---
VOICES_DIR = BASE_DIR / os.getenv("VOICES_DIR", "voices")
CACHE_DIR = BASE_DIR / os.getenv("CACHE_DIR", "cache")
OUTPUT_DIR = BASE_DIR / os.getenv("OUTPUT_DIR", "audio_output")

for folder in [VOICES_DIR, CACHE_DIR, OUTPUT_DIR]:
    folder.mkdir(parents=True, exist_ok=True)

# --- Model / TTS settings ---
MODEL_NAME = "tts_models/multilingual/multi-dataset/xtts_v2"
DEFAULT_LANGUAGE = os.getenv("DEFAULT_LANGUAGE", "hi")
MAX_CHUNK_LENGTH = int(os.getenv("MAX_CHUNK_LENGTH", "250"))
