"""
MySQL ke saath saara kaam yahan hota hai.
Do tables: Voice (saved cloned voices) aur GenerationHistory (kya-kya generate hua).
"""
from sqlalchemy import create_engine, Column, String, DateTime, Text, Integer
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
import uuid

from config import DATABASE_URL

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


class Voice(Base):
    """Ek saved/cloned voice ka record — audio sample ka path yahan store hota hai."""
    __tablename__ = "voices"

    id = Column(String(64), primary_key=True, default=lambda: f"voice_{uuid.uuid4().hex[:10]}")
    name = Column(String(255), nullable=False)
    sample_path = Column(String(512), nullable=False)
    language = Column(String(10), default="hi")
    created_at = Column(DateTime, default=datetime.utcnow)


class GenerationHistory(Base):
    """Har generate hui audio ka record — text, voice, output file path."""
    __tablename__ = "generation_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    voice_id = Column(String(64), nullable=False)
    text = Column(Text, nullable=False)
    output_path = Column(String(512), nullable=False)
    cache_key = Column(String(64), index=True)
    generation_time_seconds = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)


def init_db():
    """Tables banata hai agar already nahi hain."""
    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI dependency — har request ke liye ek DB session deta hai."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
