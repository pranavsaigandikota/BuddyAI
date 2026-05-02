
content = open('buddy_ui_server.py', encoding='utf-8').read()

START = '# Init Qwen3-TTS\nqwen_tts_model = None'
END   = 'print(f"[TTS] Qwen3-TTS load error: {e}")'

i = content.find(START)
j = content.find(END, i) + len(END)

if i == -1 or j == -1:
    print('ERROR: markers not found')
    print(repr(content[content.find('Qwen3'):content.find('Qwen3')+200]))
else:
    new_block = '''# Init Qwen3-TTS
# REF_TEXT = exact words spoken in buddy_voice/reference.wav (required to avoid CUDA assertion)
REF_TEXT = "never got the point of these, to me"

qwen_tts_model = None
voice_clone_prompt = None
try:
    if Qwen3TTSModel:
        print("[TTS] Loading Qwen3-TTS-0.6B-Base...")
        qwen_tts_model = Qwen3TTSModel.from_pretrained(
            "Qwen/Qwen3-TTS-12Hz-0.6B-Base", device_map="cuda:0", dtype=torch.float16
        )
        ref_path = str(BASE_DIR / "buddy_voice" / "reference.wav")
        if os.path.exists(ref_path):
            import librosa
            _wav, _sr = sf.read(ref_path, dtype="float32")
            if _wav.ndim > 1: _wav = _wav.mean(axis=1)
            if _sr != 16000: _wav = librosa.resample(_wav, orig_sr=_sr, target_sr=16000)
            _wav = _wav[:16000 * 10]
            _proc = str(BASE_DIR / "buddy_voice" / "reference_16k.wav")
            sf.write(_proc, _wav, 16000)
            print("[TTS] Building Voice Clone prompt...")
            voice_clone_prompt = qwen_tts_model.create_voice_clone_prompt(
                ref_audio=_proc, ref_text=REF_TEXT
            )
            print("[TTS] Qwen3-TTS ready!")
        else:
            print(f"[TTS] reference.wav not found at {ref_path}")
except Exception as e:
    print(f"[TTS] Qwen3-TTS load error: {e}")'''

    new_content = content[:i] + new_block + content[j:]
    open('buddy_ui_server.py', 'w', encoding='utf-8').write(new_content)
    print('SUCCESS - patched', i, 'to', j)
