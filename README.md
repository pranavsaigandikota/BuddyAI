# BuddyAI: A Local Multimodal PC Assistant

BuddyAI is a comprehensive, locally-hosted digital assistant designed for PC automation, information retrieval, and multimodal interaction. Developed as a privacy-focused alternative to commercial assistants, BuddyAI integrates advanced large language models (LLMs), vision systems, and hardware-level control to provide a seamless desktop experience.

## Objective
The primary goal of this project was to construct a robust assistant capable of operating entirely on local hardware. By leveraging local inference via Ollama and Faster-Whisper, BuddyAI avoids the latency and privacy concerns associated with cloud-based AI services. The system is designed to act as an efficient PC entity capable of managing tasks, controlling media, and interpreting visual data from the user's screen.

## System Architecture
The application is built on a modular Python-based backend using FastAPI, interfacing with a web-based frontend.

### 1. Natural Language Processing
- **Inference Engine**: Utilizes Ollama running the Qwen-2.5-VL model. This model provides both high-quality text generation and vision-language capabilities.
- **Context Management**: Implements a persistent JSON-based memory system that stores user preferences and facts across sessions.
- **System Prompting**: The agent is configured with a specific persona to provide concise and direct communication.

### 2. Audio Processing Pipeline
- **Speech-to-Text (STT)**: Employs the `faster-whisper` library for low-latency transcription of microphone input.
- **Text-to-Speech (TTS)**: Interfaces with a custom local server to generate voice responses using high-quality synthesized audio.
- **Hardware Integration**: Uses the `sounddevice` and `soundfile` libraries for direct interaction with system audio drivers, supporting device selection and mute functionality.

### 3. Vision and PC Automation
- **Visual Intelligence**: Captures screen data using the `mss` library. The system can interpret user activity by injecting screenshots into the Vision-Language Model.
- **Desktop Control**: Utilizes `pyautogui` for volume regulation, media playback control, and application execution (e.g., Discord, VS Code, Steam).

### 4. Planner and Data Services
- **Task Management**: A SQLite-backed planner (`buddy_planner.py`) allows for persistent task and calendar event tracking.
- **Information Retrieval**: Integrates search capabilities for real-time web data, weather updates, and news aggregation.

## Technical Requirements
- **Python 3.10+**
- **Ollama** (configured with a Vision-capable model)
- **CUDA-compatible GPU** (highly recommended for Faster-Whisper and LLM acceleration)
- **Windows OS** (optimized for Windows paths and application mapping)

## Project Structure
- `buddy_ui_server.py`: Main FastAPI entry point and system orchestrator.
- `buddy_planner.py`: Database management for tasks and events.
- `buddy_search.py`: Web and news search integration.
- `ui/`: Frontend assets (HTML, CSS, JavaScript).
- `memory/`: Persistent storage for logs, facts, and databases.

## Setup
1. Ensure Ollama is running with the required model.
2. Install dependencies via `pip install -r requirements_buddy.txt`.
3. Configure the TTS server endpoint in the server script if necessary.
4. Execute `run_buddy.bat` or `run_buddy_app.bat` to initialize the system.
