# 🎙️ WASA — Whisper AudioSocket Asterisk (v2.5.2)

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/FastAPI-0.100%2B-009688?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/PyTorch-2.0%2B-EE4C2C?style=for-the-badge&logo=pytorch&logoColor=white" alt="PyTorch">
  <img src="https://img.shields.io/badge/Transformers-HF-FFD21E?style=for-the-badge&logo=huggingface&logoColor=black" alt="Hugging Face Transformers">
  <img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="MIT License">
  <img src="https://img.shields.io/badge/Platform-Windows%20%7C%20Linux-lightgrey?style=for-the-badge" alt="Windows & Linux">
</p>

> **🔬 EXPERIMENTAL PROJECT:** This is an experimental research and development project, created as a joint collaborative effort by **Antigravity (Advanced AI Coding Assistant)**, **DeepSeek**, and **Gemini**. It is not intended for production environments without thorough security audits and performance hardening.

An AI-powered stereo audio processing tool that transcribes telephony voice streams with independent channel control. Features real-time **Asterisk AudioSocket** integration for live transcription.

WASA features a high-performance **Multi-Process Architecture**, offloading heavy AI inference to a dedicated worker process to ensure the web UI and real-time sockets remain responsive even under heavy call volume.

---

## ✨ Key Features

*   🚀 **Multi-Process AI Pipeline:** Dedicated model worker process manages a single local Whisper or VibeVoice instance to guarantee web responsiveness under load.
*   🎙️ **Dual Whisper Engines:** Full support for both **Faster-Whisper** (highly optimized for fast inference on CPU/GPU) and **OpenAI Whisper** (standard PyTorch). Compatible with models `tiny`, `base`, `small`, `medium`, `large-v3`, and `turbo` with automatic language detection and translation capabilities.
*   👥 **Microsoft VibeVoice ASR:** *(New in v2.5.0)* Support for `microsoft/VibeVoice-ASR-HF` allowing unified single-pass transcription, speaker diarization (speaker tracking), and precise timestamp generation.
*   💾 **Immediate File Saving:** Audio files are saved to disk immediately upon hangup, even while other calls are being transcribed, ensuring zero data loss and faster UI updates.
*   📦 **Session ZIP Export:** Download complete session packages (WAV + SRT + JSON) directly from the dashboard.
*   🌐 **REST ZIP Delivery:** Automatically push full session ZIPs to any remote REST endpoint (Webhook) upon completion.
*   🧹 **Bulk History Management:** Select and delete multiple recordings or sessions at once for easier maintenance.
*   ⚡ **GPU Acceleration:** Automatic CUDA detection for 5-10x faster transcription.

---

## 📡 AudioSocket Integration

WASA acts as a high-performance TCP server for the Asterisk AudioSocket protocol:

```
  [ Asterisk PBX ] 
         │ 
         ▼  (AudioSocket TCP - Port 9092)
  [ WASA AudioSocket Server ] ──► (Saves WAV immediately on Close)
         │ 
         ▼  (Job Queue)
  [ Local AI Worker Process ]  ◄── (Isolates Whisper / VibeVoice Models)
         │
         ▼  (Generates output files)
  [ Web Dashboard / Webhook ] ──► (SRT, JSON, ZIP Export)
```

1.  **Connection:** Handles `0x01` (UUID), `0x10` (Audio), and `0x00` (Hangup) frames.
2.  **Isolation:** Every incoming connection is handled in an isolated asynchronous coroutine with its own memory buffer, ensuring no audio mixing between concurrent calls.
3.  **Buffering:** During the call, raw PCM bytes are collected and stored in RAM.
4.  **Immediate WAV Export:** Once the call hangs up, the buffered audio is converted to a WAV file immediately.
5.  **Transcription:** The dedicated Model Worker process picks up the job, performs the transcription (and optional translation), and saves the results as JSON and SRT files.

### 🔌 Asterisk Dialplan Integration Examples

You can stream audio from Asterisk to WASA using the standard `app_audiosocket` module. Every AudioSocket connection requires a valid **16-byte UUID representation** (e.g. generated via Asterisk's `UUID()` function) to identify the session.

#### 1. Direct Dialplan Application
Ideal for voice menus, voicebots, or direct voicemail transcription where the caller is piped directly to the AI socket:

```asterisk
[my-direct-stt-context]
exten => 500,1,Answer()
  same => n,Set(MY_UUID=${UUID()})
  ; Streams call audio directly to WASA AudioSocket Server
  same => n,AudioSocket(${MY_UUID},192.168.100.155:9092)
  same => n,Hangup()
```

#### 2. Spying on an Active Channel (ChanSpy + AudioHook)
To transcribe an active call between two users (e.g. PJSIP/2001 and PJSIP/3001) in the background without affecting their audio path, use Asterisk's `ChanSpy` application redirecting to an AudioSocket loop:

```asterisk
[my-chanspy-context]
; Trigger a background spy session on a target endpoint (e.g. exten spyPJSIP*2001)
exten => _spyPJSIP*,1,Answer()
  same => n,Set(TARGET_CHAN=PJSIP/${EXTEN:9})
  
  ; Quietly (q) taps both directions of the audio (B) 
  ; and routes it to the start_socket exten in audio_hook_context
  same => n,ChanSpy(${TARGET_CHAN},qB(audio_hook_context^start_socket^1))
  same => n,Hangup()

[audio_hook_context]
exten => start_socket,1,Answer()
  same => n,Set(MY_UUID=${UUID()})
  same => n,AudioSocket(${MY_UUID},192.168.100.155:9092)
  same => n,Hangup()
```
*(Make sure to replace `192.168.100.155:9092` with the actual IP address and port of your WASA server).*

---

## 📂 Project Architecture

```
C:\whisper-audiosocket-stt-asterisk
├── backend/
│   ├── routes/                     # API routers (history, configuration, models)
│   ├── audiosocket_processor.py    # Session compression and webhook delivery helper
│   ├── audiosocket_server.py       # Async TCP AudioSocket server
│   ├── downloader.py               # Model downloader worker thread
│   ├── model_manager.py            # Local model worker process management
│   ├── processor.py                # Mono/Stereo audio file decompressor
│   ├── state.py                    # App configuration state & logs
│   ├── utils.py                    # Time utility, SRT conversion, and audio segment tagging
│   └── vibevoice_helper.py         # Helper for Microsoft VibeVoice model loading & generation
├── frontend/                       # Static Dashboard Web UI
├── install.bat / install.sh        # Virtual environment and setup installer scripts
├── run.bat / run.sh                # Execution launcher scripts
└── audiosocket.json                # Live configuration settings
```

---

## ⚙️ Configuration (`audiosocket.json`)

You can manage all settings via the **Config** tab in the Web UI. Key settings include:

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `port` | integer | `9092` | TCP port for the AudioSocket server. |
| `whisper_engine` | string | `"faster"` | Engine to run locally: `faster` (Faster-Whisper), `openai` (Standard Whisper), or `vibevoice` (Microsoft VibeVoice). |
| `whisper_model` | string | `"base"` | Model size to use locally (e.g. `tiny`, `base`, `medium`, `large-v3`, `turbo`, `vibevoice-asr`). |
| `vad_silence_threshold_ms`| integer | `5000` | Duration of silence allowed before the server automatically closes the connection. |
| `ignore_silence_timeout` | boolean | `true` | If enabled, the server will not close the connection due to silence. |
| `send_silence_frames` | boolean | `true` | Sends 20ms keep-alive silence frames back to Asterisk. |
| `vad_rms_threshold` | integer | `300` | The volume level (Noise Floor) below which audio is considered silent. |
| `delivery.enabled` | boolean | `false` | Enable REST webhook delivery of session ZIP files. |

---

## 🛠️ Installation & Setup

### Requirements
*   **OS:** Windows 10/11 or Linux (Ubuntu/Debian recommended).
*   **Python:** 3.10+
*   **FFmpeg:** Required for audio encoding/decoding.
*   **NVIDIA GPU:** Recommended (with CUDA) for near real-time performance.

### Quick Start (Windows)
1. Run `install.bat` to setup the virtual environment and install dependencies.
2. Run `run.bat` to launch the application.

### Quick Start (Linux)
1. Run `chmod +x *.sh` to make the scripts executable.
2. Run `./install.sh` to setup the environment.
3. Run `./run.sh` to launch the application.

*Access the dashboard at `http://localhost:8000` once the server is running.*

---

## 🌐 GitHub Pages Website

This repository includes a landing and documentation website located in the [`docs/`](docs/index.html) directory.

To activate GitHub Pages on your repository:
1. Navigate to repository **Settings** -> **Pages**.
2. Select **Source** -> **GitHub Actions** (uses `.github/workflows/deploy-gh-pages.yml`) or select **Deploy from a branch** -> `main` / `/docs`.

---

## 🤖 Collaborative AI Development (Antigravity, DeepSeek & Gemini)

WASA is a collaborative project developed, optimized, and maintained through the joint efforts of **Antigravity**, **DeepSeek**, and **Gemini**:
*   **Antigravity:** Refactored the exit lifecycle (immediate SIGINT/Ctrl+C exit with no worker restarts), fixed multi-threading scope bugs, and designed statistical byte-swapping auto-detection to eliminate static/noise dynamically.
*   **DeepSeek:** Assisted in logical structuring and code quality audits.
*   **Gemini:** Developed initial features such as Microsoft VibeVoice integration, ignore silence timeouts, SSE streaming, and overall localization of configuration and UI.

> [!NOTE]
> This repository remains experimental, serving as a playground for real-time Asterisk AudioSocket AI integrations.

---

## ⚖️ License

Distributed under the MIT License. See [LICENSE](file:///C:/whisper-audiosocket-stt-asterisk/LICENSE) for more information.

*Developed by [mhrgl.com](https://mhrgl.com) & built collaboratively by Antigravity, DeepSeek, and Gemini.*
