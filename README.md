# Stereo Dubbing Pro - V2

An AI-powered stereo audio dubbing tool that transcribes, translates, and synthesizes voiceovers with independent channel control.

This is just a test project. It was created as a sample.

## 🚀 Features

- **Stereo Dubbing:** Process Left and Right channels independently or as a unified timeline.
- **Text-to-Dub:** Generate dubbed stereo audio directly from text input with auto-translation.
- **Dynamic AI Voices:** Access dozens of high-quality "Neural" voices for every supported language, with gender and style variations.
- **Multiple AI Models:** Choice between Whisper `Small`, `Medium`, and `Large-v3` models for local transcription.
- **Asterisk Compatibility:** One-click export for Asterisk-compatible audio (8000Hz, Mono, 16-bit PCM WAV).
- **History & Bulk Management:** Multi-select to delete past recordings or download full bundles (SRT + Audio).
- **Interactive Player:** Multi-channel waveform player with L/R/Stereo switching.
- **REST API:** Ready for external integration with one-shot endpoints.
- **Smart Launcher:** Automatically cleans up port conflicts and manages local AI models.

## 🛠 Installation

1. **Clone the repository:**
   ```bash
   git clone Stereo-Dubbing-Pro-V2
   cd stereo-dubbing-pro-v2
   ```

2. **Setup Virtual Environment:**
   ```bash
   python -m venv venv
   venv\Scripts\activate.bat
   pip install -r requirements.txt
   ```

3. **Install FFmpeg:**
   This project requires FFmpeg. Ensure it's installed and added to your system's PATH.

## 💻 Usage

### Using the Launcher (Windows)
Run `run.bat`. The launcher will:
- Automatically **terminate any lingering processes** on port 8000.
- Allow you to select your preferred AI model.
- Check and **automatically download** models to the local `models/` folder if missing.
- Start the server and **automatically open** the web interface in your default browser.

### Manual Start
```bash
python backend/web.py --model medium
```
Access the UI at `http://localhost:8000`.

## 🔌 REST API for Integration

### Documentation & Testing
- **Swagger UI:** `http://localhost:8000/docs` - Interactive testing environment.
- **ReDoc:** `http://localhost:8000/redoc` - Technical documentation.

### One-Shot Dubbing Endpoint
**Endpoint:** `POST /api/v1/dub-text`
- `text`: String (Required)
- `target_lang`: String (e.g., "tr", "en", "de")
- `sync_mode`: "independent" | "original" | "unified"
- `voice_type`: Voice ShortName or "M"/"F"
- `asterisk`: Boolean (Include 8Khz WAV)

**Example cURL:**
```bash
curl -X POST "http://localhost:8000/api/v1/dub-text" \
     -F "text=Hello world" \
     -F "target_lang=tr"
```

## 📂 Project Structure

- `backend/`: FastAPI server and audio processing logic.
- `frontend/`: Web interface (HTML, CSS, JS).
- `models/`: Local storage for Whisper AI models.
- `outputs/`: Generated audio, metadata, and SRT files.
- `static/`: External CSS and JS assets for a clean code structure.
- `download_models.py`: Helper script to pre-download all model variations.

## ⚖ License

MIT
Screenshots

<img width="1113" height="626" alt="image" src="https://github.com/user-attachments/assets/f172bf71-4550-4174-b985-24d7c84f9874" />

------------------------------------------------------------

<img width="1442" height="618" alt="image" src="https://github.com/user-attachments/assets/c68d317a-06ff-42c0-b347-a1bd3c2da2dd" />

------------------------------------------------------------

<img width="1417" height="927" alt="image" src="https://github.com/user-attachments/assets/c3dc1fc9-beb1-42ed-aed6-a3f3a760d577" />


---
*Powered by [mhrgl.com](https://mhrgl.com)*
