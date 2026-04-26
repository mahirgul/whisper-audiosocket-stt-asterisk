# WASA — Technical Documentation & Usage Guide

> **⚠️ DISCLAMER:** This project is a demonstration/example for integration purposes. Hardening is required for production environments.

---

## 🏗 System Architecture

WASA (Whisper AudioSocket Asterisk) operates on a **Decoupled Multi-Process Architecture**. This ensures that the high CPU/GPU demands of AI transcription do not interfere with the real-time audio reception or the responsiveness of the Web UI.

### 1. The Core Components
*   **Web Server (FastAPI):** Handles the dashboard, API requests, and serves the static frontend.
*   **AudioSocket Server (Async TCP):** A dedicated thread running an asynchronous TCP server that listens for Asterisk connections.
*   **Model Worker (Multiprocessing):** A separate OS process that keeps the Whisper model loaded in VRAM/RAM. It communicates via an internal queue to serialize transcription tasks.

### 2. Audio Flow Logic
1.  **Reception:** Audio arrives as raw PCM (Signed Linear) via TCP.
2.  **Isolation:** Each call is handled in its own isolated `asyncio` task. Variables and buffers are local to each task, preventing any audio leakage between concurrent calls.
3.  **Buffering:** Audio is stored in RAM during the call to ensure zero disk I/O latency during live reception.
4.  **Immediate Persistence:** As soon as a connection hangs up, the memory buffer is flushed to a `.wav` file on disk. This happens *before* queuing for AI, ensuring that the file is safe and visible in the UI immediately, even if the AI worker is busy with previous tasks.
5.  **Serialized Transcription:** The Model Worker process pulls from the queue and transcribes the already-saved files one by one.

---

## ⚙️ Configuration & Live Reloading

One of WASA's strengths is its ability to adapt to configuration changes without manual restarts.

### Dynamic Settings (No Restart Needed)
These settings are read at the start of every transcription job. You can change them mid-call, and they will apply to the result once the call ends:
*   **Transcription Task:** Switch between `Transcribe` (same language) and `Translate` (to English).
*   **AI Parameters:** Temperature, Initial Prompt, and various Whisper thresholds.
*   **External Delivery:** Update your Webhook URLs or metadata fields on the fly.

### Automatic Hot-Reload (Handled by System)
When you save these settings, the AudioSocket TCP server will automatically restart its listener (taking ~1 second):
*   **Listen Port:** Changes the TCP port (e.g., from 9092 to 9093).
*   **Audio Format:** Changes to Sample Rate or bit depth.
*   **VAD Settings:** RMS/Silence thresholds.

### Manual Restart Required
*   **Whisper Model Size:** To switch from `Medium` to `Large` or `Turbo`, you must restart the entire application via `run.bat`. This is because the model is loaded into hardware memory at startup.

---

## 🎙 Voice Activity Detection (VAD)

WASA uses a sophisticated RMS-based VAD system to manage connections:
*   **RMS Threshold:** Defines the "noise floor". Anything below this is ignored as silence.
*   **Silence Threshold (ms):** If no voice is detected for this duration, the server can automatically close the connection to save resources.
*   **Ignore Silence Timeout:** A unique feature added to keep connections open indefinitely even if the speaker is silent, relying only on the Asterisk hangup signal.

---

## 🔐 Security & Concurrency

*   **Concurrency:** Python's `asyncio` manages thousands of concurrent connections. Since each connection uses local scoping for its data buffers, there is **zero risk** of audio mixing.
*   **Safety:** The server implements strict path validation to prevent Directory Traversal attacks when accessing recording history.
*   **Privacy:** All processing is done **locally**. No audio data is ever sent to external cloud providers (OpenAI, Google, etc.) unless you explicitly configure the Webhook delivery.

---

## 🛠 Troubleshooting

*   **Delay in Transcription:** Transcription starts only after the call hangs up. If the audio is long, it may take a few seconds to appear in the dashboard.
*   **GPU not used:** Ensure you have `NVIDIA Drivers` and `CUDA Toolkit` installed. The system will fallback to CPU if CUDA is not detected.
*   **Port Conflicts:** If port 8000 (Web) or 9092 (AudioSocket) is in use, the application will attempt to clear them or report an error.

---
*Developed for demonstration by [mhrgl.com](https://mhrgl.com) — Powered by Gemini AI.*
