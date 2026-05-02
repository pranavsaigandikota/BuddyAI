import subprocess
import time
import sys
import urllib.request
import threading


def wait_for_ollama(timeout=60):
    print("[WAIT] Waiting for Ollama to be ready...")
    start = time.time()
    while time.time() - start < timeout:
        try:
            urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2)
            print("[WAIT] Ollama is ready!")
            return True
        except:
            time.sleep(2)
    print("[WARN] Ollama did not respond — continuing anyway.")
    return False


def stream_output(proc, prefix):
    for line in iter(proc.stdout.readline, ''):
        if line:
            print(f"[{prefix}] {line.strip()}")


def main():
    print("=== Project Antigravity Orchestrator ===\n")

    # 1. Start Ollama (LLM backend) — only if not already running
    print("[1/5] Checking Ollama server...")
    ollama_proc = None
    try:
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2)
        print("[1/5] Ollama already running — skipping launch.")
    except:
        print("[1/5] Launching Ollama server...")
        ollama_proc = subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        threading.Thread(target=stream_output, args=(ollama_proc, "OLLAMA"), daemon=True).start()
        wait_for_ollama(timeout=60)

    # 2. Start Kinect Server
    print("[2/4] Launching KinectServer.exe...")
    kinect_proc = subprocess.Popen(
        ["KinectServer.exe"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    threading.Thread(target=stream_output, args=(kinect_proc, "KINECT"), daemon=True).start()
    time.sleep(2)

    # 3. Start Vision (uses same env as orchestrator, needs ultralytics)
    print("[3/4] Launching buddy_vision.py...")
    vision_python = r"c:\users\filma\anaconda3\python.exe"
    vision_proc = subprocess.Popen(
        [vision_python, "buddy_vision.py"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    threading.Thread(target=stream_output, args=(vision_proc, "VISION"), daemon=True).start()
    time.sleep(1)

    # 4. Start UI/LLM Chat Server (uses `whisperx` conda env)
    print("[4/4] Launching buddy_ui_server.py...")
    whisperx_python = r"c:\users\filma\anaconda3\envs\whisperx\python.exe"
    ui_proc = subprocess.Popen(
        [whisperx_python, "buddy_ui_server.py"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    threading.Thread(target=stream_output, args=(ui_proc, "LLM_UI"), daemon=True).start()

    print("\n--- All Systems Running ---")
    print("Open http://localhost:8001 in your browser to chat with Buddy.")
    print("Press Ctrl+C to shut everything down.\n")

    try:
        while True:
            time.sleep(2)
            if ollama_proc and ollama_proc.poll() is not None: print("WARNING: Ollama died!")
            if kinect_proc.poll() is not None: print("WARNING: KinectServer died!")
            if vision_proc.poll() is not None: print("WARNING: buddy_vision died!")
            if ui_proc.poll() is not None:     print("WARNING: buddy_ui_server died!")
    except KeyboardInterrupt:
        print("\nShutting down all systems...")
        for proc in [ollama_proc, kinect_proc, vision_proc, ui_proc]:
            try:
                if proc: proc.terminate()
            except: pass
        print("Goodbye!")


if __name__ == "__main__":
    main()
