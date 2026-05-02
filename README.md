# Project Antigravity: Buddy AI
### A Local Multimodal PC Assistant with East London Grit

**Project Antigravity** is a high-performance, privacy-first PC assistant designed to live natively on your hardware. It blends state-of-the-art Multimodal LLMs, real-time spatial tracking, and zero-shot voice cloning to create an entity that doesn't just process commands—it observes, responds, and remembers.

---

## 🦾 The Persona: Billy Butcher
Buddy isn't your typical "polite" AI. He is modeled after **Billy Butcher** (*The Boys*).
- **Hardened, Cynical, and Direct**: No "How can I help you today?" fluff.
- **East London Grit**: Authentic slang, dropping H's, and a healthy dose of sarcasm.
- **Conversational Flow**: Optimized to speak in winding, natural sentences rather than robotic fragments.

---

## 🏗️ Architecture: "Antigravity Slim"
A primary challenge was running a full multimodal stack (VLM + STT + TTS) on a single consumer GPU (16GB VRAM) while maintaining low latency.

### **Engineering Decisions & Rationale**

#### **1. VRAM Optimization (CPU/GPU Load Balancing)**
- **Decision**: STT and Vision-Preprocessing are offloaded to the **CPU**, while the **GPU** is reserved exclusively for the LLM (`Qwen2.5-VL`) and the TTS Synthesis (`Qwen3-TTS`).
- **Why**: Standard ASR models like Whisper can be greedy with VRAM. By running Parakeet on the CPU, we ensure the LLM has maximum overhead for complex vision reasoning without causing OOM (Out of Memory) errors during synthesis.

#### **2. Speech-to-Text: Parakeet (0.6B) on CPU**
- **Decision**: Switched from Faster-Whisper to NVIDIA’s **Parakeet-CTC**.
- **Why**: Parakeet is exceptionally efficient. Running the 0.6B parameter model on the CPU provides near-instant transcription with higher accuracy for accented speech (crucial for Butcher's slang) without touching GPU resources.

#### **3. Text-to-Speech: Qwen3-TTS with Zero-Shot Cloning**
- **Decision**: Integrated **Qwen3-TTS-0.6B-Base** for all synthesis.
- **Why**: Traditional TTS (like Kokoro or gTTS) sounds too clean for a character like Butcher. Qwen3-TTS allows for **Zero-Shot Voice Cloning**. By providing a 10s reference clip and transcript, Buddy inherits the specific grit, texture, and emotional weight of the target persona.

#### **4. Dual-Track Vision: YOLO vs. VLM**
- **Decision**: Use **YOLOv8** for spatial tracking and **Qwen2.5-VL** for scene understanding.
- **Why**: 
    - **YOLO** handles the "dumb" fast tasks: tracking the user's head and tilting the physical Kinect motor in real-time.
    - **VLM** handles the "smart" tasks: looking at the user's screen or camera feed to answer questions.
    - **Clean Feed Logic**: We modified the pipeline so YOLO draws its tracking boxes on a local UI for the user to see, but sends a **clean, unmodified image** to the LLM. This prevents the LLM from getting confused by neon green boxes and stick figures.

---

## 🛠️ Key Features
- **Spatial Awareness**: Real-time Kinect motor control to keep the user in frame.
- **Multimodal Context**: Can see your screen ("What am I looking at?") and your room ("What am I holding?").
- **Persistent Memory**: Remembers personal facts, preferences, and past conversations via a local JSON memory bank.
- **Live Voice Reload**: A dedicated UI button to hot-swap voice reference files without a server restart.
- **PC Control**: Native hooks for Volume, Media, YouTube, and application launching (Discord, VS Code, etc.).

---

## 📂 Project Structure
- `run_antigravity.py`: The master orchestrator that spins up the LLM, Vision, and UI servers.
- `buddy_ui_server.py`: The central nervous system (FastAPI, LLM Logic, TTS Synthesis).
- `buddy_vision.py`: Spatial tracking, YOLO processing, and Kinect hardware control.
- `buddy_planner.py`: SQLite-backed task and event management.
- `buddy_voice/`: Contains the reference audio and text for voice cloning.
- `ui/`: Premium glass-morphic web interface.

---

## 🚀 Setup & Launch
1. **Ollama**: Install and run `ollama serve`. Pull the model: `ollama pull qwen2.5-vl:3b`.
2. **Kinect**: Ensure Kinect V2 is connected and `KinectServer.exe` is in the root.
3. **Environment**: Install dependencies from `requirements_buddy.txt` and `requirements_tts.txt`.
4. **Run**: Execute `python run_antigravity.py`.

---
*Properly bloody marvelous, innit?*
