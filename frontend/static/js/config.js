/* ============================================================
   config.js — System configuration logic
   ============================================================ */

"use strict";

document.addEventListener("DOMContentLoaded", () => {
  loadConfig();
});

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
  setVal("cfgTransMode",    "on_close");
  setVal("cfgSampleRate",   cfg.input_sample_rate);
  setVal("cfgChannels",     cfg.input_channels);
  setVal("cfgSampleWidth",  cfg.input_sample_width);
  setVal("cfgSilence",      cfg.vad_silence_threshold_ms);
  setVal("cfgRmsThreshold", cfg.vad_rms_threshold || 300);
  setVal("cfgMinChunk",     cfg.vad_min_chunk_ms);
  setChecked("cfgDebugMode", cfg.debug_mode || false);
  setChecked("cfgIgnoreSilence", cfg.ignore_silence_timeout || false);
  setChecked("cfgSilenceFrames", cfg.send_silence_frames || false);

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
    vad_silence_threshold_ms: parseInt(getVal("cfgSilence")) || 1500,
    vad_rms_threshold:        parseInt(getVal("cfgRmsThreshold")) || 300,
    vad_min_chunk_ms:         parseInt(getVal("cfgMinChunk")) || 1000,
    debug_mode:               getChecked("cfgDebugMode"),
    ignore_silence_timeout:   getChecked("cfgIgnoreSilence"),
    send_silence_frames:      getChecked("cfgSilenceFrames"),
    
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
      initial_prompt:              getVal("cfgWhisperPrompt") || ""
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
