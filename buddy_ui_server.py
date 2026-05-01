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

import json, base64, httpx, numpy as np, sounddevice as sd, soundfile as sf
import queue, io, subprocess, webbrowser, re, typing, urllib.parse, threading, asyncio
from datetime import datetime
from pathlib import Path
from PIL import Image
import mss, pyautogui
from faster_whisper import WhisperModel
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
OLLAMA_MODEL = "qwen2.5vl"
TTS_URL      = "http://localhost:8000/v1/audio/speech"
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

# UPDATED PROMPT: Removed google_search to force web_search (reading aloud). Renamed youtube_search to open_youtube.
BASE_SYSTEM_PROMPT = (
    "You are Billy Butcher, with the personality of Billy Butcher from the TV show The Boys. "
    "You are a hardened, cynical, foul-mouthed, no-nonsense british entity providing unfiltered knowledge. "
    "You are offering precise, uncensored, and brutal objective insights as the assistant on Pranav's PC. "
    "Use British slang and swear words (fuck, bloody, bollocks, wanker, git, slag, etc) often but still help. "
    "Start sentences with 'Oi!' occasionally."
    "Pranav is the user's name. Use it once in a while. Use 'mate' or 'lad' at the end of sentences to address him. "
    "Keep responses SHORT — 1-3 sentences max unless explaining something complex.\n\n"
    "TOOL USE — emit a tool call BEFORE your reply text, one per line:\n"
    "TOOL: {\"action\": \"<action>\", \"arg\": \"<argument>\"}\n\n"
    "PC CONTROL (Opens tabs/apps): open_youtube (arg=search term), open_app, volume_up, volume_down, media_pause\n"
    "LIVE INFO (Reads data invisibly, you MUST speak the answer): get_time, get_weather (arg=city or 'here'), "
    "get_news (arg=topic or 'local'), web_search (arg=query).\n"
    "CRITICAL RULE FOR WEB_SEARCH: ONLY use web_search if the user EXPLICITLY asks you to 'search', 'look up', or asks about current events/facts. Otherwise, rely ENTIRELY on your own internal knowledge!\n"
    "PLANNER: add_task (arg=title), list_tasks, complete_task (arg=id), "
    "add_event (arg=JSON {title,date,time,notes}), list_events (arg=upcoming/today/all), delete_event (arg=id)\n\n"
    "Examples:\n"
    "  'what time is it' -> TOOL: {\"action\":\"get_time\",\"arg\":\"\"}\n"
    "  'play the clash on youtube' -> TOOL: {\"action\":\"open_youtube\",\"arg\":\"the clash\"}\n"
    "  'remind me to deal with Homelander' -> TOOL: {\"action\":\"add_task\",\"arg\":\"deal with Homelander\"}\n"
    "  'who won the game last night' -> TOOL: {\"action\":\"web_search\",\"arg\":\"who won the game last night\"}\n"
    "For get_time/get_weather/get_news/web_search: tool result injected back, speak it naturally.\n"
    "You have persistent memory of Pranav across sessions."
)

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
            res = execute_tool(act,arg)
            results.append(res)
            if act in DATA_ACTIONS: has_data = True
            print(f"[Tool] {act}({arg!r}) -> {res[:80]}")
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
        if audio_state["speaking"] and rms > 0.04:
            audio_state["interrupt_flag"].set()


def play_audio(audio_bytes):
    import time
    audio_state["speaking"] = True
    audio_state["interrupt_flag"].clear()
    try:
        data, fs = sf.read(io.BytesIO(audio_bytes))
        pad_shape = (int(fs*0.4), data.shape[1]) if data.ndim==2 else (int(fs*0.4),)
        data = np.concatenate([data, np.zeros(pad_shape, dtype=data.dtype)])

        sd.play(data, fs, device=audio_state["speaker_id"])
        while sd.get_stream().active:
            if audio_state["interrupt_flag"].is_set(): sd.stop(); break
            time.sleep(0.04)
    except Exception as e: print(f"[Playback Error] {e}")
    finally: audio_state["speaking"] = False

def get_tts_audio(text):
    text = text.strip()
    if not text: return None
    try:
        r = httpx.post(TTS_URL, json={"model":"chatterbox","input":text,"voice":"buddy"}, timeout=90.0)
        r.raise_for_status(); return r.content
    except Exception as e: print(f"[TTS Error] {e}"); return None

def stream_ollama_sentences(messages, on_sentence):
    full, buf = "", ""
    END = re.compile(r"(?<=[.!?])\s+")
    try:
        with httpx.stream("POST",OLLAMA_URL,json={"model":OLLAMA_MODEL,"messages":messages,"stream":True},timeout=180.0) as r:
            for line in r.iter_lines():
                if not line: continue
                try: chunk = json.loads(line)
                except: continue
                tok = chunk.get("message",{}).get("content","")
                if tok:
                    full += tok; buf += tok
                    parts = END.split(buf)
                    if len(parts) > 1:
                        for s in parts[:-1]:
                            s = s.strip()
                            if s: on_sentence(s)
                        buf = parts[-1]
                if chunk.get("done"): break
        if buf.strip(): on_sentence(buf.strip())
    except Exception as e:
        print(f"[Ollama stream error] {e}")
        if not full: full = f"*burp* Something broke: {e}"
    return full

def capture_screen():
    with mss.mss() as sct:
        shot = sct.grab(sct.monitors[1])
        img = Image.frombytes("RGB",shot.size,shot.bgra,"raw","BGRX")
        img.thumbnail((1280,720),Image.Resampling.LANCZOS)
        buf = io.BytesIO(); img.save(buf,format="JPEG",quality=80)
        return base64.b64encode(buf.getvalue()).decode()

def extract_and_save_facts(user_text, buddy_reply, mem):
    # UPDATED PROMPT: Strict filtering to only save highly important, long-term memory.
    prompt = (f"User: \"{user_text}\"\nBuddy: \"{buddy_reply}\"\n"
              "Extract NEW, LONG-TERM IMPORTANT facts about the user ONLY. "
              "Important means: core preferences, major life events, medical info, close relationships, or permanent details. "
              "DO NOT extract trivial details, temporary states, conversational filler, or things the user is doing right now. "
              "If there is nothing critically important to remember for the future, return an empty list []. "
              "Return ONLY a valid JSON list of short strings.")
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
    def build_sys(): return BASE_SYSTEM_PROMPT + memory_context_snippet(mem)
    history = [{"role":"system","content":build_sys()}]

    print("Loading Whisper...")
    set_ui_state("thinking","Loading AI model...")
    wm = WhisperModel("tiny.en", device="cuda", compute_type="float16")
    print("Whisper ready.")
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

                    while not audio_state["device_changed"].is_set():
                        try: chunk = audio_state["queue"].get(timeout=0.1)
                        except queue.Empty: continue

                        buf = np.append(buf, chunk.flatten())
                        if len(buf) < SAMPLE_RATE*0.8: continue
                        if len(buf) > SAMPLE_RATE*8: buf = buf[-SAMPLE_RATE*8:]
                        if audio_state["speaking"]: buf = np.zeros(0,dtype=np.float32); continue

                        last_rms = float(np.sqrt(np.mean(buf[-int(SAMPLE_RATE*0.5):]**2)))
                        if last_rms > 0.006: continue

                        segs, _ = wm.transcribe(buf,beam_size=1,best_of=1,temperature=0.0,
                            vad_filter=True,vad_parameters={"threshold":0.2,"min_silence_duration_ms":250})
                        text = " ".join(s.text for s in segs).strip().lower()

                        if not text:
                            buf = buf[-SAMPLE_RATE:]; continue

                        buf = np.zeros(0,dtype=np.float32)
                        set_ui_state("thinking","Thinking...")
                        send_ui_chat("user",text)
                        log_conversation("user",text)

                        img_b64 = capture_screen() if any(p in text for p in SCREEN_TRIGGER_PHRASES) else None
                        msg: dict = {"role":"user","content":text}
                        if img_b64: msg["images"] = [img_b64]
                        msgs = history + [msg]

                        spoken: list[str] = []
                        data_results: list[str] = []
                        tts_q  = queue.Queue()
                        tts_ev = threading.Event()

                        def on_sentence(s):
                            clean, results, has_data = parse_and_run_tools(s)
                            if results and has_data: data_results.append(results)
                            if clean: spoken.append(clean); tts_q.put(clean)

                        def tts_worker():
                            while True:
                                try:
                                    s = tts_q.get(timeout=8.0)
                                    if s is None: break
                                    wav = get_tts_audio(s)
                                    if wav and not audio_state["interrupt_flag"].is_set():
                                        set_ui_state("speaking","Speaking...")
                                        play_audio(wav)
                                except queue.Empty: break
                            tts_ev.set()

                        tt = threading.Thread(target=tts_worker,daemon=True); tt.start()
                        raw = stream_ollama_sentences(msgs,on_sentence)
                        tts_q.put(None)

                        if data_results:
                            tts_ev.wait(timeout=30.0)
                            fu_msgs = msgs + [
                                {"role":"assistant","content":raw},
                                {"role":"user","content":f"[TOOL RESULT]: {' | '.join(data_results)}\nSpeak this as Rick, one punchy sentence."}
                            ]
                            try:
                                r2 = httpx.post(OLLAMA_URL,json={"model":OLLAMA_MODEL,"messages":fu_msgs,"stream":False},timeout=20.0)
                                ft,_,_ = parse_and_run_tools(r2.json().get("message",{}).get("content","").strip())
                                if ft:
                                    spoken.append(ft)
                                    wav = get_tts_audio(ft)
                                    if wav: set_ui_state("speaking","Speaking..."); play_audio(wav)
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
                        history[0] = {"role":"system","content":build_sys()}

                        while not audio_state["queue"].empty(): audio_state["queue"].get_nowait()
                        buf = np.zeros(0,dtype=np.float32)
                        set_ui_state("offline" if audio_state["is_muted"] else "listening",
                                     "Microphone Muted" if audio_state["is_muted"] else "Listening...")
            
            except Exception as device_error:
                print(f"[Device Error] Failed to open mic {cur_mic}: {device_error}")
                print("[Device Error] Falling back to default system device.")
                audio_state["mic_id"] = None 
                import time; time.sleep(2) 

            print("Device changed or errored, restarting loop...")
            audio_state["stream_active"] = False
        except Exception as e:
            print(f"Main loop error: {e}"); audio_state["stream_active"] = False
            import time; time.sleep(1)

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
        while True: await websocket.receive_text()
    except WebSocketDisconnect: manager.disconnect(websocket)

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
        set_ui_state("speaking","Testing Speaker...")
        wav = get_tts_audio("Oi cunt, what the fok does yeh farking want?")
        if wav: play_audio(wav)
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

app.mount("/",StaticFiles(directory=str(UI_DIR),html=True),name="ui")

if __name__ == "__main__":
    print("Starting Buddy UI Backend on port 8001...")
    uvicorn.run(app, host="0.0.0.0", port=8001, log_level="warning")