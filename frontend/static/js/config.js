/* ============================================================
   config.js — System configuration logic
   ============================================================ */

"use strict";

document.addEventListener("DOMContentLoaded", () => {
  loadConfig();
});

function onEngineChange() {
  const engine = document.getElementById("engineListBox").value;
  setVal("cfgWhisperEngine", engine);
  refreshModelStatus();
}

async function refreshModelStatus() {
  const container = document.getElementById("modelItems");
  if (!container) return;
  
  const currentEngine = getVal("cfgWhisperEngine") || "faster";
  const currentModel = getVal("cfgWhisperModel");
  
  try {
    const r = await fetch("/models/list");
    const list = await r.json();

    const dr = await fetch("/models/download-status");
    const dStatus = await dr.json();
    const downloading = dStatus.downloading || [];
    const progress = dStatus.progress || {};
    
    let html = "";
    
    // Filter models based on currentEngine
    let models = list.filter(m => {
      if (currentEngine === "vibevoice") {
        return m.type === "vibevoice";
      }
      return m.type === "whisper";
    });

    const renderRow = (modelId, engine, isDownloaded, isDownloading) => {
      const isSelected = (currentModel === modelId && currentEngine === engine);
      const dot = isDownloaded ? "🟢" : (isDownloading ? "🟡" : "⚪");
      const key = `${modelId}_${engine}`;
      const prog = progress[key];
      
      let statusText = isDownloaded ? "READY" : (isDownloading ? "DOWNLOADING..." : "NOT DOWNLOADED");
      if (isDownloading && prog) {
        if (prog.status === "queued") {
          statusText = "QUEUED...";
        } else {
          statusText = `${prog.percent}% (${prog.current_mb}/${prog.total_mb} MB)`;
        }
      }
      
      const color = isDownloaded ? "var(--primary)" : (isDownloading ? "#eab308" : "var(--muted)");
      
      let actions = "";
      if (!isDownloaded && !isDownloading) {
        actions += `<button class="btn btn-sm" style="font-size:0.6rem; padding:2px 8px;" onclick="downloadModel('${modelId}', '${engine}')">DOWNLOAD</button>`;
      }
      
      const selectBtnClass = isSelected ? "btn-primary" : "btn-secondary";
      const selectBtnText = isSelected ? "SELECTED" : "SELECT";
      const disabled = !isDownloaded ? "disabled style='opacity:0.3; cursor:not-allowed;'" : "";
      
      actions += `<button class="btn btn-sm ${selectBtnClass}" style="font-size:0.6rem; padding:2px 8px; margin-left:5px;" ${disabled} onclick="selectModel('${modelId}', '${engine}')">${selectBtnText}</button>`;

      return `<div style="display:grid; grid-template-columns: 1.5fr 1fr 1.5fr; padding:10px 15px; border-bottom:1px solid var(--border); align-items:center; font-family:monospace; font-size:0.75rem; background:${isSelected ? 'rgba(59,130,246,0.05)' : 'transparent'};">
                <div style="font-weight:700;">${modelId.toUpperCase()}</div>
                <div style="display:flex; align-items:center; gap:5px; color:${color}; font-weight:700;">
                  <span>${dot}</span>
                  <span style="font-size:0.6rem; white-space:nowrap;">${statusText}</span>
                </div>
                <div style="text-align:right;">${actions}</div>
              </div>`;
    };

    models.forEach(m => {
      const isDownloaded = (currentEngine === "faster" ? m.faster : (currentEngine === "openai" ? m.openai : (currentEngine === "vibevoice" ? m.vibevoice : m.nvidia)));
      const isDownloading = downloading.includes(`${m.id}_${currentEngine}`);
      html += renderRow(m.id, currentEngine, isDownloaded, isDownloading);
    });

    if (models.length === 0) {
      html = `<div style="padding:20px; text-align:center; color:var(--muted); font-size:0.8rem;">No models found for this engine.</div>`;
    }

    container.innerHTML = html;
  } catch (e) {
    container.innerHTML = "<div style='padding:20px; color:var(--error);'>Error loading models.</div>";
  }
}

function selectModel(modelId, engine) {
  setVal("cfgWhisperModel", modelId);
  if (engine !== "nvidia") {
    setVal("cfgWhisperEngine", engine);
  }
  refreshModelStatus();
  showToast(`Selected ${modelId.toUpperCase()} (${engine.toUpperCase()})`, "success");
}

async function downloadModel(modelId, engine) {
  try {
    const r = await fetch(`/models/download/${modelId}?engine=${engine}`, { method: 'POST' });
    const res = await r.json();
    if (res.status === "started") {
      showToast(`Started downloading ${modelId} (${engine})`, "success");
    } else if (res.status === "already_downloading") {
      showToast(`Already downloading ${modelId}`, "warning");
    }
    refreshModelStatus();
  } catch (e) {
    showToast("Failed to start download", "error");
  }
}

// Update status every 5 seconds on config page
setInterval(refreshModelStatus, 5000);

async function loadConfig() {
  try {
    const r = await fetch("/audiosocket/config");
    const cfg = await r.json();
    applyConfigToForm(cfg);
  } catch (e) {
    showToast("Failed to load config", "error");
  }
}

function applyConfigToForm(cfg) {
  setVal("cfgPort",         cfg.port);
  setVal("cfgTransMode",    cfg.transcription_mode || "on_close");
  setVal("cfgSampleRate",   cfg.input_sample_rate);
  setVal("cfgChannels",     cfg.input_channels);
  setVal("cfgSampleWidth",  cfg.input_sample_width);
  setChecked("cfgUseSileroVad", cfg.use_silero_vad || false);
  setVal("cfgSileroVadThreshold", cfg.silero_vad_threshold ?? 0.5);
  setVal("cfgWebPasscode",   cfg.web_passcode || "");
  setVal("cfgSilence",      cfg.vad_silence_threshold_ms);
  setVal("cfgRmsThreshold", cfg.vad_rms_threshold || 300);
  setVal("cfgMinChunk",     cfg.vad_min_chunk_ms);
  setChecked("cfgDebugMode", cfg.debug_mode || false);
  setChecked("cfgIgnoreSilence", cfg.ignore_silence_timeout || false);
  setChecked("cfgSilenceFrames", cfg.send_silence_frames || false);

  // New configurations
  setVal("cfgBindAddress",  cfg.bind_address || "127.0.0.1");
  setVal("cfgMaxConnections", cfg.max_concurrent_connections || 10);
  setChecked("cfgEndianSwap", cfg.force_endian_swap ?? true);
  setChecked("cfgAutoRestart", cfg.auto_restart_worker ?? true);
  setVal("cfgWhisperModel", cfg.whisper_model || "medium");
  setVal("cfgWhisperEngine", cfg.whisper_engine || "faster");
  const engineSelect = document.getElementById("engineListBox");
  if (engineSelect) {
    engineSelect.value = cfg.whisper_engine || "faster";
  }
  setVal("cfgApiProvider",  cfg.api_provider || "local");
  setVal("cfgApiBaseUrl",   cfg.api_base_url || "");
  setVal("cfgApiKey",       cfg.api_key || "");
  setVal("cfgApiModelName", cfg.api_model_name || "");
  setVal("cfgLlmModelName", cfg.llm_model_name || "");
  
  // Custom added configurations
  setVal("cfgLocalDevice",  cfg.local_whisper_device || "auto");
  setVal("cfgLocalCompute", cfg.local_whisper_compute_type || "default");
  setVal("cfgWebHost",      cfg.web_host || "0.0.0.0");
  setVal("cfgWebPort",      cfg.web_port || 8000);

  toggleApiFields(cfg.api_provider || "local");

  // Advanced AI
  setVal("cfgAiNoSpeech",   cfg.ai_no_speech_threshold ?? 0.6);
  setVal("cfgAiMinGap",     cfg.ai_min_music_gap ?? 3.0);
  setVal("cfgSilenceFrameMs", cfg.silence_frame_ms ?? 20);

  // Whisper Transcription
  const w = cfg.whisper || {};
  setVal("cfgWhisperTask",      w.task ?? "transcribe");
  setVal("cfgWhisperTemp",      w.temperature ?? 0.0);
  setVal("cfgWhisperNoSpeech",  w.no_speech_threshold ?? 0.6);
  setVal("cfgWhisperLogProb",   w.logprob_threshold ?? -1.0);
  setVal("cfgWhisperComp",      w.compression_ratio_threshold ?? 2.4);
  setVal("cfgWhisperPrompt",    w.initial_prompt ?? "");
  setChecked("cfgWhisperCondition", w.condition_on_previous_text ?? true);
  setVal("cfgWhisperBeamSize",  w.beam_size ?? 5);
  setVal("cfgWhisperBestOf",    w.best_of ?? 5);
  setChecked("cfgWhisperVadFilter", w.vad_filter ?? true);
  setVal("cfgWhisperLang",      w.language ?? "");

  const d = cfg.delivery || {};
  setChecked("cfgDeliveryEnabled", d.enabled);
  setVal("cfgDeliveryUrl",     d.url);
  setVal("cfgDeliveryMethod",  d.method);
  setVal("cfgDeliveryField",   d.field_name);
  setVal("cfgDeliveryTimeout", d.timeout_s);
  setVal("cfgDeliveryExtra",
    JSON.stringify(d.extra_fields || {}, null, 2));

  toggleDeliverySection(d.enabled);
}

function gatherConfig() {
  let extraFields = {};
  try { extraFields = JSON.parse(getVal("cfgDeliveryExtra") || "{}"); } catch (_) {}

  return {
    port:                     parseInt(getVal("cfgPort")) || 9092,
    transcription_mode:       getVal("cfgTransMode") || "instant",
    input_sample_rate:        parseInt(getVal("cfgSampleRate")) || 8000,
    input_channels:           parseInt(getVal("cfgChannels")) || 1,
    input_sample_width:       parseInt(getVal("cfgSampleWidth")) || 2,
    use_silero_vad:           getChecked("cfgUseSileroVad"),
    silero_vad_threshold:     parseFloat(getVal("cfgSileroVadThreshold")) || 0.5,
    web_passcode:             getVal("cfgWebPasscode") || "",
    vad_silence_threshold_ms: parseInt(getVal("cfgSilence")) || 1500,
    vad_rms_threshold:        parseInt(getVal("cfgRmsThreshold")) || 300,
    vad_min_chunk_ms:         parseInt(getVal("cfgMinChunk")) || 1000,
    debug_mode:               getChecked("cfgDebugMode"),
    ignore_silence_timeout:   getChecked("cfgIgnoreSilence"),
    send_silence_frames:      getChecked("cfgSilenceFrames"),
    
    // New configurations
    bind_address:             getVal("cfgBindAddress") || "127.0.0.1",
    max_concurrent_connections: parseInt(getVal("cfgMaxConnections")) || 10,
    force_endian_swap:        getChecked("cfgEndianSwap"),
    auto_restart_worker:      getChecked("cfgAutoRestart"),
    whisper_model:            getVal("cfgWhisperModel") || "medium",
    whisper_engine:           getVal("cfgWhisperEngine") || "faster",
    api_provider:             getVal("cfgApiProvider") || "local",
    api_base_url:             getVal("cfgApiBaseUrl") || "",
    api_key:                  getVal("cfgApiKey") || "",
    api_model_name:           getVal("cfgApiModelName") || "",
    llm_model_name:           getVal("cfgLlmModelName") || "",

    // Custom added configurations
    local_whisper_device:       getVal("cfgLocalDevice") || "auto",
    local_whisper_compute_type: getVal("cfgLocalCompute") || "default",
    web_host:                   getVal("cfgWebHost") || "0.0.0.0",
    web_port:                   parseInt(getVal("cfgWebPort")) || 8000,
    
    // Advanced AI
    ai_no_speech_threshold:   parseFloat(getVal("cfgAiNoSpeech")) || 0.6,
    ai_min_music_gap:         parseFloat(getVal("cfgAiMinGap")) || 3.0,
    silence_frame_ms:         parseInt(getVal("cfgSilenceFrameMs")) || 20,

    // Whisper
    whisper: {
      task:                       getVal("cfgWhisperTask") || "transcribe",
      temperature:                parseFloat(getVal("cfgWhisperTemp")) || 0.0,
      no_speech_threshold:        parseFloat(getVal("cfgWhisperNoSpeech")) || 0.6,
      logprob_threshold:          parseFloat(getVal("cfgWhisperLogProb")) || -1.0,
      compression_ratio_threshold: parseFloat(getVal("cfgWhisperComp")) || 2.4,
      condition_on_previous_text:  getChecked("cfgWhisperCondition"),
      initial_prompt:              getVal("cfgWhisperPrompt") || "",
      beam_size:                   parseInt(getVal("cfgWhisperBeamSize")) || 5,
      best_of:                     parseInt(getVal("cfgWhisperBestOf")) || 5,
      vad_filter:                  getChecked("cfgWhisperVadFilter"),
      language:                    getVal("cfgWhisperLang") || ""
    },

    delivery: {
      enabled:        getChecked("cfgDeliveryEnabled"),
      url:            getVal("cfgDeliveryUrl"),
      method:         getVal("cfgDeliveryMethod") || "POST",
      field_name:     getVal("cfgDeliveryField")  || "session_zip",
      timeout_s:      parseInt(getVal("cfgDeliveryTimeout")) || 30,
      extra_fields:   extraFields,
    }
  };
}

async function saveConfig() {
  const cfg = gatherConfig();
  try {
    const r = await fetch("/audiosocket/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cfg)
    });
    if (!r.ok) throw new Error(await r.text());
    showToast("Configuration saved & server restarted", "success");
  } catch (e) {
    showToast("Save failed: " + e.message, "error");
  }
}

function toggleDeliverySection(enabled) {
  const sec = document.getElementById("deliverySection");
  const placeholder = document.getElementById("deliveryPlaceholder");
  if (sec) sec.style.display = enabled ? "block" : "none";
  if (placeholder) placeholder.style.display = enabled ? "none" : "block";
}

window.toggleApiFields = function(provider) {
  const fieldsGroup = document.getElementById("apiFieldsGroup");
  const customFields = document.getElementById("apiCustomFields");
  const modelSelectGroup = document.getElementById("apiModelSelectGroup");
  const modelSelect = document.getElementById("cfgApiModelSelect");
  const modelNameInput = document.getElementById("cfgApiModelName");
  
  if (!fieldsGroup || !customFields || !modelSelect || !modelNameInput) return;
  
  if (provider === "local") {
    fieldsGroup.style.display = "none";
    customFields.style.display = "none";
    if (modelSelectGroup) modelSelectGroup.style.display = "none";
    const customModelGroup = document.getElementById("customModelInputGroup");
    if (customModelGroup) customModelGroup.style.display = "none";
  } else {
    fieldsGroup.style.display = "block";
    if (modelSelectGroup) modelSelectGroup.style.display = "block";
    
    // Clear and populate model dropdown options
    modelSelect.innerHTML = "";
    
    let models = [];
    let showCustomModelInput = false;
    let showBaseUrlInput = false;
    
    if (provider === "nvidia") {
      models = [
        { value: "nvidia/whisper-large-v3", label: "NVIDIA Whisper Large v3 (Default)" },
        { value: "nvidia/canary-1b", label: "NVIDIA Canary 1B" },
        { value: "nvidia/parakeet-ctc-1.1b", label: "NVIDIA Parakeet CTC 1.1B" },
        { value: "nvidia/parakeet-rnnt-1.1b", label: "NVIDIA Parakeet RNNT 1.1B" }
      ];
      setVal("cfgApiBaseUrl", "https://integrate.api.nvidia.com/v1");
      setVal("cfgLlmModelName", "meta/llama-3.1-8b-instruct");
    } else if (provider === "openai") {
      models = [
        { value: "whisper-1", label: "OpenAI Whisper-1 (Default)" }
      ];
      setVal("cfgApiBaseUrl", "https://api.openai.com/v1");
      setVal("cfgLlmModelName", "gpt-4o-mini");
    } else if (provider === "groq") {
      models = [
        { value: "whisper-large-v3", label: "Groq Whisper Large v3 (Default)" },
        { value: "distil-whisper-large-v3-en", label: "Groq Distil Whisper Large v3 English" }
      ];
      setVal("cfgApiBaseUrl", "https://api.groq.com/openapi/v1");
      setVal("cfgLlmModelName", "llama3-8b-8192");
    } else if (provider === "custom") {
      showCustomModelInput = true;
      showBaseUrlInput = true;
      models = [
        { value: "custom", label: "Custom (Type below...)" }
      ];
    }
    
    models.forEach(m => {
      const opt = document.createElement("option");
      opt.value = m.value;
      opt.textContent = m.label;
      modelSelect.appendChild(opt);
    });
    
    // Set selected value in dropdown based on saved configuration model
    const savedModel = modelNameInput.value;
    if (savedModel && models.some(m => m.value === savedModel)) {
      modelSelect.value = savedModel;
    } else {
      if (provider === "custom") {
        modelSelect.value = "custom";
      } else if (models.length > 0) {
        modelSelect.value = models[0].value;
        modelNameInput.value = models[0].value;
      }
    }
    
    // Show/hide fields
    customFields.style.display = showBaseUrlInput ? "block" : "none";
    const customModelGroup = document.getElementById("customModelInputGroup");
    if (customModelGroup) {
      customModelGroup.style.display = showCustomModelInput ? "block" : "none";
    }
  }
  refreshModelStatus();
}

window.onApiModelSelectChange = function(val) {
  const modelNameInput = document.getElementById("cfgApiModelName");
  const customModelGroup = document.getElementById("customModelInputGroup");
  if (!modelNameInput) return;
  
  if (val === "custom") {
    if (customModelGroup) customModelGroup.style.display = "block";
  } else {
    modelNameInput.value = val;
    if (customModelGroup) customModelGroup.style.display = "none";
  }
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------
function getVal(id)              { return (document.getElementById(id) || {}).value; }
function setVal(id, v)           { const el = document.getElementById(id); if (el) el.value = v ?? ""; }
function getChecked(id)          { return !!(document.getElementById(id) || {}).checked; }
function setChecked(id, v)       { const el = document.getElementById(id); if (el) el.checked = !!v; }

function showToast(msg, type = "success") {
  let t = document.getElementById("toast");
  if (!t) {
    t = document.createElement("div");
    t.id = "toast";
    t.className = "toast";
    document.body.appendChild(t);
  }
  t.textContent = msg;
  t.className = `toast ${type}`;
  // Force reflow
  void t.offsetWidth;
  t.classList.add("show");
  setTimeout(() => t.classList.remove("show"), 3000);
}
