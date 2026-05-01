import soundcard as sc
import numpy as np
import serial

# --- SETUP VARIABLES ---
SERIAL_PORT = 'COM4' 
BAUD_RATE = 115200

# Connect to the Hub
try:
    hub_serial = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.1)
    print(f"Connected to Pybricks Hub on {SERIAL_PORT}\n")
except Exception as e:
    print(f"Error connecting: {e}. Is Pybricks IDE disconnected?")
    exit()

# --- AUDIO DEVICE SELECTION ---
speakers = sc.all_speakers()
print("Available Audio Devices:")
for i, speaker in enumerate(speakers):
    print(f"[{i}] {speaker.name}")

try:
    choice = int(input("\nEnter the number of your actual speakers/headphones: "))
    selected_speaker = speakers[choice]
except (ValueError, IndexError):
    print("Invalid selection. Exiting.")
    exit()

try:
    mic = sc.get_microphone(id=selected_speaker.id, include_loopback=True)
    print(f"\nSuccessfully listening to: {selected_speaker.name}")
except Exception as e:
    print(f"Could not find loopback for this device: {e}")
    exit()

print("Play some audio! Press Ctrl+C to stop.\n")

# Changed to 48000Hz to match Windows standards for Bluetooth/HD Audio
with mic.recorder(samplerate=48000) as recorder:
    while True:
        data = recorder.record(numframes=1024)
        peak_volume = np.max(np.abs(data))
        
        # We are multiplying by 500 now to make it highly sensitive
        volume = min(int(peak_volume * 500), 100)
        
        # Print the RAW float value so we can see if it's literally 0.00000
        print(f"Raw Audio: {peak_volume:.5f} | Scaled Volume: {volume}   ", end='\r') 
        
        message = f"{volume}\n"
        hub_serial.write(message.encode('utf-8'))