import os
import time
import uuid
import threading
import torch
from TTS.api import TTS

os.environ["COQUI_TOS_AGREED"] = "1"
os.environ["MPLBACKEND"] = "Agg"

from config import MODEL_NAME, OUTPUT_DIR
from text_processor import split_into_chunks
from audio_utils import combine_audio_chunks, get_cache_key, get_cached_path, is_cached


class TTSEngine:
    def __init__(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = None
        self.lock = threading.Lock()
        self.builtin_speakers = {}   # {"builtin_claribel_dervla": "Claribel Dervla", ...}

    def load(self):
        if self.model is not None:
            return
        print(f"[TTSEngine] Loading {MODEL_NAME} on {self.device}...")
        self.model = TTS(MODEL_NAME).to(self.device)
        print("[TTSEngine] Model loaded successfully.")

        # --- Cache built-in XTTS speakers (preloaded, no sample needed) ---
        raw_speakers = getattr(self.model, "speakers", None) or []
        for name in raw_speakers:
            key = "builtin_" + name.lower().replace(" ", "_")
            self.builtin_speakers[key] = name

        print(f"[TTSEngine] {len(self.builtin_speakers)} built-in speakers available.")

    def is_builtin_voice(self, voice_id: str) -> bool:
        return voice_id in self.builtin_speakers

    def generate(
        self,
        text: str,
        language: str,
        voice_id: str,
        speaker_wav: str = None,
        speaker_name: str = None,
    ) -> dict:
        """
        Exactly one of speaker_wav (cloned voice) or speaker_name (builtin XTTS voice)
        must be provided.
        """
        if self.model is None:
            raise RuntimeError("XTTS model is not loaded.")
        if not speaker_wav and not speaker_name:
            raise ValueError("Either speaker_wav or speaker_name must be provided.")

        # --- 1. Check Cache ---
        cache_key = get_cache_key(text, voice_id, language)
        cached_file = get_cached_path(cache_key)

        if is_cached(cache_key):
            print(f"[TTSEngine] Cache Hit! Serving cached file: {cached_file}")
            return {
                "path": str(cached_file),
                "cache_key": cache_key,
                "time_seconds": 0.0,
                "is_cached": True,
            }

        start = time.time()
        chunks = split_into_chunks(text)
        chunk_paths = []

        # --- 2. Generation (thread safe) ---
        with self.lock:
            for i, chunk in enumerate(chunks):
                temp_path = OUTPUT_DIR / f"temp_{voice_id}_{uuid.uuid4().hex}_{i}.wav"

                if speaker_name:
                    # Built-in preloaded XTTS voice — no reference audio needed
                    self.model.tts_to_file(
                        text=chunk,
                        speaker=speaker_name,
                        language=language,
                        file_path=str(temp_path),
                    )
                else:
                    # Cloned voice — needs reference sample
                    self.model.tts_to_file(
                        text=chunk,
                        speaker_wav=speaker_wav,
                        language=language,
                        file_path=str(temp_path),
                    )

                chunk_paths.append(str(temp_path))

        # --- 3. Merge Chunks ---
        final_path = cached_file

        if len(chunk_paths) == 1:
            os.replace(chunk_paths[0], final_path)
        else:
            combine_audio_chunks(chunk_paths, str(final_path))
            for path in chunk_paths:
                if os.path.exists(path):
                    os.remove(path)

        elapsed = round(time.time() - start, 2)
        print(f"[TTSEngine] Speech Generated in {elapsed}s")

        return {
            "path": str(final_path),
            "cache_key": cache_key,
            "time_seconds": elapsed,
            "is_cached": False,
        }


engine = TTSEngine()