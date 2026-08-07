// WASA GitHub Pages Interactive Application Script

document.addEventListener('DOMContentLoaded', () => {
  initDialplanCustomizer();
  initSimulator();
  initTabs();
  initSmoothScroll();
});

/* 1. Asterisk Dialplan Customizer */
function initDialplanCustomizer() {
  const ipInput = document.getElementById('ast-ip');
  const portInput = document.getElementById('ast-port');
  const chanInput = document.getElementById('ast-chan');
  
  const directCode = document.getElementById('code-direct');
  const chanspyCode = document.getElementById('code-chanspy');
  
  function updateCodeSnippets() {
    const ip = ipInput ? ipInput.value.trim() || '192.168.100.155' : '192.168.100.155';
    const port = portInput ? portInput.value.trim() || '9092' : '9092';
    const chan = chanInput ? chanInput.value.trim() || 'PJSIP/2001' : 'PJSIP/2001';
    
    if (directCode) {
      directCode.textContent = 
`[my-direct-stt-context]
exten => 500,1,Answer()
  same => n,Set(MY_UUID=\${UUID()})
  ; Streams call audio directly to WASA AudioSocket Server
  same => n,AudioSocket(\${MY_UUID},${ip}:${port})
  same => n,Hangup()`;
    }
    
    if (chanspyCode) {
      chanspyCode.textContent = 
`[my-chanspy-context]
; Taps active channel ${chan} quietly without affecting audio stream
exten => _spyPJSIP*,1,Answer()
  same => n,Set(TARGET_CHAN=${chan})
  same => n,ChanSpy(\${TARGET_CHAN},qB(audio_hook_context^start_socket^1))
  same => n,Hangup()

[audio_hook_context]
exten => start_socket,1,Answer()
  same => n,Set(MY_UUID=\${UUID()})
  same => n,AudioSocket(\${MY_UUID},${ip}:${port})
  same => n,Hangup()`;
    }
  }

  if (ipInput) ipInput.addEventListener('input', updateCodeSnippets);
  if (portInput) portInput.addEventListener('input', updateCodeSnippets);
  if (chanInput) chanInput.addEventListener('input', updateCodeSnippets);

  updateCodeSnippets();
}

/* 2. Interactive AudioSocket Telephony Simulator */
function initSimulator() {
  const startBtn = document.getElementById('sim-start-btn');
  const consoleEl = document.getElementById('sim-console');
  const waveVisualizer = document.getElementById('sim-wave');
  const statusDot = document.getElementById('sim-status-dot');
  const statusText = document.getElementById('sim-status-text');
  const engineSelect = document.getElementById('sim-engine');

  if (!startBtn || !consoleEl) return;

  let isRunning = false;

  function appendLog(text, type = 'info') {
    const now = new Date().toISOString().substring(11, 19);
    const line = document.createElement('div');
    line.className = `sim-console-line ${type}`;
    line.innerHTML = `<span class="ts">[${now}]</span> ${text}`;
    consoleEl.appendChild(line);
    consoleEl.scrollTop = consoleEl.scrollHeight;
  }

  startBtn.addEventListener('click', async () => {
    if (isRunning) return;
    isRunning = true;
    startBtn.disabled = true;
    startBtn.innerHTML = `<span>⚡ Call Active...</span>`;
    
    const selectedEngine = engineSelect ? engineSelect.value : 'vibevoice';

    consoleEl.innerHTML = '';
    appendLog(`Initializing Asterisk AudioSocket TCP Client...`, 'info');
    
    await sleep(600);
    const uuid = generateUUID();
    appendLog(`Connected to 0.0.0.0:9092. Handshake UUID Frame: <code>${uuid}</code>`, 'success');
    
    if (statusDot) statusDot.classList.add('active');
    if (statusText) statusText.textContent = 'STREAMING AUDIO (PORT 9092)';
    if (waveVisualizer) waveVisualizer.classList.add('active');

    // Simulate audio frames streaming
    await sleep(800);
    appendLog(`Streaming 8000Hz 16-bit linear PCM audio frames (0x10)`, 'info');
    await sleep(700);
    appendLog(`VAD RMS Level: 1450 (Voice Detected above threshold 300)`, 'info');
    await sleep(1000);
    appendLog(`Asterisk sent Hangup Frame (0x00). Closing Socket Connection.`, 'warn');

    if (waveVisualizer) waveVisualizer.classList.remove('active');
    if (statusText) statusText.textContent = 'SAVING WAV DISK BUFFER';

    await sleep(500);
    const filename = `call_${uuid.substring(0, 8)}.wav`;
    appendLog(`💾 Immediate WAV Export: Flushed 482,400 bytes to disk <code>/outputs/${filename}</code>`, 'success');

    if (statusText) statusText.textContent = 'AI WORKER QUEUED';
    appendLog(`Pushed ${filename} to Local AI Model Worker Queue.`, 'info');

    await sleep(1200);
    appendLog(`🤖 Worker processing job using <strong>${selectedEngine.toUpperCase()}</strong> engine...`, 'info');

    await sleep(1500);
    if (selectedEngine === 'vibevoice') {
      appendLog(`[00:00.50 -> 00:03.20] [Speaker 1]: "Hello, welcome to WASA telephony system. How can I assist you today?"`, 'speaker1');
      await sleep(800);
      appendLog(`[00:03.50 -> 00:06.80] [Speaker 2]: "Hi! I need real-time speech recognition for Asterisk audio streams."`, 'speaker2');
      await sleep(800);
      appendLog(`[00:07.10 -> 00:10.40] [Speaker 1]: "WASA supports both Faster-Whisper and Microsoft VibeVoice for instant diarization."`, 'speaker1');
    } else {
      appendLog(`[00:00.50 -> 00:03.20] "Hello, welcome to WASA telephony system. How can I assist you today?"`, 'speaker1');
      await sleep(800);
      appendLog(`[00:03.50 -> 00:06.80] "Hi! I need real-time speech recognition for Asterisk audio streams."`, 'speaker2');
    }

    await sleep(500);
    appendLog(`✅ SRT & JSON transcripts saved. Webhook delivered to REST endpoint (200 OK).`, 'success');

    if (statusDot) statusDot.classList.remove('active');
    if (statusText) statusText.textContent = 'IDLE';

    startBtn.disabled = false;
    startBtn.innerHTML = `<span>▶️ Run Telephony Test Call</span>`;
    isRunning = false;
  });
}

/* Helper functions */
function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function generateUUID() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
    const r = Math.random() * 16 | 0;
    const v = c === 'x' ? r : (r & 0x3 | 0x8);
    return v.toString(16);
  });
}

/* 3. Tab Switching */
function initTabs() {
  const tabButtons = document.querySelectorAll('.tab-btn');
  tabButtons.forEach(btn => {
    btn.addEventListener('click', () => {
      const group = btn.dataset.tabGroup;
      const target = btn.dataset.tabTarget;

      document.querySelectorAll(`.tab-btn[data-tab-group="${group}"]`).forEach(b => b.classList.remove('active'));
      document.querySelectorAll(`.tab-content[data-tab-group="${group}"]`).forEach(c => c.classList.remove('active'));

      btn.classList.add('active');
      const targetEl = document.getElementById(target);
      if (targetEl) targetEl.classList.add('active');
    });
  });
}

/* 4. Global Copy Helper */
window.copyToClipboard = function(elementId, btn) {
  const el = document.getElementById(elementId);
  if (!el) return;
  const text = el.innerText || el.textContent;
  
  navigator.clipboard.writeText(text).then(() => {
    const originalHTML = btn.innerHTML;
    btn.innerHTML = `✓ Copied!`;
    btn.style.borderColor = 'var(--emerald)';
    btn.style.color = 'var(--emerald)';
    
    setTimeout(() => {
      btn.innerHTML = originalHTML;
      btn.style.borderColor = '';
      btn.style.color = '';
    }, 2000);
  }).catch(err => {
    console.error('Failed to copy: ', err);
  });
};

/* 5. Smooth Scroll */
function initSmoothScroll() {
  document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function(e) {
      const targetId = this.getAttribute('href');
      if (targetId === '#') return;
      const targetEl = document.querySelector(targetId);
      if (targetEl) {
        e.preventDefault();
        targetEl.scrollIntoView({
          behavior: 'smooth'
        });
      }
    });
  });
}
