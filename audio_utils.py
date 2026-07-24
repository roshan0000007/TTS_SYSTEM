
"""
Audio processing utilities — kisi bhi input format ko XTTS-friendly clean
WAV mein convert karta hai. Silence-aware trimming use karta hai taaki
reference audio kabhi bhi word/sentence ke beech mein na kate.
"""
import hashlib
from pathlib import Path
from pydub import AudioSegment
from pydub.silence import detect_leading_silence, detect_silence
from pydub.exceptions import CouldntDecodeError
from config import CACHE_DIR

ALLOWED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".wma"}

MIN_DURATION_MS = 3000
MAX_DURATION_MS = 15000
TARGET_SAMPLE_RATE = 22050
TARGET_CHANNELS = 1
SILENCE_THRESHOLD_DB = -42.0
MIN_SILENCE_LEN_MS = 150


def is_supported_audio_format(filename: str) -> bool:
    ext = Path(filename).suffix.lower()
    return ext in ALLOWED_AUDIO_EXTENSIONS


def trim_leading_trailing_silence(audio: AudioSegment) -> AudioSegment:
    """Start aur end ke dead-air/silence ko trim karta hai."""
    start_trim = detect_leading_silence(audio, silence_threshold=SILENCE_THRESHOLD_DB)
    end_trim = detect_leading_silence(audio.reverse(), silence_threshold=SILENCE_THRESHOLD_DB)
    duration = len(audio)
    trimmed = audio[start_trim: duration - end_trim]
    return trimmed if len(trimmed) > 500 else audio


def smart_trim_to_max_duration(audio: AudioSegment, max_duration_ms: int) -> tuple:
    """
    IMPORTANT FIX: Agar audio max_duration se lamba hai, isse hard cutoff
    (bilkul max_duration_ms pe kaat dena) nahi karte — kyunki isse word/sentence
    ke beech mein cut lag sakta hai (jaisa pehle ho raha tha: 15.0s pe cut
    laga jabki speech active thi, nearest pause 13.4s pe tha).

    Iski jagah, max_duration se pehle SABSE NAZDEEK natural silence/pause
    dhundte hain, aur wahin trim karte hain — taaki reference clip hamesha
    ek complete word/phrase pe khatam ho, beech mein nahi.
    """
    if len(audio) <= max_duration_ms:
        return audio, False

    # Max duration tak ke audio mein saare silence gaps dhundo
    search_region = audio[:max_duration_ms]
    silences = detect_silence(
        search_region,
        min_silence_len=MIN_SILENCE_LEN_MS,
        silence_thresh=SILENCE_THRESHOLD_DB
    )

    if silences:
        # Sabse aakhri (max_duration ke sabse pass wala) silence gap ka
        # beech ka point use karo trim point ke roop mein — natural pause
        last_silence = silences[-1]
        cut_point = (last_silence[0] + last_silence[1]) // 2
        # Bahut chhota trim na ho jaye (kam se kam MIN_DURATION_MS rakho)
        if cut_point >= MIN_DURATION_MS:
            return audio[:cut_point], True

    # Agar koi silence nahi mila (continuous speech bina pause ke), to
    # majboori mein hard cutoff hi karna padega — lekin yeh rare case hai
    return audio[:max_duration_ms], True


def prepare_reference_audio(input_path: str, output_path: str) -> dict:
    try:
        audio = AudioSegment.from_file(input_path)
    except CouldntDecodeError as e:
        raise ValueError(
            f"Audio file decode nahi ho payi. File corrupt ho sakti hai ya "
            f"format unsupported hai. Error: {str(e)}"
        )
    except Exception as e:
        raise ValueError(f"Audio processing failed: {str(e)}")

    original_duration_ms = len(audio)

    if original_duration_ms < MIN_DURATION_MS:
        raise ValueError(
            f"Audio bahut chhota hai ({original_duration_ms/1000:.1f}s). "
            f"Kam se kam {MIN_DURATION_MS/1000:.0f} second ka clean sample chahiye."
        )

    # --- 1. Leading/trailing silence trim karo ---
    audio = trim_leading_trailing_silence(audio)

    # --- 2. Smart trim (silence-boundary aware, word ke beech mein nahi katega) ---
    audio, was_trimmed = smart_trim_to_max_duration(audio, MAX_DURATION_MS)

    # --- 3. Normalize format ---
    audio = audio.set_frame_rate(TARGET_SAMPLE_RATE)
    audio = audio.set_channels(TARGET_CHANNELS)
    audio = audio.set_sample_width(2)

    # --- 4. Volume normalize ---
    if audio.max_dBFS != float("-inf"):
        change = -3.0 - audio.max_dBFS
        audio = audio.apply_gain(change)

    audio.export(output_path, format="wav")

    return {
        "original_duration_seconds": round(original_duration_ms / 1000, 2),
        "final_duration_seconds": round(len(audio) / 1000, 2),
        "was_trimmed": was_trimmed,
        "sample_rate": TARGET_SAMPLE_RATE,
        "channels": TARGET_CHANNELS,
    }


def get_cache_key(text: str, voice_id: str, language: str) -> str:
    raw = f"{text.strip()}|{voice_id}|{language}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get_cached_path(cache_key: str) -> Path:
    return CACHE_DIR / f"{cache_key}.wav"


def is_cached(cache_key: str) -> bool:
    return get_cached_path(cache_key).exists()