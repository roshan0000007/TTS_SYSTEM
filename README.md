# TTS System (ElevenLabs-style) — XTTS-v2 Base Model

## Architecture — Kya Kahan Chalega

| Component | Platform | Kyun |
|---|---|---|
| Code editing | **VS Code (local)** | Sabse achha editor experience |
| Version control | **GitHub** | VS Code ↔ Colab ke beech code sync karne ke liye |
| Model + GPU inference | **Google Colab (T4 GPU)** | XTTS-v2 ko GPU chahiye, laptop pe free nahi milta |
| MySQL Database | **Local machine ya cloud (PlanetScale/Railway free tier)** | Voice metadata, generation history store karne ke liye |
| Audio files storage | **Filesystem** (Colab disk ya Google Drive mounted) | Actual .wav files yahin save hongi |
| API server | **Colab pe FastAPI**, ngrok se public URL | GPU wahi hai jahan model load hai |
| Client (jo API call karega) | **Kahin bhi** — Postman, tumhara app, VS Code terminal | Sirf HTTP requests bhejta hai |

## Poora Flow

```
[VS Code — code likho]
        ↓ git push
[GitHub — code storage]
        ↓ git clone/pull
[Google Colab — GPU]
   ├── venv setup
   ├── XTTS-v2 model load (GPU)
   ├── MySQL connect (voice metadata)
   ├── FastAPI server start
   └── ngrok → public URL
        ↓
[Client — kahi se bhi call karo]
   POST /v1/voices/add          → voice clone karo, save karo
   POST /v1/text-to-speech/{id} → audio generate karo
   GET  /v1/voices              → saari saved voices dekho
   GET  /v1/history             → generation history dekho
```

## Why NOT Vector DB

Vector DB (Pinecone, Chroma, etc.) similarity search ke liye hota hai — jaise "is text jaisa milta-julta text dhoondo" ya "is jaisi awaaz wali voice dhoondo" (embeddings compare karke). 

Hamare TTS system me:
- Voice ek unique ID se lookup hoti hai (exact match) — yeh normal database ka kaam hai
- History bhi structured records hain (text, voice_id, timestamp)

**MySQL iske liye perfect hai** — vector DB add karna is stage pe unnecessary complexity hoga. Agar future me "similar sounding voices suggest karo" jaisa feature chahiye, tab vector DB add karna sahi rahega.

## File Structure

```
tts-elevenlabs-clone/
├── requirements.txt       # Saare Python packages
├── config.py               # Settings (paths, DB config)
├── database.py             # MySQL models (Voice, GenerationHistory)
├── text_processor.py       # Text chunking/normalization
├── audio_utils.py          # Audio combine, caching logic
├── tts_engine.py            # XTTS-v2 model wrapper
├── main.py                  # FastAPI app — saare endpoints
├── .env.example              # Environment variables template
├── colab_setup.py            # Colab me ek hi baar chalane wala setup script
└── README.md                 # Yeh file
```

## Setup — Step by Step

### 1. Local (VS Code) — Code Likhna/Edit Karna
```bash
git clone https://github.com/YOUR_USERNAME/tts-elevenlabs-clone.git
cd tts-elevenlabs-clone
code .
```
Jo bhi changes karo, `git push` karke Colab me `git pull` se le aana.

### 2. MySQL Setup (Ek Baar)

**Option A — Local MySQL** (agar apne machine pe test karna hai):
```bash
mysql -u root -p
CREATE DATABASE tts_system;
```

**Option B — Free Cloud MySQL (Recommended, Colab se accessible)**:
- [Railway.app](https://railway.app) → New Project → MySQL → free tier
- Connection details milenge (host, user, password, port) — `.env` file me daalo

### 3. Google Colab — GPU + Server

Naya Colab notebook, **Runtime → Change runtime type → T4 GPU**, phir:

```python
!git clone https://github.com/YOUR_USERNAME/tts-elevenlabs-clone.git
%cd tts-elevenlabs-clone
```

```python
!python3.11 -m venv /content/tts_env || (apt-get update -qq && apt-get install -y python3.11 python3.11-venv python3.11-dev && python3.11 -m venv /content/tts_env)
!/content/tts_env/bin/pip install -q -r requirements.txt
```

`.env` file banao (apna MySQL credentials daal ke):
```python
%%writefile .env
DB_HOST=your-mysql-host
DB_PORT=3306
DB_USER=your-user
DB_PASSWORD=your-password
DB_NAME=tts_system
NGROK_TOKEN=your-ngrok-token
```

Server chalao:
```python
!/content/tts_env/bin/python colab_setup.py
```

Yeh script model load karega, DB tables banayega, FastAPI server start karega, aur ngrok URL print karega.

### 4. Test Karo (Kahin Se Bhi)

```bash
# Voice add karo
curl -X POST "https://xxxx.ngrok-free.app/v1/voices/add" \
  -F "name=My Voice" \
  -F "voice_sample=@my_sample.wav"

# Text to speech
curl -X POST "https://xxxx.ngrok-free.app/v1/text-to-speech/voice_1" \
  -H "Content-Type: application/json" \
  -d '{"text":"Namaste duniya"}' \
  --output result.wav
```
