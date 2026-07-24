"""
Lambe text ko chhote, model-friendly chunks me todta hai.
XTTS-v2 ek call me limited characters hi achhe se handle karta hai (~250),
isliye sentence-boundary pe smartly split karte hain.
"""
import re
from config import MAX_CHUNK_LENGTH


def normalize_text(text: str) -> str:
    """Extra spaces, newlines saaf karo."""
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def split_into_chunks(text: str, max_length: int = MAX_CHUNK_LENGTH) -> list[str]:
    """
    Text ko sentences ke boundary pe todta hai (. ! ? ke baad),
    taaki beech-e-sentence se na kate — audio zyada natural sunayi degi.
    """
    text = normalize_text(text)
    sentences = re.split(r"(?<=[.!?।]) ", text)  # । = Hindi sentence-ending danda bhi cover karta hai

    chunks = []
    current = ""

    for sentence in sentences:
        if len(current) + len(sentence) + 1 <= max_length:
            current = f"{current} {sentence}".strip()
        else:
            if current:
                chunks.append(current)
            # Agar ek hi sentence max_length se lamba hai, use bhi force-split karo
            if len(sentence) > max_length:
                for i in range(0, len(sentence), max_length):
                    chunks.append(sentence[i:i + max_length])
                current = ""
            else:
                current = sentence

    if current:
        chunks.append(current)

    return chunks