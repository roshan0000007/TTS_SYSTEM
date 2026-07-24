%%writefile /kaggle/working/TTS_SYSTEM/tts_engine.py
import os
import re
import time
import uuid
import threading
import torch
from TTS.api import TTS
from pydub import AudioSegment

os.environ["COQUI_TOS_AGREED"] = "1"
os.environ["MPLBACKEND"] = "Agg"

from config import MODEL_NAME, OUTPUT_DIR
from audio_utils import get_cache_key, get_cached_path, is_cached


def normalize_text_for_tts(text: str) -> str:
    if not text:
        return text
    text = text.strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"([,.!?;:।])(\S)", r"\1 \2", text)
    if text and text[-1] not in ".!?।":
        text += "."
    return text


def split_into_sentences(text: str) -> list[str]:
    sentences = re.split(r"(?<=[.!?।])\s+", text)
    return [s.strip() for s in sentences if s.strip()]


class TTSEngine:
    def __init__(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = None
        self.lock = threading.Lock()
        self.builtin_speakers = {}

        self.temperature = 0.65
        self.repetition_penalty = 5.0
        self.top_k = 50
        self.top_p = 0.85
        self.length_penalty = 1.0
        self.speed = 1.0

    def load(self):
        if self.model is not None:
            return
        print(f"[TTSEngine] Loading {MODEL_NAME} on {self.device}...")
        self.model = TTS(MODEL_NAME).to(self.device)
        print("[TTSEngine] Model loaded successfully.")

        if self.device == "cpu":
            print("⚠️ [TTSEngine] WARNING: Running on CPU. Generation will be slow.")

        raw_speakers = getattr(self.model, "speakers", None) or []
        for name in raw_speakers:
            key = "builtin_" + name.lower().replace(" ", "_")
            self.builtin_speakers[key] = name

        print(f"[TTSEngine] {len(self.builtin_speakers)} built-in speakers available.")

    def is_builtin_voice(self, voice_id: str) -> bool:
        return voice_id in self.builtin_speakers

    def _generate_segment(self, text, language, file_path, speaker_wav=None, speaker_name=None):
        common_args = dict(
            text=text,
            language=language,
            file_path=str(file_path),
            split_sentences=False,
            temperature=self.temperature,
            repetition_penalty=self.repetition_penalty,
            top_k=self.top_k,
            top_p=self.top_p,
            length_penalty=self.length_penalty,
            speed=self.speed,
        )
        if speaker_name:
            self.model.tts_to_file(speaker=speaker_name, **common_args)
        else:
            self.model.tts_to_file(speaker_wav=speaker_wav, **common_args)

    def generate(
        self,
        text: str,
        language: str,
        voice_id: str,
        speaker_wav: str = None,
        speaker_name: str = None,
    ) -> dict:
        if self.model is None:
            raise RuntimeError("XTTS model is not loaded.")
        if not speaker_wav and not speaker_name:
            raise ValueError("Either speaker_wav or speaker_name must be provided.")

        text = normalize_text_for_tts(text)
        if not text:
            raise ValueError("Text is empty after normalization.")

        cache_key = get_cache_key(text, voice_id, language)
        cached_file = get_cached_path(cache_key)

        # --- Cache check ---
        if is_cached(cache_key):
            print(f"[TTSEngine] Cache Hit! Serving cached file: {cached_file}")
            return {
                "path": str(cached_file),
                "cache_key": cache_key,
                "time_seconds": 0.0,
                "is_cached": True,
            }

        start = time.time()
        sentences = split_into_sentences(text)

        # --- IMPORTANT FIX: Har request ko apna UNIQUE temp file milta hai
        # (request-specific uuid ke saath) — taaki koi bhi do requests kabhi
        # ek dusre ki file ko overwrite/partial-read na kar sakein. Poora
        # generation complete hone ke BAAD hi hum final cache path pe
        # atomically rename karte hain — isliye reader ko kabhi bhi
        # incomplete/stale/wrong-voice ki audio nahi milegi. ---
        request_temp_path = OUTPUT_DIR / f"pending_{voice_id}_{uuid.uuid4().hex}.wav"

        with self.lock:
            if len(sentences) <= 1:
                self._generate_segment(text, language, request_temp_path, speaker_wav, speaker_name)
            else:
                segment_paths = []
                for i, sentence in enumerate(sentences):
                    seg_path = OUTPUT_DIR / f"seg_{voice_id}_{uuid.uuid4().hex}_{i}.wav"
                    self._generate_segment(sentence, language, seg_path, speaker_wav, speaker_name)
                    segment_paths.append(str(seg_path))

                combined = AudioSegment.empty()
                pause = AudioSegment.silent(duration=250)
                for i, seg_path in enumerate(segment_paths):
                    combined += AudioSegment.from_wav(seg_path)
                    if i < len(segment_paths) - 1:
                        combined += pause

                combined.export(str(request_temp_path), format="wav")

                for seg_path in segment_paths:
                    if os.path.exists(seg_path):
                        os.remove(seg_path)

            # --- Atomic rename: sirf tabhi cache file banti hai jab poora
            # generation successfully complete ho chuka ho. os.replace()
            # atomic operation hai — koi bhi reader kabhi partial file
            # nahi dekhega. ---
            os.replace(str(request_temp_path), str(cached_file))

        elapsed = round(time.time() - start, 2)
        print(f"[TTSEngine] Speech Generated in {elapsed}s ({len(sentences)} sentence(s)) for voice_id={voice_id}")

        return {
            "path": str(cached_file),
            "cache_key": cache_key,
            "time_seconds": elapsed,
            "is_cached": False,
        }


engine = TTSEngine()