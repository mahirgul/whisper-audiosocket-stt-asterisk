let ws, audioCtx, audioEl, sourceNode, splitter, merger, leftGain, rightGain;
let currentPage = 1, historyItems = [], allVoices = [];

async function updateVoiceList() {
    const lang = document.getElementById('targetLang').value;
    const group = document.getElementById('voiceGroup');
    group.innerHTML = '';
    
    if (allVoices.length === 0) {
        try {
            const r = await fetch('/voices');
            allVoices = await r.json();
        } catch(e) { return; }
    }

    const filtered = allVoices.filter(v => v.Locale.startsWith(lang));
    filtered.forEach(v => {
        const opt = document.createElement('option');
        opt.value = v.ShortName;
        opt.innerText = `${v.FriendlyName.replace('Microsoft ', '').replace(' Online (Natural)', '')} (${v.Gender})`;
        group.appendChild(opt);
    });
}

function switchTab(tab) {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    if (tab === 'file') {
        document.querySelector('.tab-btn:nth-child(1)').classList.add('active');
        document.getElementById('fileTab').classList.add('active');
    } else {
        document.querySelector('.tab-btn:nth-child(2)').classList.add('active');
        document.getElementById('textTab').classList.add('active');
    }
}

// Stats Interval
setInterval(async () => {
    try {
        const r = await fetch('/stats');
        const d = await r.json();
        document.getElementById('sCpu').innerText = d.cpu_usage + "%";
        document.getElementById('sRam').innerText = d.ram_usage_gb + " / " + d.ram_total_gb + " GB";
        document.getElementById('sTask').innerText = d.current_task || "Idle";
        document.getElementById('modelOverlay').style.display = (d.status === "loading") ? 'flex' : 'none';
    } catch(e){}
}, 1000);

function setupAudioEngine() {
    if (audioCtx) return;
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    audioEl = new Audio();
    audioEl.crossOrigin = "anonymous";
    sourceNode = audioCtx.createMediaElementSource(audioEl);
    splitter = audioCtx.createChannelSplitter(2);
    merger = audioCtx.createChannelMerger(2);
    leftGain = audioCtx.createGain(); rightGain = audioCtx.createGain();
    sourceNode.connect(splitter);
    splitter.connect(leftGain, 0); splitter.connect(rightGain, 1);
    leftGain.connect(merger, 0, 0); rightGain.connect(merger, 0, 1);
    merger.connect(audioCtx.destination);
}

function setChannel(mode) {
    if (!leftGain) return;
    document.getElementById('btnLeft').classList.remove('btn-active');
    document.getElementById('btnRight').classList.remove('btn-active');
    document.getElementById('btnBoth').classList.remove('btn-active');
    if (mode === 'L') {
        leftGain.gain.value = 1; rightGain.gain.value = 0;
        document.getElementById('btnLeft').classList.add('btn-active');
    } else if (mode === 'R') {
        leftGain.gain.value = 0; rightGain.gain.value = 1;
        document.getElementById('btnRight').classList.add('btn-active');
    } else {
        leftGain.gain.value = 1; rightGain.gain.value = 1;
        document.getElementById('btnBoth').classList.add('btn-active');
    }
}

function initWavesurfer(url) {
    setupAudioEngine();
    if (ws) ws.destroy();
    
    // Reset audio element
    audioEl.pause();
    audioEl.src = url;
    audioEl.load(); 

    // Small timeout to ensure the container is visible and has dimensions
    setTimeout(() => {
        ws = WaveSurfer.create({
            container: '#waveform',
            url: url,
            media: audioEl,
            waveColor: '#3b82f6',
            progressColor: '#60a5fa',
            height: 80,
            splitChannels: true,
            normalize: true
        });

        ws.on('ready', () => {
            console.log('WaveSurfer ready');
        });

        document.getElementById('playPause').onclick = () => {
            if (audioCtx.state === 'suspended') audioCtx.resume();
            ws.playPause();
        };
        document.getElementById('btnLeft').onclick = () => setChannel('L');
        document.getElementById('btnRight').onclick = () => setChannel('R');
        document.getElementById('btnBoth').onclick = () => setChannel('Both');
        setChannel('Both');
    }, 50);
}

async function loadHistory(page = 1) {
    try {
        currentPage = page;
        const r = await fetch(`/history?page=${page}`);
        const data = await r.json();
        historyItems = data.items;
        const container = document.getElementById('historyList');
        const bulk = document.getElementById('bulkActions');
        bulk.style.display = 'none';

        if (historyItems.length === 0) {
            container.innerHTML = '<p style="font-size:0.7rem; color:#94a3b8; text-align:center; padding:20px;">Empty</p>';
            return;
        }

        container.innerHTML = historyItems.map((item, idx) => `
            <div class="history-item" onclick="loadFromHistory(${idx}, this)">
                <input type="checkbox" class="item-checkbox" value="${item.name}" onclick="toggleSelect(event)">
                <div class="item-info">
                    <strong style="word-break:break-all; display:block; margin-bottom:2px;">${item.name}</strong>
                    <span class="time">${new Date(item.time * 1000).toLocaleString()}</span>
                    <div style="display:flex; gap:6px; margin-top:10px;">
                        <a href="/download/${item.name}" onclick="event.stopPropagation()" class="download-link" style="padding:4px 10px;">ZIP</a>
                        <span onclick="deleteFromHistory('${item.name}', event)" class="download-link" style="padding:4px 10px; color:#ef4444; border-color:#fee2e2;">DEL</span>
                    </div>
                </div>
            </div>
        `).join('');

        const pag = document.getElementById('pagination');
        pag.innerHTML = '';
        for(let i=1; i<=data.pages; i++) {
            pag.innerHTML += `<button class="page-btn ${i===page?'active':''}" onclick="loadHistory(${i})">${i}</button>`;
        }
    } catch(e) {}
}

function toggleSelect(event) {
    event.stopPropagation();
    updateBulkUI();
}

function toggleSelectAll() {
    const master = document.getElementById('selectAll');
    document.querySelectorAll('.item-checkbox').forEach(cb => cb.checked = master.checked);
    updateBulkUI();
}

function updateBulkUI() {
    const checked = document.querySelectorAll('.item-checkbox:checked');
    const bulk = document.getElementById('bulkActions');
    const count = document.getElementById('selectedCount');
    if (checked.length > 0) {
        bulk.style.display = 'flex';
        count.innerText = checked.length + " selected";
    } else {
        bulk.style.display = 'none';
    }
}

async function deleteSelected() {
    const checked = document.querySelectorAll('.item-checkbox:checked');
    if (checked.length === 0) return;
    if (!confirm(`Are you sure you want to delete ${checked.length} items?`)) return;

    const filenames = Array.from(checked).map(cb => cb.value);
    try {
        const res = await fetch('/delete-multiple', {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(filenames)
        });
        await res.json();
        loadHistory(currentPage);
        resetUI();
    } catch(e) { alert("Failed to delete items"); }
}

async function deleteFromHistory(filename, event) {
    event.stopPropagation();
    if(!confirm("Are you sure you want to delete this recording?")) return;
    try {
        await fetch(`/delete/${filename}`, { method: 'DELETE' });
        loadHistory(currentPage);
        resetUI();
    } catch(e) { alert("Failed to delete"); }
}

function loadFromHistory(idx, el) {
    const item = historyItems[idx];
    if(!item) return;
    document.querySelectorAll('.history-item').forEach(i => i.classList.remove('active'));
    el.classList.add('active');
    document.getElementById('setupArea').style.display = 'none';
    document.getElementById('playerCard').style.display = 'block';
    document.getElementById('btnNew').style.display = 'block';
    document.getElementById('playingLabel').innerText = item.name;
    if(item.meta) {
        document.getElementById('boxOL').innerText = item.meta.orig_l || "";
        document.getElementById('boxOR').innerText = item.meta.orig_r || "";
        document.getElementById('boxTL').innerText = item.meta.tran_l || "";
        document.getElementById('boxTR').innerText = item.meta.tran_r || "";
        document.getElementById('resultsGrid').style.display = 'grid';
    }
    initWavesurfer(item.url + "?t=" + Date.now());
}

function resetUI() {
    window.location.reload();
}

async function start() {
    const file = document.getElementById('f').files[0];
    if(!file) return;
    handleProcessing('/transcribe', { file });
}

async function startText() {
    const text = document.getElementById('inputText').value.trim();
    if(!text) { alert("Please enter text"); return; }
    handleProcessing('/process-text', { text });
}

async function handleProcessing(endpoint, payload) {
    const lang = document.getElementById('targetLang').value;
    const sync = document.getElementById('syncMode').value;
    const voice = document.getElementById('voiceType').value;
    const asterisk = document.getElementById('asteriskFormat').checked;
    
    document.getElementById('setupArea').style.display = 'none';
    document.getElementById('resultsGrid').style.display = 'none';
    document.getElementById('playerCard').style.display = 'none';
    document.getElementById('boxOL').innerText = "...";
    document.getElementById('boxOR').innerText = "...";
    document.getElementById('boxTL').innerText = "...";
    document.getElementById('boxTR').innerText = "...";

    const bar = document.getElementById('loadingBar');
    bar.style.display = 'block';
    bar.innerText = "Processing...";

    const fd = new FormData();
    for(let key in payload) fd.append(key, payload[key]);
    fd.append('target_lang', lang);

    try {
        const res = await fetch(endpoint, { method: 'POST', body: fd });
        const data = await res.json();
        if(data.error || data.detail) throw new Error(data.error || data.detail);

        document.getElementById('boxOL').innerText = data.orig_l;
        document.getElementById('boxOR').innerText = data.orig_r;
        document.getElementById('boxTL').innerText = data.tran_l;
        document.getElementById('boxTR').innerText = data.tran_r;
        document.getElementById('resultsGrid').style.display = 'grid';

        bar.innerText = "Generating Stereo Audio...";
        const fdSync = new FormData(); 
        fdSync.append('sync_mode', sync);
        fdSync.append('voice_type', voice);
        fdSync.append('asterisk', asterisk);
        
        const res2 = await fetch(`/synthesize/${data.job_id}`, { method: 'POST', body: fdSync });
        const data2 = await res2.json();
        
        if (data2.audio_url) {
            const finalUrl = data2.audio_url + "?t=" + Date.now();
            initWavesurfer(finalUrl);
            document.getElementById('playingLabel').innerText = data2.audio_url.split('/').pop();
            document.getElementById('playerCard').style.display = 'block';
            document.getElementById('btnNew').style.display = 'block';
            bar.style.display = 'none';
            await loadHistory(1); 
        } else {
            throw new Error(data2.detail || "Failed");
        }
    } catch(e) {
        alert("ERROR: " + e.message);
        resetUI();
        bar.style.display = 'none';
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const targetLang = document.getElementById('targetLang');
    if (targetLang) {
        targetLang.addEventListener('change', updateVoiceList);
        updateVoiceList();
    }
    loadHistory(1);
});
