# Stereo Transcribe & Translate Pro - V2

> **✨ Made with Gemini ✨**

An AI-powered stereo audio processing tool that transcribes and translates audio with independent channel control. Features real-time **Asterisk AudioSocket** integration for live transcription and offline translation using ArgosTranslate.

This version (V2) features a high-performance **Multi-Process Architecture**, offloading heavy AI inference to a dedicated worker process to ensure the web UI and real-time sockets remain responsive.

## 🚀 Features

- **Multi-Process AI Pipeline:** Dedicated model worker process manages a single Whisper instance (Small, Medium, or Large-v3) for all transcription tasks, preventing memory bloat and GIL contention.
- **GPU Acceleration:** Automatic CUDA detection for 5-10x faster transcription on compatible hardware.
- **High-Performance Translation:** Optimized batched translation via **ArgosTranslate**, reducing processing time for long conversations.
- **Secure File Handling:** Robust path traversal protection for all job and session management endpoints.
- **Stereo Processing:** Automatically splits Left and Right channels to process them independently, perfect for call recordings with agent/customer on separate tracks.
- **Smart AudioSocket Listener:** Real-time TCP server accepting Asterisk AudioSocket connections (SLIN 8000Hz) with improved VAD accuracy.
- **Background Processing Queue:** AudioSocket sessions are queued and processed sequentially to ensure system stability even during traffic spikes.
- **CPU & I/O Optimization:** Reduced update frequencies, faster connection timeouts, and optimized disk writes for intermediate session states.
- **Real-time Monitoring:** Live SSE (Server-Sent Events) stream for tracking active connections, VAD stats, and transcription progress.
- **Interactive Player:** Multi-channel waveform player with L/R/Stereo switching and synchronized transcriptions.

---

## 🛠 Installation

### System Requirements
- **OS:** Windows 10/11 (tested on Win11)
- **Python:** 3.10+ (tested on 3.14)
- **FFmpeg:** Required for audio processing
- **GPU (Optional):** NVIDIA GPU with CUDA for best performance.

### Quick Setup

Run `install.bat` to automate the environment setup:
1. Installs Python and FFmpeg via `winget` (if missing).
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
4. Access the UI at `http://localhost:8000`.

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
5. **Monitoring:** View live connection stats and VAD metrics in the "AudioSocket" tab.

### Configuration (`audiosocket.json`)

```json
{
  "port": 9092,
  "target_lang": "en",
  "send_silence_frames": false,
  "force_endian_swap": false,
  "delivery": {
    "enabled": false,
    "url": "http://your-server/api/webhook"
  }
}
```

*Note: `send_silence_frames` is disabled by default to save CPU cycles (50 wakeups/sec per connection).*

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
- `backend/model_manager.py`: Manages the Whisper worker process (CUDA enabled).
- `backend/audiosocket_server.py`: Async TCP AudioSocket implementation.
- `backend/processor.py`: Stereo splitting and transcription logic.
- `backend/local_translator.py`: Batched offline translation via ArgosTranslate.
- `frontend/`: HTML5/JS/CSS UI using WaveSurfer.js.

---

## ⚖ License

MIT

*Powered by [mhrgl.com](https://mhrgl.com)*
