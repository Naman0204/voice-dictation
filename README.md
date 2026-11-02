# Voice Dictation

Voice dictation you trigger with a hotkey of your choice: tap it, speak, and the text types itself wherever your cursor is. I built it as a free, fully local alternative to Wispr Flow, and as a bonus it handles accents just as well.

## What it does
- **Dictate into any app.** Triple-tap your hotkey, speak, and the words type into whatever field has focus. Tap again to stop.
- **Voice notes.** A second hotkey records and transcribes a note, with optional task extraction.
- **Fully offline.** Transcription runs on your machine with faster-whisper. Nothing is sent to the cloud.
- **Configurable.** Pick your trigger keys, model size, and behavior in `config.json`.

## Requirements
- Windows
- Python 3.12 (3.11+ works, 3.12 recommended)
- First launch downloads the speech model once, so you need internet that one time. After that it runs offline.

## Setup
1. Clone the repo:
   ```
   git clone https://github.com/Naman0204/voice-dictation.git
   ```
2. Double-click **`setup.bat`** (creates the environment and installs dependencies).
3. Double-click **`run.bat`** to start. The app lives in your system tray.

Prefer the command line?

```
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe main.py
```

## Usage
- Triple-tap **D** (default) anywhere, speak, and your words type into the focused field.
- Triple-tap **R** (default) to record a voice note.
- Change the keys and settings in `config.json`. A clean template is in `config.example.json`.

## Optional
- **AI task extraction** from your notes uses a local LLM through [LM Studio](https://lmstudio.ai) at `localhost:1234`. Without it, the app falls back to keyword extraction.
- **One-click launcher.** `tools/launcher/VoiceNotesLauncher.cs` is an optional tray helper for starting the app on login. Build instructions are in the file. Not needed to use the app.

## Privacy
Everything runs locally. Your audio and transcripts stay on your machine and are never uploaded.

## License
MIT. See [LICENSE](LICENSE).
