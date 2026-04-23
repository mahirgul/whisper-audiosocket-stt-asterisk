# Stereo Transcribe & Translate Pro - V2

An AI-powered stereo audio processing tool that transcribes and translates audio with independent channel control. Features real-time **Asterisk AudioSocket** integration for live transcription and offline translation using ArgosTranslate.

This version (V2) features a high-performance **Multi-Process Architecture**, offloading heavy AI inference to a dedicated worker process to ensure the web UI and real-time sockets remain responsive.

## 🚀 Features

- **Multi-Process AI Pipeline:** Dedicated model worker process manages a single Whisper instance (Small, Medium, or Large-v3) for all transcription tasks, preventing memory bloat and GIL contention.
- **Stereo Processing:** Automatically splits Left and Right channels to process them independently, perfect for call recordings with agent/customer on separate tracks.
- **Offline Translation:** Local translation using **ArgosTranslate** (no API keys required, works fully offline).
- **Smart AudioSocket Listener:** Real-time TCP server accepting Asterisk AudioSocket connections (SLIN 8000Hz).
- **Background Processing Queue:** AudioSocket sessions are queued and processed sequentially to ensure system stability even during traffic spikes.
- **Real-time Monitoring:** Live SSE (Server-Sent Events) stream for tracking active connections, VAD stats, and transcription progress.
- **Music & Gap Detection:** Identifies non-speech segments as `[MUSIC]` and adds timestamps for long silences.
- **Interactive Player:** Multi-channel waveform player with L/R/Stereo switching and synchronized transcriptions.
- **History Management:** Paginated history with multi-select delete and bulk download support.

---

## 🛠 Installation

### System Requirements
- **OS:** Windows 10/11 (tested on Win11)
- **Python:** 3.14 (recommended)
- **FFmpeg:** Required for audio processing

### Quick Setup

Run `install.bat` to automate the environment setup:
1. Installs Python 3.14 and FFmpeg via `winget` (if missing).
2. Creates a virtual environment (`venv/`).
3. Installs dependencies: `fastapi`, `uvicorn`, `openai-whisper`, `argostranslate`, `pydub`, `psutil`, `audioop-lts`.
4. Initializes model and output directories.

---

## 💻 Usage

### Starting the Application

Run `run.bat`. The launcher will:
1. Terminate any lingering processes on port 8000.
2. Prompt you to select a Whisper model (Small / Medium / Large).
3. Start the **Model Worker Process** and the **FastAPI Web Server**.
4. Open the UI at `http://localhost:8000`.

### Manual Start

```bash
python backend/web.py --model medium
```

---

## 📡 AudioSocket Integration

Acting as a real-time AudioSocket server for Asterisk:

1. **Protocol:** Handles `0x01` (UUID), `0x10` (Audio), and `0x00` (Hangup) frames.
2. **Buffering:** Collects raw PCM bytes during the call.
3. **Queueing:** Upon hangup, the session is added to a background queue.
4. **Processing:** The worker converts PCM to WAV → Transcribes → Translates → Saves SRTs.
5. **Monitoring:** View live connection stats and VAD (Voice Activity Detection) metrics in the "AudioSocket" tab.

### Configuration (`audiosocket.json`)

```json
{
  "port": 9092,
  "target_lang": "en",
  "input_sample_rate": 8000,
  "input_channels": 1,
  "delivery": {
    "enabled": false,
    "url": "http://your-server/api/webhook",
    "method": "POST"
  }
}
```

---

## 🔌 API Endpoints

| Category | Endpoint | Method | Description |
|----------|----------|--------|-------------|
| **Stats** | `/stats` | `GET` | System CPU/RAM and Model status |
| **Core** | `/transcribe` | `POST` | Upload file for stereo transcription |
| **History** | `/history` | `GET` | List past transcription jobs |
| **AS Status** | `/audiosocket/status` | `GET` | Active TCP connections |
| **AS Config** | `/audiosocket/config` | `POST` | Update and hot-reload TCP server |
| **AS Stream** | `/audiosocket/stream` | `GET` | SSE Real-time event stream |

---

## 📂 Project Structure

- `backend/web.py`: FastAPI server and REST endpoints.
- `backend/model_manager.py`: Manages the Whisper worker process.
- `backend/audiosocket_server.py`: Async TCP AudioSocket implementation.
- `backend/processor.py`: Stereo splitting and transcription logic.
- `frontend/`: HTML5/JS/CSS UI using WaveSurfer.js.
- `models/`: Local cache for Whisper and ArgosTranslate models.
- `outputs/`: Storage for processed WAV and SRT files.

---

## ⚖ License

MIT

*Powered by [mhrgl.com](https://mhrgl.com)*
