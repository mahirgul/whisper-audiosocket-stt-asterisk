# WASA — Whisper AudioSocket Asterisk (V2)

> **✨ Developed & Optimized with Gemini ✨**
> *This project has been significantly enhanced and maintained using Google Gemini CLI, ensuring modern coding standards and robust implementation.*

An AI-powered stereo audio processing tool that transcribes audio with independent channel control. Features real-time **Asterisk AudioSocket** integration for live transcription.

WASA (V2) features a high-performance **Multi-Process Architecture**, offloading heavy AI inference to a dedicated worker process to ensure the web UI and real-time sockets remain responsive even under load.

---

## 🚀 Key Features

- **Multi-Process AI Pipeline:** Dedicated model worker process manages a single Whisper instance (Tiny, Base, Small, Medium, Large, or Turbo) for all transcription tasks, preventing memory bloat and GIL contention.
- **GPU Acceleration:** Automatic CUDA detection for 5-10x faster transcription on compatible hardware.
- **Ignore Silence Timeout:** (New) Option to keep connections alive even during long periods of silence, preventing premature hangups from the Asterisk side.
- **Send Silence Frames:** Built-in keepalive mechanism that sends silent frames back to Asterisk to maintain active sessions.
- **Smart VAD (Voice Activity Detection):** RMS-based silence detection with configurable thresholds and minimum chunk durations.
- **Independent Stereo Processing:** Automatically splits Left and Right channels to process them independently, perfect for call recordings with agent/customer on separate tracks.
- **Real-time Monitoring:** Live SSE (Server-Sent Events) stream for tracking active connections, VAD stats, and transcription progress.
- **Secure Architecture:** Robust path traversal protection and isolated session management.

---

## 📡 AudioSocket Integration

WASA acts as a high-performance TCP server for the Asterisk AudioSocket protocol:

1.  **Connection:** Handles `0x01` (UUID), `0x10` (Audio), and `0x00` (Hangup) frames.
2.  **Isolation:** Every incoming connection is handled in a completely isolated asynchronous coroutine with its own memory buffer, ensuring no audio mixing between concurrent calls.
3.  **Buffering:** During the call, raw PCM bytes are collected and stored in RAM.
4.  **Processing (on_close):** Once the call hangs up, the buffered audio is converted to a WAV file and queued for Whisper transcription.
5.  **Transcription:** The dedicated Model Worker process picks up the job, performs the transcription (and optional translation), and saves the results as JSON and SRT files.

---

## ⚙️ Configuration (`audiosocket.json`)

You can manage all settings via the **Config** tab in the Web UI. Key settings include:

- **Listen Port:** TCP port for the AudioSocket server (Default: `9092`).
- **Silence Threshold (ms):** Maximum duration of silence allowed before the server automatically closes the connection (unless Ignore Silence is enabled).
- **Ignore Silence Timeout:** If enabled, the server will not close the connection due to inactivity/silence.
- **Send Silence:** Sends 20ms silence frames back to Asterisk to keep the media path active.
- **RMS Threshold:** The volume level (Noise Floor) below which audio is considered silent.
- **Whisper Options:**
    - `task`: Set to `"translate"` to automatically translate any language to English.
    - `initial_prompt`: Provide context or specific vocabulary to improve accuracy.

---

## 🛠 Installation & Setup

### Requirements
- **OS:** Windows 10/11
- **Python:** 3.10+
- **FFmpeg:** Required for audio encoding/decoding.
- **NVIDIA GPU:** Recommended (with CUDA) for near real-time performance.

### Quick Start
1. Run `install.bat` to setup the virtual environment and install dependencies.
2. Run `run.bat` to launch the application.
3. Select your desired Whisper model when prompted.
4. Access the dashboard at `http://localhost:8000`.

---

## 📂 Project Architecture

- **`backend/audiosocket_server.py`**: The core TCP server. Manages connections, VAD, and buffering.
- **`backend/model_manager.py`**: Manages the separate Whisper process. Ensures only one model is loaded in memory.
- **`backend/web.py`**: FastAPI-based web server and REST API.
- **`frontend/`**: Modern dashboard for monitoring live calls and viewing transcription history.

---

## 🤖 Gemini's Contribution

This project has been updated and optimized by **Gemini CLI**. Key Gemini-driven enhancements include:
- Implementation of the **Ignore Silence Timeout** feature.
- Refactoring the **AudioSocket reader** for better EOF vs. Timeout handling.
- Localization of the **UI and Configuration** system to English.
- Comprehensive **code documentation** and English comment conversion.
- Architecture validation for **concurrency and data isolation**.

---

## ⚖ License

MIT

*Developed by [mhrgl.com](https://mhrgl.com) & Enhanced by Gemini AI.*
