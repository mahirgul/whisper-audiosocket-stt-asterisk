# Stereo Transcribe & Translate Pro - V2

An AI-powered stereo audio processing tool that transcribes and translates audio with independent channel control. Features real-time **Asterisk AudioSocket** integration for live transcription and offline translation using ArgosTranslate.

This is just a test project. It was created as a sample project for testing purposes.

## 🚀 Features

- **Stereo Processing:** Process Left and Right channels independently or as a unified timeline.
- **Offline Translation:** Local translation using ArgosTranslate (no API keys required).
- **Multiple AI Models:** Choose between Whisper `Small`, `Medium`, and `Large-v3` models for local transcription.
- **Asterisk Compatibility:** One-click export for Asterisk-compatible audio (8000 Hz, Mono, 16-bit PCM WAV).
- **AudioSocket Listener:** Real-time TCP server that accepts Asterisk AudioSocket connections, transcribes, and translates incoming audio on the fly — with multi-connection support.
- **History & Bulk Management:** Multi-select to delete past recordings or download full bundles (SRT + WAV).
- **Interactive Player:** Multi-channel waveform player with L/R/Stereo switching.
- **REST API:** Ready for external integration with one-shot endpoints.
- **Smart Launcher:** Automatically cleans up port conflicts and manages local AI models.

---

## 🛠 Installation

### Test Environment
- Windows 11
- Windows Terminal
- PowerShell 7.6.1
- Python 3.14

### Quick Setup (Recommended)

Run `install.bat` — it will automatically:
1. Install Python 3.14 via `winget` (if missing)
2. Install FFmpeg via `winget` (if missing)
3. Create a Python virtual environment (`venv/`)
4. Install all dependencies from `requirements.txt` + `audioop-lts`
5. Create `models/whisper/` and `outputs/` directories

### Manual Setup

```bash
winget install Python.Python.3.14
winget install ffmpeg

python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install audioop-lts
pip install argostranslate
```

---

## 💻 Usage

### Starting the Application

Run `run.bat`. The launcher will:
- Terminate any lingering process on port 8000
- Let you select a Whisper AI model (Small / Medium / Large)
- Download the model automatically if not cached locally
- Start the backend server and open the web UI in your browser

### Manual Start

```bash
python backend/web.py --model medium
```

Access the UI at `http://localhost:8000`.

---

## 📡 AudioSocket Integration

Stereo Transcribe & Translate Pro can act as a real-time AudioSocket server for Asterisk.

### How It Works

1. Asterisk dials an extension that uses `AudioSocket()` pointing to this server
2. The server receives raw PCM audio from the call
3. Voice Activity Detection (VAD) detects phrase boundaries (1.5 s silence = end of segment)
4. Each segment is transcribed (Whisper) → translated (ArgosTranslate)
5. All artifacts (WAV, SRTs) are saved to `audiosocket/{uuid}/`
6. Optionally, transcription/translation data is POST-ed to a configured REST endpoint

### Configuration — `audiosocket.json`

```json
{
  "port": 9092,
  "target_lang": "en",
  "input_sample_rate": 8000,
  "input_channels": 1,
  "input_sample_width": 2,
  "vad_silence_threshold_ms": 1500,
  "vad_min_chunk_ms": 1000,
  "delivery": {
    "enabled": false,
    "url": "http://your-server/api/receive-data",
    "method": "POST",
    "field_name": "audio",
    "extra_fields": {
      "session_id": "{uuid}",
      "lang": "{target_lang}"
    },
    "timeout_s": 10
  }
}
```

### Asterisk Dialplan Example

```
exten => 1234,1,Answer()
exten => 1234,2,AudioSocket(127.0.0.1:9092)
exten => 1234,3,Hangup()
```

### Output Structure

```
audiosocket/
  {asterisk-uuid}/
    session.json          — session metadata, config snapshot
    chunk_001.wav         — raw PCM chunk
    chunk_001_orig.srt    — Whisper transcript
    chunk_001_tran.srt    — translated SRT
    chunk_002.wav
    ...
```

---

## 🔌 REST API

### Documentation & Testing
- **Swagger UI:** `http://localhost:8000/docs`
- **ReDoc:** `http://localhost:8000/redoc`

### Endpoints

| Method | Route | Description |
|--------|-------|-------------|
| POST | `/transcribe` | Upload audio file → get transcription + translation |
| GET | `/audiosocket/status` | Server status + active connection count |
| GET | `/audiosocket/config` | Read `audiosocket.json` |
| POST | `/audiosocket/config` | Save config + hot-reload TCP server |
| GET | `/audiosocket/sessions` | Paginated session list |
| GET | `/audiosocket/sessions/{uuid}` | Session detail with chunk list |
| DELETE | `/audiosocket/sessions/{uuid}` | Delete session folder |
| GET | `/audiosocket/stream` | SSE live event stream |

---

## 📂 Project Structure

```
Stereo-Dubbing-Pro-V2/
├── backend/
│   ├── web.py                    — FastAPI server + all routes
│   ├── processor.py              — Whisper transcription, audio processing
│   ├── local_translator.py       — Offline translation via ArgosTranslate
│   ├── audiosocket_server.py     — Async TCP AudioSocket listener
│   └── audiosocket_processor.py — PCM→WAV, transcribe, translate, REST delivery
├── frontend/
│   ├── index.html                — Main transcription UI
│   ├── audiosocket.html          — AudioSocket monitor UI
│   └── static/
│       ├── css/
│       │   ├── style.css
│       │   └── audiosocket.css
│       └── js/
│           ├── script.js
│           ├── audiosocket.js
│           └── wavesurfer.min.js
├── models/
│   ├── whisper/                  — Cached Whisper model files (.pt)
│   └── argostranslate/           — Cached translation packages
├── outputs/                      — Generated SRTs + processed WAVs
├── audiosocket/                  — AudioSocket session recordings
├── audiosocket.json              — AudioSocket server configuration
├── requirements.txt
├── install.bat                   — First-time setup script
├── run.bat                       — Application launcher
└── .gitignore
```

---

## ⚖ License

MIT

---

*Powered by [mhrgl.com](https://mhrgl.com)*
