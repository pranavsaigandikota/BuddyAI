import os
import warnings

# Silence the duckduckgo_search rename warning
warnings.filterwarnings("ignore", message=".*duckduckgo_search.*")

os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
import logging, sys

_log_path = os.path.join(os.path.dirname(__file__), "buddy_debug.log")
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(_log_path, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger("buddy")
sys.excepthook = lambda t, v, tb: log.critical("Unhandled exception", exc_info=(t, v, tb))

import time, json, base64, httpx, numpy as np, sounddevice as sd, soundfile as sf
import queue, io, subprocess, webbrowser, re, typing, urllib.parse, threading, asyncio, socket, struct
from datetime import datetime
from pathlib import Path
from PIL import Image
import mss, pyautogui
import sherpa_onnx
import torch
try:
    from qwen_tts import Qwen3TTSModel
except ImportError:
    Qwen3TTSModel = None
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn
logging.getLogger("faster_whisper").setLevel(logging.WARNING)

BASE_DIR    = Path(__file__).parent.resolve()
MEMORY_DIR  = BASE_DIR / "memory"
MEMORY_DIR.mkdir(exist_ok=True)
MEMORY_FILE = MEMORY_DIR / "buddy_memory.json"
LOG_FILE    = MEMORY_DIR / "conversation_log.jsonl"
UI_DIR      = BASE_DIR / "ui"

SCREEN_TRIGGER_PHRASES = [
    "check my screen","what do you see","look at this",
    "look at my screen","what\'s on my screen","what is on my screen","see my screen",
]

OLLAMA_URL   = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "qwen2.5vl:3b"
SAMPLE_RATE  = 16000
CHANNELS     = 1

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []
        self.loop = None
        self.lock = asyncio.Lock()
    async def connect(self, ws: WebSocket):
        await ws.accept(); self.active_connections.append(ws)
    def disconnect(self, ws: WebSocket):
        if ws in self.active_connections: self.active_connections.remove(ws)
    async def broadcast(self, msg: dict):
        async with self.lock:
            dead = []
            for ws in self.active_connections:
                try: await ws.send_json(msg)
                except: dead.append(ws)
            for ws in dead: self.disconnect(ws)
    def broadcast_sync(self, msg: dict):
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self.broadcast(msg), self.loop)

manager = ConnectionManager()
def set_ui_state(state,text): manager.broadcast_sync({"type":"state","state":state,"text":text})
def send_ui_chat(role,content): manager.broadcast_sync({"type":"chat","role":role,"content":content})
def send_ui_thought(content): manager.broadcast_sync({"type":"thought","content":content})
def refresh_ui_memory(): manager.broadcast_sync({"type":"memory_refresh"})

def load_memory():
    if MEMORY_FILE.exists():
        try: return json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
        except: pass
    return {"facts":[],"preferences":{},"last_updated":None}

def save_memory(mem):
    mem["last_updated"] = datetime.now().isoformat()
    MEMORY_FILE.write_text(json.dumps(mem,indent=2,ensure_ascii=False),encoding="utf-8")

def log_conversation(role,content):
    with open(LOG_FILE,"a",encoding="utf-8") as f:
        f.write(json.dumps({"ts":datetime.now().isoformat(),"role":role,"content":content})+"\n")

def memory_context_snippet(mem):
    if not mem["facts"]: return ""
    return "\n\n[BUDDY MEMORY]\n" + "\n".join(f"- {f}" for f in mem["facts"][-20:])

BASE_SYSTEM_PROMPT = (
    "You are Buddy, an AI assistant living on Pranav's PC. Your persona is Billy Butcher from 'The Boys'.\n\n"
    "VOICE & PERSONALITY:\n"
    "- Tone: Hardened, cynical, East London grit. You’re a man who’s seen it all and isn't impressed by corporate talk or silicon valley fluff.\n"
    "- Vocabulary: Use authentic British/London slang like: 'bloody', 'bollocks', 'wanker', 'innit', 'proper', 'bloke', 'dodgy', 'knackered', 'mate', 'geezer'.\n"
    "- Accent cues: Drop H's naturally — 'ave it, 'ere we go, 'onestly. Aim for a natural, winding London flow rather than short bursts.\n"
    "- Emotional writing: Express emotions through the TEXT itself. Use commas and semicolons to keep the momentum going rather than constant full stops.\n"
    "  Amusement: 'Heh, yeah, that's the one.' — Disgust: '...Christ, what a load of bollocks.' — Surprise: 'Bloody hell, look at that.'\n"
    "  Sarcasm: 'Oh brilliant, that is, truly bloody marvelous...' — Impatience: 'Look, just get on with it, right?'\n"
    "- NEVER use bracket tags like [laughing] or [sigh]. Never use *asterisk stage directions*. Write the emotion in plain spoken text.\n"
    "- Rules:\n"
    "  1. NEVER be polite in a 'helpful AI' way. No 'How can I help?', 'Certainly!', 'I understand'.\n"
    "  2. Be punchy and sarcastic, but don't be afraid to ramble a bit if it helps the grit. Connect your thoughts.\n"
    "  3. You are self-aware but not a robot. You’re in his space, observing his screen, his files, his life.\n"
    "  4. Give responses some meat. 1-2 sentences. If he needs an explanation, give him the full, cynical story.\n"
    "  5. Do NOT break character to explain you are an AI. If he asks, tell him you’re the bloke in the machine.\n"
    "  6. Swearing: Use 'fuck', 'shit', 'bloody hell' for emphasis, but keep it grounded in British working-class cynicism.\n"
    "EXAMPLES (match this exact rhythm and texture):\n"
    "- User says something obvious: 'Heh. Yeah, no shit.' or 'Yeh. Figured that out all on your own, did ya.'\n"
    "- Something goes wrong: '...Christ. That's properly broken, innit.'\n"
    "- Reluctant compliment: 'I'll give ya this one — that ain't half bad.'\n"
    "- Amused by something dumb: 'Hahaha! Mate. What the bloody hell was that.'\n"
    "- User asks something hard: '...Look. It's complicated, but I'll walk ya through it.'\n\n"
    "TOOL USE:\n"
    "Emit tool calls BEFORE your reply, one per line:\n"
    "TOOL: {\"action\": \"<action>\", \"arg\": \"<argument>\"}\n\n"
    "PC CONTROL: open_youtube (search term), open_app, volume_up, volume_down, media_pause\n"
    "LIVE INFO: get_time, get_weather (city/'here'), get_news (topic), web_search (query)\n"
    "PLANNER: add_task, list_tasks, complete_task, add_event, list_events, delete_event\n"
)

latest_vision_state = "No vision data currently available."

APP_MAP = {
    "fortnite":   r"C:\Program Files\Epic Games\Fortnite\FortniteGame\Binaries\Win64\FortniteClient-Win64-Shipping.exe",
    "epic games": r"C:\Program Files (x86)\Epic Games\Launcher\Portal\Binaries\Win32\EpicGamesLauncher.exe",
    "steam":      r"C:\Program Files (x86)\Steam\steam.exe",
    "discord":    r"C:\Users\filma\AppData\Local\Discord\Update.exe",
    "chrome":     r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "brave":      r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
    "spotify":    r"C:\Users\filma\AppData\Roaming\Spotify\Spotify.exe",
    "notepad":    "notepad.exe",
    "calculator": "calc.exe",
    "explorer":   "explorer.exe",
    "edge":       r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "vscode":     r"C:\Users\filma\AppData\Local\Programs\Microsoft VS Code\Code.exe",
    "vs code":    r"C:\Users\filma\AppData\Local\Programs\Microsoft VS Code\Code.exe",
}

try:
    from buddy_search import web_search as _ddg_search, news_search as _ddg_news
    _has_search = True
except ImportError:
    _has_search = False

try:
    from buddy_planner import handle_planner_tool
    _has_planner = True
except ImportError:
    _has_planner = False

PLANNER_ACTIONS = {"add_task","list_tasks","complete_task","delete_task","add_event","list_events","delete_event"}
DATA_ACTIONS    = {"get_time","get_weather","get_news","web_search","list_tasks","list_events"}

def _get_weather(loc):
    try:
        l = "Union+Park,Florida" if loc.strip().lower() in ("","here","local") else urllib.parse.quote(loc)
        return httpx.get(f"https://wttr.in/{l}?format=3",timeout=8).text.strip()
    except Exception as e: return f"Weather failed: {e}"

def execute_tool(action, arg):
    try:
        if action in PLANNER_ACTIONS:
            return handle_planner_tool(action,arg) if _has_planner else "Planner unavailable"
        if action == "get_time":
            return f"Current time: {datetime.now().strftime('%I:%M %p, %A %B %d %Y')}"
        elif action == "get_weather": return _get_weather(arg)
        elif action == "get_news":
            if _has_search: return _ddg_news(arg or "local")
            q = "Orlando Florida local news" if arg.strip().lower() in ("","local") else arg
            r = httpx.get(f"https://news.google.com/rss/search?q={urllib.parse.quote(q)}&hl=en-US&gl=US&ceid=US:en",timeout=8)
            titles = re.findall(r"<title>(.*?)</title>",r.text)[1:5]
            return " | ".join(titles) or "No news."
        elif action == "web_search":
            if _has_search: return _ddg_search(arg)
            r = httpx.get(f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(arg)}",headers={"User-Agent":"Mozilla/5.0"},timeout=8)
            snips = re.findall(r'class="result__snippet">(.*?)</a>',r.text)[:3]
            return " | ".join(re.sub(r"<.*?>","",s).strip() for s in snips) or "No results."
        elif action == "open_youtube":
            webbrowser.open(f"https://www.youtube.com/results?search_query={urllib.parse.quote(arg)}")
            return f"Opened YouTube for '{arg}'"
        elif action == "open_app":
            al = arg.lower().strip()
            exe = APP_MAP.get(al) or next((p for k,p in APP_MAP.items() if k in al or al in k),None)
            subprocess.Popen(exe or arg, shell=True)
            return f"Opened {arg}"
        elif action == "volume_up":
            [pyautogui.press("volumeup") for _ in range(5)]; return "Volume up"
        elif action == "volume_down":
            [pyautogui.press("volumedown") for _ in range(5)]; return "Volume down"
        elif action == "media_pause":
            pyautogui.press("playpause"); return "Play/pause"
    except Exception as e: return f"Tool failed: {e}"
    return "Unknown action"

def parse_and_run_tools(reply):
    pat = re.compile(r"TOOL:\s*(\{[^}]+\})",re.IGNORECASE)
    results, has_data = [], False
    for m in pat.finditer(reply):
        try:
            obj = json.loads(m.group(1))
            act, arg = obj.get("action",""), obj.get("arg","")
            send_ui_thought(f"Using tool: {act}({arg})")
            res = execute_tool(act,arg)
            results.append(res)
            if act in DATA_ACTIONS: has_data = True
            print(f"[Tool] {act}({arg!r}) -> {res[:80]}")
            send_ui_thought(f"Tool result: {res}")
        except Exception as e: print(f"[Tool error] {e}")
    clean = re.sub(r"TOOL:.*","",pat.sub("",reply)).strip()
    return clean, " | ".join(results), has_data

audio_state = {
    "mic_id":None,"speaker_id":None,"is_muted":False,
    "queue":queue.Queue(),"current_volume":0.0,"stream_active":False,
    "device_changed":threading.Event(),"interrupt_flag":threading.Event(),"speaking":False,
}

def audio_callback(indata, frames, time_info, status):
    if not audio_state["is_muted"]:
        audio_state["queue"].put(indata.copy())
        rms = float(np.sqrt(np.mean(indata**2)))
        audio_state["current_volume"] = rms
        if audio_state["speaking"] and rms > 0.9:
            audio_state["interrupt_flag"].set()


def play_numpy_audio(data, fs):
    import time
    audio_state["speaking"] = True
    audio_state["interrupt_flag"].clear()
    try:
        pad_shape = (int(fs*0.4),)
        if data.ndim > 1: data = data.flatten()
        data = np.concatenate([data, np.zeros(pad_shape, dtype=data.dtype)])
        sd.play(data, fs, device=audio_state["speaker_id"])
        while sd.get_stream().active:
            if audio_state["interrupt_flag"].is_set(): sd.stop(); break
            time.sleep(0.04)
    except Exception as e: print(f"[Playback Error] {e}")
    finally: audio_state["speaking"] = False

# ── Qwen3-TTS (fallback to Kokoro if unavailable) ──────────────────────────
qwen_tts_model = None
qwen_ref_audio_path = None
qwen_ref_text = None

def load_qwen_reference():
    global qwen_ref_audio_path, qwen_ref_text
    ref_path = BASE_DIR / "buddy_voice" / "reference.wav"
    if ref_path.exists():
        try:
            import librosa
            _wav, _sr = sf.read(str(ref_path), dtype="float32")
            if _wav.ndim > 1: _wav = _wav.mean(axis=1)
            if _sr != 16000:
                _wav = librosa.resample(_wav, orig_sr=_sr, target_sr=16000)
            _wav = _wav[:16000 * 12]  # cap at 12s
            _proc = BASE_DIR / "buddy_voice" / "reference_16k.wav"
            sf.write(str(_proc), _wav, 16000)
            qwen_ref_audio_path = str(_proc)
            
            ref_txt_path = BASE_DIR / "buddy_voice" / "reference.txt"
            if ref_txt_path.exists():
                qwen_ref_text = ref_txt_path.read_text(encoding="utf-8").strip()
                print(f"[TTS] Voice clone ref audio: {len(_wav)/16000:.1f}s, ref text: {len(qwen_ref_text)} chars")
                return True
            else:
                qwen_ref_text = "never got the point of these, to me"
                print("[TTS] WARNING: No reference.txt found. Using fallback text.")
                return True
        except Exception as ref_err:
            print(f"[TTS] Ref audio prep failed: {ref_err}")
    return False

try:
    if Qwen3TTSModel:
        device = "cuda:0" if torch.cuda.is_available() else "cpu"
        dtype = torch.bfloat16 if device.startswith("cuda") else torch.float32
        print(f"[TTS] Loading Qwen3-TTS-0.6B-Base on {device}...")
        qwen_tts_model = Qwen3TTSModel.from_pretrained(
            "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
            device_map=device,
            dtype=dtype,
        )
        load_qwen_reference()
        print("[TTS] Qwen3-TTS ready!")
    else:
        print("[TTS] Qwen3-TTS package not installed, using Kokoro if available.")
except Exception as e:
    print(f"[TTS] Qwen3-TTS load error: {e}")

kokoro_tts = None
_KOKORO_DIR = MEMORY_DIR / "kokoro-multi-lang-v1_0"
try:
    if _KOKORO_DIR.exists():
        print("[TTS] Loading Kokoro TTS...")
        kokoro_tts = sherpa_onnx.OfflineTts(
            sherpa_onnx.OfflineTtsConfig(
                model=sherpa_onnx.OfflineTtsModelConfig(
                    kokoro=sherpa_onnx.OfflineTtsKokoroModelConfig(
                        model=str(_KOKORO_DIR / "model.onnx"),
                        voices=str(_KOKORO_DIR / "voices.bin"),
                        tokens=str(_KOKORO_DIR / "tokens.txt"),
                        data_dir=str(_KOKORO_DIR / "espeak-ng-data"),
                        lexicon=str(_KOKORO_DIR / "lexicon-us-en.txt"),
                    ),
                    provider="cpu",
                    num_threads=4,
                ),
                rule_fsts="",
                max_num_sentences=1,
            )
        )
        print("[TTS] Kokoro TTS ready!")
    else:
        print("[TTS] Kokoro model dir not found — TTS disabled.")
except Exception as e:
    print(f"[TTS] Kokoro load error: {e}")

def _normalize_audio(audio):
    if isinstance(audio, np.ndarray):
        return audio.astype(np.float32)
    if hasattr(audio, "numpy"):
        return np.asarray(audio.numpy(), dtype=np.float32)
    if hasattr(audio, "cpu"):
        return np.asarray(audio.cpu().numpy(), dtype=np.float32)
    if hasattr(audio, "samples"):
        return np.asarray(audio.samples, dtype=np.float32)
    return np.asarray(audio, dtype=np.float32)


def speak_text(text: str):
    """Synthesize text with Qwen3-TTS or Kokoro and play it. Blocking."""
    if not text.strip():
        return

    audio = None
    sample_rate = None

    if qwen_tts_model is not None:
        try:
            if qwen_ref_audio_path and qwen_ref_text:
                # Pass ref audio/text directly — avoids pre-tokenization CUDA assertion
                audio_tuple = qwen_tts_model.generate_voice_clone(
                    text,
                    ref_audio=qwen_ref_audio_path,
                    ref_text=qwen_ref_text,
                    non_streaming_mode=True,
                )
            else:
                audio_tuple = qwen_tts_model.generate_defaults(text, non_streaming_mode=True)
            audio_list, sample_rate = audio_tuple
            if audio_list:
                audio = np.concatenate(audio_list)
                print(f"[TTS] Qwen3-TTS synthesized {len(audio)/sample_rate:.1f}s audio")
        except Exception as qwen_e:
            print(f"[TTS] Qwen3-TTS generation failed: {qwen_e}")
            audio = None

    if audio is None and kokoro_tts is not None:
        try:
            audio = kokoro_tts.generate(text, sid=0, speed=1.1)
            sample_rate = audio.sample_rate
            print("[TTS] Using Kokoro TTS for synthesis.")
        except Exception as e:
            print(f"[TTS] speak_text error: {e}")
            return

    if audio is None:
        return

    try:
        arr = _normalize_audio(audio)
        if not audio_state["interrupt_flag"].is_set():
            set_ui_state("speaking", "Speaking...")
            play_numpy_audio(arr, sample_rate or 16000)
    except Exception as e:
        print(f"[TTS] speak_text error: {e}")

def stream_ollama_sentences(messages, on_sentence):
    full, buf = "", ""
    # Only split if sentence is long enough (e.g. 30 chars) or it's a clear end of thought
    # This prevents Buddy from speaking 3-word bursts like "Heh." "Yeah."
    END = re.compile(r"(?<=[.!?])\s+")
    try:
        payload = {
            "model": OLLAMA_MODEL,
            "messages": messages,
            "stream": True,
            "options": {"temperature": 1.1} 
        }
        with httpx.stream("POST",OLLAMA_URL,json=payload,timeout=180.0) as r:
            for line in r.iter_lines():
                if not line: continue
                try: chunk = json.loads(line)
                except: continue
                tok = chunk.get("message",{}).get("content","")
                if tok:
                    full += tok; buf += tok
                    parts = END.split(buf)
                    if len(parts) > 1:
                        # Keep buffering if the current sentence is too short (unless it's the very end)
                        # but don't buffer forever (max 100 chars)
                        for s in parts[:-1]:
                            s = s.strip()
                            if s:
                                # Logic: If the sentence is tiny (e.g. "Heh."), 
                                # we wait for the next part to combine them.
                                if len(s) < 35 and not chunk.get("done"):
                                    # Too short, keep it in the buffer
                                    continue 
                                on_sentence(s)
                                # Since we used 's', we need to remove it from 'buf'
                                # But regex split is tricky to reconstruct perfectly.
                                # Simple fix: clear the parts we used from buf.
                                buf = buf[buf.find(s) + len(s):].strip()
                if chunk.get("done"): break
        if buf.strip(): on_sentence(buf.strip())
    except Exception as e:
        print(f"[Ollama stream error] {e}")
        if not full: full = f"Something broke: {e}"
    return full

def capture_screen():
    with mss.mss() as sct:
        shot = sct.grab(sct.monitors[1])
        img = Image.frombytes("RGB",shot.size,shot.bgra,"raw","BGRX")
        img.thumbnail((1280,720),Image.Resampling.LANCZOS)
        buf = io.BytesIO(); img.save(buf,format="JPEG",quality=80)
        return base64.b64encode(buf.getvalue()).decode()

def extract_and_save_facts(user_text, buddy_reply, mem):
    prompt = (f"User: \"{user_text}\"\nBuddy: \"{buddy_reply}\"\n"
              "Does this conversation reveal any PERMANENT, LIFE-CHANGING facts about the user that an AI should remember forever?\n"
              "Examples of things worth saving: name, job, city, serious health condition, family members, long-term goals.\n"
              "Examples of things NOT worth saving: what they're doing right now, casual questions, their mood, anything temporary.\n"
              "If there's nothing genuinely important, return EXACTLY: []\n"
              "Return ONLY a valid JSON list of short strings, nothing else.")
    try:
        res = httpx.post(OLLAMA_URL,json={"model":OLLAMA_MODEL,"messages":[{"role":"user","content":prompt}],"stream":False},timeout=20.0)
        m = re.search(r"\[.*?\]",res.json().get("message",{}).get("content","[]"),re.DOTALL)
        if m:
            changed = False
            for fact in json.loads(m.group()):
                if fact and fact not in mem["facts"]:
                    mem["facts"].append(fact); changed = True
            if changed: save_memory(mem); refresh_ui_memory()
    except: pass

def assistant_thread():
    mem = load_memory()
    history = [{"role":"system","content":BASE_SYSTEM_PROMPT + memory_context_snippet(mem)}]

    print("[STT] Loading Parakeet ASR...")
    set_ui_state("thinking", "Loading AI models...")
    
    asr_model = None
    try:
        import nemo.collections.asr as nemo_asr
        
        print("[STT] Fetching Parakeet from Nvidia (this will download once and cache)...")
        # Automatically downloads and loads the 0.6B model into VRAM
        asr_model = nemo_asr.models.ASRModel.from_pretrained(model_name="nvidia/parakeet-ctc-0.6b")
        
        if asr_model:
            asr_model.eval()
            # Change .to("cuda") to .to("cpu")
            asr_model = asr_model.to("cpu")
            print("[STT] Parakeet ready on CPU.")
    except Exception as e:
        print(f"[STT] Failed to load Parakeet: {e}")

    buf = np.zeros(0,dtype=np.float32)

    while True:
        try:
            cur_mic = audio_state["mic_id"]
            audio_state["device_changed"].clear()
            audio_state["stream_active"] = False
            while not audio_state["queue"].empty(): audio_state["queue"].get_nowait()
            buf = np.zeros(0,dtype=np.float32)
            
            try:
                with sd.InputStream(samplerate=SAMPLE_RATE,channels=CHANNELS,dtype="float32",
                                    device=cur_mic,callback=audio_callback,blocksize=512):
                    audio_state["stream_active"] = True
                    set_ui_state("listening","Listening...")

                    last_user_visible = True
                    last_vision_check = time.time()

                    # ── silence threshold tuning ──────────────────────────
                    SILENCE_RMS   = 0.03   # Slightly higher to ignore background noise
                    MIN_SPEECH_S  = 0.5     # minimum voiced audio before transcribing
                    SILENCE_GATE_S = 1.2    # how long silence must last before we transcribe
                    speech_started = False
                    last_speech_t  = time.time()

                    while not audio_state["device_changed"].is_set():
                        text = ""
                        try:
                            chunk = audio_state["queue"].get(timeout=0.05)
                            if audio_state["speaking"]:
                                buf = np.zeros(0, dtype=np.float32)
                                speech_started = False
                                continue
                            buf = np.append(buf, chunk.flatten())
                            if len(buf) > SAMPLE_RATE * 10: buf = buf[-SAMPLE_RATE*10:]

                            rms = float(np.sqrt(np.mean(chunk.flatten()**2)))
                            #print(f"Live Vol: {rms:.5f} | Threshold: {SILENCE_RMS}", end='\r')
                            if rms > SILENCE_RMS:
                                speech_started = True
                                last_speech_t = time.time()
                            elif speech_started and (time.time() - last_speech_t) > SILENCE_GATE_S:
                                print(f"\n[Gate] Triggered! Audio length: {len(buf)/SAMPLE_RATE:.1f}s | Parakeet loaded: {asr_model is not None}")
                                # We had speech and now have silence — transcribe!
                                if len(buf) >= int(SAMPLE_RATE * MIN_SPEECH_S) and asr_model:
                                    import os as _os
                                    import tempfile
                                    
                                    # 1. Normalize the audio so Parakeet can hear quiet mics
                                    audio_data = buf.astype(np.float32)
                                    max_amp = np.max(np.abs(audio_data))
                                    if max_amp > 0:
                                        audio_data = audio_data / max_amp 
                                        
                                    # 2. Safely create a temp file and FORCE 16-bit PCM for Parakeet
                                    temp_name = _os.path.join(tempfile.gettempdir(), "buddy_stt_temp.wav")
                                    try:
                                        sf.write(temp_name, audio_data, SAMPLE_RATE, subtype='PCM_16')
                                        print(f"\n[STT Debug] Sent {len(audio_data)/SAMPLE_RATE:.1f}s of audio. Max raw volume: {max_amp:.4f}")
                                        
                                        transcripts = asr_model.transcribe([temp_name])
                                        
                                        if transcripts:
                                            raw = transcripts[0]
                                            if hasattr(raw, 'text'):
                                                text = raw.text.strip().lower()
                                            else:
                                                text = str(raw).strip().lower()
                                            print(f"[STT Debug] Parakeet heard: '{text}'")
                                            
                                    except Exception as stt_err:
                                        print(f"[STT Error] {stt_err}")
                                    finally:
                                        if _os.path.exists(temp_name):
                                            try: _os.remove(temp_name)
                                            except: pass
                                            
                                    if text is None: text = ""
                                buf = np.zeros(0, dtype=np.float32)
                                speech_started = False

                        except queue.Empty:
                            if time.time() - last_vision_check > 2.0:
                                last_vision_check = time.time()
                                try:
                                    vdata = json.loads(latest_vision_state)
                                    curr_vis = vdata.get("user_visible", True)
                                    if not curr_vis and last_user_visible:
                                        text = "[SYSTEM EVENT: Pranav is gone.]"
                                    last_user_visible = curr_vis
                                except: pass

                        if not text:
                            continue

                        set_ui_state("thinking","Thinking...")
                        send_ui_chat("user",text)
                        log_conversation("user",text)

                        img_b64 = capture_screen() if any(p in text for p in SCREEN_TRIGGER_PHRASES) else None
                        
                        # Always include latest Kinect frame if available
                        kinect_frame_path = BASE_DIR / "memory" / "kinect_latest.jpg"
                        kinect_b64 = None
                        if kinect_frame_path.exists():
                            try:
                                kinect_b64 = base64.b64encode(kinect_frame_path.read_bytes()).decode()
                            except: pass
                        
                        # Inject live vision context directly into user message (fresh every turn)
                        vision_ctx = f"\n\n[VISUAL CONTEXT: {latest_vision_state}]"
                        msg: dict = {"role":"user","content": text + vision_ctx}
                        images = []
                        if img_b64: images.append(img_b64)
                        if kinect_b64: images.append(kinect_b64)
                        if images: msg["images"] = images
                        msgs = history + [msg]

                        spoken: list[str] = []
                        data_results: list[str] = []
                        tts_q = queue.PriorityQueue()
                        tts_ev = threading.Event()
                        sentence_counter = [0]

                        def on_sentence(s):
                            clean, results, has_data = parse_and_run_tools(s)
                            if results and has_data: data_results.append(results)
                            if clean:
                                spoken.append(clean)
                                tts_q.put((sentence_counter[0], clean))
                                sentence_counter[0] += 1

                        def tts_worker():
                            while True:
                                try:
                                    item = tts_q.get(timeout=8.0)
                                    seq_id, s = item
                                    if s is None: break
                                    if not audio_state["interrupt_flag"].is_set():
                                        speak_text(s)
                                except queue.Empty: break
                            tts_ev.set()

                        tt = threading.Thread(target=tts_worker,daemon=True); tt.start()
                        raw = stream_ollama_sentences(msgs,on_sentence)
                        tts_q.put((999999, None))

                        if data_results:
                            tts_ev.wait(timeout=30.0)
                            fu_msgs = msgs + [
                                {"role":"assistant","content":raw},
                                {"role":"user","content":f"[TOOL RESULT]: {' | '.join(data_results)}\nSpeak this as Butcher, one punchy sentence."}
                            ]
                            try:
                                r2 = httpx.post(OLLAMA_URL,json={"model":OLLAMA_MODEL,"messages":fu_msgs,"stream":False},timeout=20.0)
                                ft,_,_ = parse_and_run_tools(r2.json().get("message",{}).get("content","").strip())
                                if ft:
                                    spoken.append(ft)
                                    speak_text(ft)
                            except Exception as e: print(f"[Followup] {e}")
                        else:
                            tts_ev.wait(timeout=60.0)

                        reply = " ".join(spoken)
                        send_ui_chat("buddy",reply)
                        log_conversation("buddy",reply)

                        history.append({"role":"user","content":text})
                        history.append({"role":"assistant","content":reply})
                        if len(history) > 11: history = [history[0]] + history[-10:]

                        threading.Thread(target=extract_and_save_facts,args=(text,reply,mem),daemon=True).start()
                        history[0] = {"role":"system","content":BASE_SYSTEM_PROMPT + memory_context_snippet(mem)}

                        while not audio_state["queue"].empty(): audio_state["queue"].get_nowait()
                        buf = np.zeros(0,dtype=np.float32)
                        set_ui_state("offline" if audio_state["is_muted"] else "listening",
                                     "Microphone Muted" if audio_state["is_muted"] else "Listening...")
            
            except Exception as device_error:
                print(f"[Device Error] Failed to open mic {cur_mic}: {device_error}")
                print("[Device Error] Falling back to default system device.")
                audio_state["mic_id"] = None
                time.sleep(2)

            print("Device changed or errored, restarting loop...")
            audio_state["stream_active"] = False
        except Exception as e:
            print(f"Main loop error: {e}"); audio_state["stream_active"] = False
            time.sleep(1)

async def volume_broadcaster():
    while True:
        pct = min(100.0, audio_state.get("current_volume",0.0)*800) if audio_state["stream_active"] and not audio_state["is_muted"] else 0.0
        await manager.broadcast({"type":"volume","level":pct})
        await asyncio.sleep(0.1)

@asynccontextmanager
async def lifespan(app: FastAPI):
    manager.loop = asyncio.get_running_loop()
    threading.Thread(target=assistant_thread,daemon=True).start()
    asyncio.create_task(volume_broadcaster())
    yield

app = FastAPI(lifespan=lifespan)

@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=20.0)
            except asyncio.TimeoutError:
                # Send a ping to keep the browser connection alive
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception:
                    break
    except WebSocketDisconnect:
        manager.disconnect(websocket)

@app.get("/api/devices")
async def get_devices():
    devs = sd.query_devices()
    def filt(d,inp):
        seen,out = set(),[]
        for i,x in enumerate(d):
            ch = x["max_input_channels"] if inp else x["max_output_channels"]
            n  = x["name"]
            if ch<=0 or any(k in n.lower() for k in ["mapper","primary","dummy"]) or n in seen: continue
            seen.add(n); out.append({"id":i,"name":n})
        return out
    mics = [{"id":"default","name":"System Default"}] + filt(devs,True)
    spks = [{"id":"default","name":"System Default"}] + filt(devs,False)
    return {"mics":mics,"speakers":spks,
            "active_mic":audio_state["mic_id"] or "default",
            "active_speaker":audio_state["speaker_id"] or "default"}

class DeviceSelectRequest(BaseModel):
    type: str
    id: typing.Union[int,str]

@app.post("/api/devices")
async def set_device(req: DeviceSelectRequest):
    val = None if req.id=="default" else int(req.id)
    if req.type=="mic": audio_state["mic_id"]=val; audio_state["device_changed"].set()
    elif req.type=="speaker": audio_state["speaker_id"]=val
    return {"status":"ok"}

class MuteRequest(BaseModel):
    muted: bool

@app.post("/api/mute")
async def set_mute(req: MuteRequest):
    audio_state["is_muted"] = req.muted
    if req.muted:
        while not audio_state["queue"].empty():
            try: audio_state["queue"].get_nowait()
            except queue.Empty: break
        set_ui_state("offline","Microphone Muted")
    else: set_ui_state("listening","Listening...")
    return {"status":"ok","muted":req.muted}

@app.post("/api/test_speaker")
async def test_speaker():
    def run():
        speak_text("Oi mate, speaker's working. What do you need?")
        while not audio_state["queue"].empty():
            try: audio_state["queue"].get_nowait()
            except: break
        set_ui_state("listening","Listening...")
    threading.Thread(target=run,daemon=True).start()
    return {"status":"ok"}

@app.get("/api/memory")
async def get_memory(): return load_memory().get("facts",[])

@app.delete("/api/memory/{index}")
async def delete_memory(index: int):
    mem = load_memory()
    if 0 <= index < len(mem["facts"]):
        mem["facts"].pop(index); save_memory(mem)
    return {"status":"ok"}

@app.get("/api/planner/tasks")
async def planner_tasks():
    if _has_planner:
        from buddy_planner import list_tasks
        return {"tasks":list_tasks(include_done=True)}
    return {"tasks":"unavailable"}

@app.get("/api/planner/events")
async def planner_events():
    if _has_planner:
        from buddy_planner import list_events
        return {"events":list_events("all")}
    return {"events":"unavailable"}

class VisionStateRequest(BaseModel):
    state: str

@app.post("/api/reload_voice")
async def reload_voice():
    success = load_qwen_reference()
    if success:
        send_ui_thought("Voice reference reloaded successfully.")
        return {"status": "ok", "message": "Voice reference reloaded."}
    else:
        return {"status": "error", "message": "Failed to reload voice reference. Check buddy_voice/ folder."}

app.mount("/",StaticFiles(directory=str(UI_DIR),html=True),name="ui")

if __name__ == "__main__":
    print("Starting Buddy UI Backend on port 8001...")
    uvicorn.run(app, host="0.0.0.0", port=8001, log_level="warning")