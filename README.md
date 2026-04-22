# Stereo Dubbing Pro - V2

An AI-powered stereo audio dubbing tool that transcribes, translates, and synthesizes voiceovers with independent channel control. Now with real-time **Asterisk AudioSocket** integration.

This is just a test project. It was created as a sample project for testing purposes.

## 🚀 Features

- **Stereo Dubbing:** Process Left and Right channels independently or as a unified timeline.
- **Text-to-Dub:** Generate dubbed stereo audio directly from text input with auto-translation.
- **Dynamic AI Voices:** Access dozens of high-quality Neural voices for every supported language, with gender and style variations.
- **Multiple AI Models:** Choose between Whisper `Small`, `Medium`, and `Large-v3` models for local transcription.
- **Asterisk Compatibility:** One-click export for Asterisk-compatible audio (8000 Hz, Mono, 16-bit PCM WAV).
- **AudioSocket Listener:** Real-time TCP server that accepts Asterisk AudioSocket connections, transcribes, translates, and dubs incoming audio on the fly — with multi-connection support.
- **REST Delivery:** Optionally POST dubbed audio to an external REST endpoint after each voice segment.
- **History & Bulk Management:** Multi-select to delete past recordings or download full bundles (SRT + Audio).
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

Stereo Dubbing Pro can act as a real-time AudioSocket server for Asterisk.

### How It Works

1. Asterisk dials an extension that uses `AudioSocket()` pointing to this server
2. The server receives raw PCM audio from the call
3. Voice Activity Detection (VAD) detects phrase boundaries (1.5 s silence = end of segment)
4. Each segment is transcribed (Whisper) → translated → dubbed (edge-tts)
5. All artifacts are saved to `audiosocket/{uuid}/`
6. Optionally, the dubbed MP3 is POST-ed to a configured REST endpoint

### Configuration — `audiosocket.json`

```json
{
  "port": 9092,
  "target_lang": "en",
  "voice_type": "M",
  "input_sample_rate": 8000,
  "input_channels": 1,
  "input_sample_width": 2,
  "vad_silence_threshold_ms": 1500,
  "vad_min_chunk_ms": 1000,
  "delivery": {
    "enabled": false,
    "url": "http://your-server/api/receive-audio",
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

The configuration can also be edited live from the **AudioSocket Monitor** page (`/audiosocket.html`). Changes take effect immediately without restarting the application.

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
    chunk_001_dub.mp3     — TTS dubbed audio
    chunk_002.wav
    ...
```

### Monitor Page

Open `/audiosocket.html` to:
- View and edit `audiosocket.json` in-browser
- Watch live connections and event logs in real time (Server-Sent Events)
- Browse and play back past session recordings chunk by chunk
- Delete individual sessions

---

## 🔌 REST API

### Documentation & Testing
- **Swagger UI:** `http://localhost:8000/docs`
- **ReDoc:** `http://localhost:8000/redoc`

### Dubbing Endpoints

| Method | Route | Description |
|--------|-------|-------------|
| POST | `/transcribe` | Upload audio file → get transcription + translation |
| POST | `/process-text` | Submit text → translate |
| POST | `/synthesize/{job_id}` | Generate stereo dubbed audio |
| POST | `/api/v1/dub-text` | One-shot: text → dubbed audio |
| GET | `/download/{filename}` | Download full bundle (MP3 + SRTs + WAV) |
| GET | `/history` | Paginated dubbing history |
| DELETE | `/delete/{filename}` | Delete a recording |
| DELETE | `/delete-multiple` | Bulk delete |

### AudioSocket Endpoints

| Method | Route | Description |
|--------|-------|-------------|
| GET | `/audiosocket/status` | Server status + active connection count |
| GET | `/audiosocket/config` | Read `audiosocket.json` |
| POST | `/audiosocket/config` | Save config + hot-reload TCP server |
| GET | `/audiosocket/sessions` | Paginated session list |
| GET | `/audiosocket/sessions/{uuid}` | Session detail with chunk list |
| DELETE | `/audiosocket/sessions/{uuid}` | Delete session folder |
| GET | `/audiosocket/stream` | SSE live event stream |

### One-Shot Dub API Example

```bash
curl -X POST "http://localhost:8000/api/v1/dub-text" \
     -F "text=Hello world" \
     -F "target_lang=tr"
```

---

## 📂 Project Structure

```
Stereo-Dubbing-Pro-V2/
├── backend/
│   ├── web.py                    — FastAPI server + all routes
│   ├── processor.py              — Whisper transcription, TTS, audio processing
│   ├── audiosocket_server.py     — Async TCP AudioSocket listener
│   └── audiosocket_processor.py — PCM→WAV, transcribe, translate, dub, REST delivery
├── frontend/
│   ├── index.html                — Main dubbing studio UI
│   ├── audiosocket.html          — AudioSocket monitor UI
│   ├── favicon.ico
│   └── static/
│       ├── css/
│       │   ├── style.css
│       │   └── audiosocket.css
│       └── js/
│           ├── script.js
│           ├── audiosocket.js
│           └── wavesurfer.min.js
├── models/
│   └── whisper/                  — Cached Whisper model files (.pt)
├── outputs/                      — Generated stereo dubs + SRTs
├── audiosocket/                  — AudioSocket session recordings
│   └── {uuid}/
├── audiosocket.json              — AudioSocket server configuration
├── requirements.txt
├── download_models.py            — Pre-download Whisper models
├── install.bat                   — First-time setup script
├── run.bat                       — Application launcher
└── .gitignore
```

---

## ⚖ License

MIT

---

*Powered by [mhrgl.com](https://mhrgl.com)*
