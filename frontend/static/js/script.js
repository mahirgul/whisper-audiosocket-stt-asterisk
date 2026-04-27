let ws, audioCtx, audioEl, sourceNode, splitter, merger, leftGain, rightGain;
let currentPage = 1, historyItems = [];

async function checkStatus() {
    try {
        const r = await fetch('/stats');
        const d = await r.json();
        document.getElementById('sCpu').innerText = d.cpu_usage + "%";
        document.getElementById('sRam').innerText = d.ram_usage_gb + " / " + d.ram_total_gb + " GB";
        
        let taskText = d.current_task || "Idle";
        if (d.status !== "loading" && taskText === "Starting...") {
            taskText = "Idle";
        }
        document.getElementById('sTask').innerText = taskText;
        document.getElementById('modelOverlay').style.display = (d.status === "loading") ? 'flex' : 'none';

        // UI Logic for refresh safety:
        // Keep setupArea visible so user can keep uploading
        const setup = document.getElementById('setupArea');
        const player = document.getElementById('playerCard');
        const activeTasks = d.active_tasks || [];
        
        setup.style.display = 'block'; 

        // If a player is active, we might want to keep it, but setup stays too
        if (player.style.display === 'block') {
            // player is already visible, no need to change
        }

        renderTaskList(activeTasks, taskText);

        // Persistent Global Status Bar handling
        const gBar = document.getElementById('globalStatus');
        const gText = document.getElementById('globalStatusText');
        if (d.status === "processing") {
            gBar.style.display = 'flex';
            gText.innerText = taskText;
        } else {
            gBar.style.display = 'none';
        }
    } catch(e){}
}

function renderTaskList(tasks, currentWorkerTask) {
    const container = document.getElementById('taskList');
    if (!tasks || tasks.length === 0) {
        container.innerHTML = "";
        return;
    }

    container.innerHTML = tasks.map((t, idx) => {
        // The first task in model_manager._pending is usually the one being processed
        // We can correlate with currentWorkerTask for more detail
        const isProcessing = idx === 0; 
        const status = isProcessing ? currentWorkerTask : "In Queue";
        
        return `
            <div class="task-item">
                <div class="task-name" title="${t.label}">${t.label}</div>
                <div class="task-status">${status}</div>
            </div>
        `;
    }).join('');
}

// Stats Interval
setInterval(checkStatus, 1000);

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
    
    audioEl.pause();
    audioEl.src = url;
    audioEl.load(); 

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

        container.innerHTML = historyItems.map((item, idx) => {
            const dateObj = item.time ? new Date(item.time * 1000) : new Date();
            const timeStr = dateObj.toLocaleString();
            
            return `
            <div class="history-item" onclick="loadFromHistory(${idx}, this)">
                <input type="checkbox" class="item-checkbox" value="${item.name}" onclick="toggleSelect(event)">
                <div class="item-info">
                    <strong style="word-break:break-all; display:block; margin-bottom:2px;">${item.name}</strong>
                    <span class="time">${timeStr}</span>
                    <div style="display:flex; gap:6px; margin-top:10px;">
                        <a href="/download/${item.name}" onclick="event.stopPropagation()" class="download-link" style="padding:4px 10px;">WAV</a>
                        <a href="/history/download-zip/${item.name}" onclick="event.stopPropagation()" class="download-link" style="padding:4px 10px; border-color:#3b82f6; color:#3b82f6;">ZIP</a>
                        <span onclick="deleteFromHistory('${item.name}', event)" class="download-link" style="padding:4px 10px; color:#ef4444; border-color:#fee2e2;">DEL</span>
                    </div>
                </div>
            </div>
        `}).join('');

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
        await fetch('/delete-multiple', {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(filenames)
        });
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
    const prompt = document.getElementById('uploadPrompt') ? document.getElementById('uploadPrompt').value : "";
    const translate = document.getElementById('translateToEn') && document.getElementById('translateToEn').checked;
    
    handleProcessing('/transcribe', { 
        file, 
        initial_prompt: prompt,
        task: translate ? "translate" : "transcribe"
    });
}

async function handleProcessing(endpoint, payload) {
    document.getElementById('setupArea').style.display = 'block'; // Keep visible
    document.getElementById('resultsGrid').style.display = 'none';
    document.getElementById('playerCard').style.display = 'none';
    document.getElementById('boxOL').innerText = "...";
    document.getElementById('boxOR').innerText = "...";

    const fd = new FormData();
    for(let key in payload) fd.append(key, payload[key]);

    try {
        const res = await fetch(endpoint, { method: 'POST', body: fd });
        const data = await res.json();
        
        if(data.error || data.detail) throw new Error(data.error || data.detail);

        document.getElementById('boxOL').innerText = data.orig_l;
        document.getElementById('boxOR').innerText = data.orig_r;
        document.getElementById('resultsGrid').style.display = 'grid';

        if (data.audio_url) {
            initWavesurfer(data.audio_url + "?t=" + Date.now());
            document.getElementById('playingLabel').innerText = data.audio_url.split('/').pop();
            document.getElementById('playerCard').style.display = 'block';
            document.getElementById('btnNew').style.display = 'block';
            await loadHistory(1); 
        } else {
            document.getElementById('btnNew').style.display = 'block';
        }
    } catch(e) {
        alert("ERROR: " + e.message);
        // On error, let the user stay on the page to try again
    }
}

document.addEventListener('DOMContentLoaded', () => {
    checkStatus(); // Immediate check
    loadHistory(1);
});
