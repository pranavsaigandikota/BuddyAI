import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
import sys
import io
import traceback
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
import uvicorn
import numpy as np
import soundfile as sf
import torch

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR       = Path(__file__).parent.resolve()
VOICE_DIR      = BASE_DIR / "buddy_voice"
REF_AUDIO_PATH = VOICE_DIR / "reference.wav"

VOICE_DIR.mkdir(exist_ok=True)

# ── Validate reference audio ───────────────────────────────────────────────────
if not REF_AUDIO_PATH.exists():
    print(f"WARNING: No voice reference found at {REF_AUDIO_PATH}")
    print("Chatterbox will use its default voice until you add a real clip.")
    print(f"To clone a voice: put a clean 5-15s WAV of Rick speaking at: {REF_AUDIO_PATH}")
    REF_AUDIO_PATH = None
else:
    _data, _sr = sf.read(str(REF_AUDIO_PATH))
    _rms = np.sqrt(np.mean(_data.astype(np.float32) ** 2))
    if _rms < 1e-4:
        print("WARNING: reference.wav is silent — ignoring it, using default voice.")
        REF_AUDIO_PATH = None
    else:
        _dur = len(_data) / _sr
        print(f"Voice reference loaded: {REF_AUDIO_PATH.name} ({_dur:.1f}s, RMS={_rms:.4f})")

# ── Load Chatterbox ────────────────────────────────────────────────────────────
model = None
try:
    # IMPORT THE TURBO MODULE INSTEAD OF THE ORIGINAL
    from chatterbox.tts_turbo import ChatterboxTurboTTS
    
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Loading Chatterbox Turbo TTS on {device.upper()}...")
    
    # LOAD THE TURBO CLASS (No repo string needed, it knows where to look!)
    model = ChatterboxTurboTTS.from_pretrained(device=device) 
    
    print("Chatterbox Turbo TTS loaded successfully.")
except Exception as e:
    print(f"ERROR loading Chatterbox: {e}", file=sys.stderr)
    traceback.print_exc()
    print("TTS will be unavailable until this is fixed.", file=sys.stderr)

# ChatterboxTurboTTS does not support get_conditioning_latents — use audio_prompt_path directly

# ── FastAPI app ────────────────────────────────────────────────────────────────
app = FastAPI(title="Buddy TTS Server (Chatterbox Turbo)")

class SpeechRequest(BaseModel):
    model: str = "chatterbox"
    input: str
    voice: str = "buddy"
    response_format: str = "wav"
    speed: float = 1.0
    # 0.0-1.0: higher = more expressive/emotive (Rick should be ~0.6-0.8)
    exaggeration: float = 0.7
    # 0.0-1.0: higher = more faithful to prompt, lower = more natural flow
    cfg_weight: float = 0.5


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "model_loaded": model is not None,
        "voice_cloning": REF_AUDIO_PATH is not None,
        "device": "cuda" if torch.cuda.is_available() else "cpu",
    }


@app.post("/v1/audio/speech")
async def create_speech(request: SpeechRequest):
    if not model:
        raise HTTPException(status_code=503, detail="Chatterbox model is not loaded.")

    print(f"[TTS] Synthesising: {request.input[:80]}...")

    try:
        kwargs = {
            "text": request.input,
            "exaggeration": request.exaggeration,
            "cfg_weight": request.cfg_weight,
        }

        if REF_AUDIO_PATH is not None:
            kwargs["audio_prompt_path"] = str(REF_AUDIO_PATH)
        else:
            print("[TTS] Using default Chatterbox voice (no reference audio)")

        wav = model.generate(**kwargs)

        # Chatterbox returns a tensor — convert to numpy
        wav_np = wav.squeeze().cpu().numpy()

        buf = io.BytesIO()
        sf.write(buf, wav_np, model.sr, format="WAV")
        buf.seek(0)

        return Response(content=buf.read(), media_type="audio/wav")

    except Exception as e:
        tb = traceback.format_exc()
        print(f"[TTS Error] {e}\n{tb}")
        raise HTTPException(status_code=500, detail=f"{e}\n\n{tb}")


if __name__ == "__main__":
    print("Starting Buddy TTS Server (Chatterbox Turbo) on http://0.0.0.0:8000 ...")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")