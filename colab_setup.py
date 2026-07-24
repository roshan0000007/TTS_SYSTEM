"""
Colab me is script ko chalao — yeh:
1. Ngrok tunnel start karega (public URL milega)
2. FastAPI server ko background me chalayega
3. Model load hone tak wait karega
4. Health check karke confirm karega sab sahi chal raha hai

Usage (Colab cell me):
    !/content/tts_env/bin/python colab_setup.py
"""
import os
import sys
import subprocess
import time
import requests

from pyngrok import ngrok
from config import NGROK_TOKEN

# Colab ka global matplotlib backend conflict avoid karne ke liye
os.environ["MPLBACKEND"] = "Agg"


def start():
    if NGROK_TOKEN:
        ngrok.set_auth_token(NGROK_TOKEN)

    public_url = ngrok.connect(8006)
    print(f"\n{'='*60}")
    print(f"PUBLIC API URL: {public_url}")
    print(f"{'='*60}\n")

    # IMPORTANT: sirf "uvicorn" likhne se system-wide (global) uvicorn use ho sakta hai,
    # jo isi venv me nahi hai. Isliye hamesha isi venv ke uvicorn ka poora path use karo —
    # yeh path automatically usi Python interpreter se nikalte hain jisse yeh script chal rahi hai.
    venv_bin_dir = os.path.dirname(sys.executable)
    uvicorn_path = os.path.join(venv_bin_dir, "uvicorn")

    print(f"Starting FastAPI server via: {uvicorn_path}")
    print("(model load hone me 1-2 min lagega)")
    process = subprocess.Popen(
        [uvicorn_path, "main:app", "--host", "0.0.0.0", "--port", "8006"],
        env={**os.environ, "MPLBACKEND": "Agg"}
    )

    # Health check — server ready hone tak wait karo
    max_retries = 30
    for i in range(max_retries):
        try:
            resp = requests.get("http://localhost:8006/health", timeout=3)
            if resp.status_code == 200 and resp.json().get("model_loaded"):
                print("\n✅ Server ready! Model loaded successfully.")
                print(f"✅ Test karo: {public_url}/health")
                break
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(5)
        print(f"Waiting for model to load... ({(i+1)*5}s)")
    else:
        print("⚠️ Server abhi bhi load ho raha hai, thoda aur wait karo ya logs check karo.")

    print(f"\nServer PID: {process.pid} (isko stop karne ke liye process.terminate() use karo)")
    return process, public_url


if __name__ == "__main__":
    start()
    # Script ko zinda rakhne ke liye (agar terminal se chalaya hai)
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        print("Shutting down...")