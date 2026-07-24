import os
import re
import time
import threading
import torch
import torchaudio
from TTS.api import TTS

os.environ["COQUI_TOS_AGREED"] = "1"
os.environ["MPLBACKEND"] = "Agg"

from config import MODEL_NAME, OUTPUT_DIR
from audio_utils import get_cache_key, get_cached_path, is_cached


def normalize_text_for_tts(text: str) -> str:
    """
    Robust Normalization: Removes unsupported special characters, extra spaces,
    and weird symbols that cause XTTS to hallucinate gibberish at pauses.
    """
    if not text:
        return text

    # Strip and convert all kinds of whitespace/tabs/newlines to a standard space
    text = text.strip()
    text = re.sub(r"[\r\n\t]+", " ", text)
    
    # Clean non-standard/unusual unicode punctuation symbols that confuse XTTS
    # Convert Devanagari Danda '।' to standard period '.' for clean XTTS processing
    text = text.replace("।", ".")
    
    # Remove weird symbols/characters (Keep letters, numbers, basic punctuation, Hindi script)
    # Allows Hindi (u0900-u097F), English (a-zA-A0-9), and basic punctuation (. , ! ? - ')
    text = re.sub(r"[^\w\s.,!?'\u0900-\u097F]", "", text)

    # Replace multiple dots/dashes/symbols like "..." or "---" or ",," with single punctuation
    text = re.sub(r"\.{2,}", ".", text)
    text = re.sub(r"-{2,}", "-", text)
    text = re.sub(r",{2,}", ",", text)

    # Fix space around punctuation (e.g. "अच्छा .तकनीक" -> "अच्छा. तकनीक")
    text = re.sub(r"\s+([.,!?])", r"\1", text)
    text = re.sub(r"([.,!?])([^\s])", r"\1 \2", text)

    # Collapse multiple spaces into one space
    text = re.sub(r"\s+", " ", text).strip()

    # Ensure sentence ends with a proper terminator
    if text and text[-1] not in ".!?":
        text += "."

    return text


class TTSEngine:
    def __init__(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = None
        self.lock = threading.Lock()
        self.builtin_speakers = {}  # {"builtin_claribel_dervla": "Claribel Dervla", ...}

    def load(self):
        if self.model is not None:
            return
        print(f"[TTSEngine] Loading {MODEL_NAME} on {self.device}...")
        self.model = TTS(MODEL_NAME).to(self.device)
        print("[TTSEngine] Model loaded successfully.")

        if self.device == "cpu":
            print("⚠️ [TTSEngine] WARNING: Running on CPU. Generation will be slow. "
                  "Enable GPU runtime in Colab (Runtime > Change runtime type > T4 GPU).")

        # Built-in XTTS speakers mapping
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
        Generates natural, crisp audio without gibberish or hallucination at symbols/spaces.
        """
        if self.model is None:
            raise RuntimeError("XTTS model is not loaded.")
        if not speaker_wav and not speaker_name:
            raise ValueError("Either speaker_wav or speaker_name must be provided.")

        # 1. Clean & normalize text to kill bad symbols/spaces
        text = normalize_text_for_tts(text)
        if not text:
            raise ValueError("Text is empty after normalization.")

        # 2. Check Cache
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
        final_path = str(cached_file)

        # 3. Enhanced Generation Logic
        with self.lock:
            gpt_cond_kwargs = {
                "temperature": 0.45,           # Lower temp stops hallucinating sound at pauses
                "repetition_penalty": 8.0,     # High penalty prevents repeating sounds at spaces
                "speed": 1.05,                 # Natural speech pace
                "top_p": 0.8,
                "top_k": 40,                   # Focused token prediction
                "length_penalty": 1.0,
                "enable_text_splitting": True
            }

            try:
                # Custom inference logic
                wav_outputs = self.model.synthesizer.tts(
                    text=text,
                    language_name=language,
                    speaker_name=speaker_name,
                    speaker_wav=speaker_wav,
                    split_sentences=True,
                    gpt_cond_len=10,            # Clean sound matching
                    **gpt_cond_kwargs
                )

                wav_tensor = torch.tensor(wav_outputs).unsqueeze(0)

                # Silence & Hallucination Trimmer
                non_silent_indices = torch.abs(wav_tensor) > 0.01
                if non_silent_indices.any():
                    last_sound = torch.max(torch.where(non_silent_indices)[2])
                    cutoff = min(last_sound + int(24000 * 0.15), wav_tensor.shape[2])
                    wav_tensor = wav_tensor[:, :, :cutoff]

                torchaudio.save(final_path, wav_tensor, 24000)

            except Exception as e:
                print(f"⚠️ Direct synthesis fallback triggered ({e})...")
                common_args = dict(
                    text=text,
                    language=language,
                    file_path=final_path,
                    split_sentences=True,
                )
                if speaker_name:
                    self.model.tts_to_file(speaker=speaker_name, **common_args)
                else:
                    self.model.tts_to_file(speaker_wav=speaker_wav, **common_args)

        elapsed = round(time.time() - start, 2)
        print(f"[TTSEngine] Speech Generated in {elapsed}s")

        return {
            "path": final_path,
            "cache_key": cache_key,
            "time_seconds": elapsed,
            "is_cached": False,
        }


engine = TTSEngine()