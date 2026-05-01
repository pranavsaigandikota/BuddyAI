const API = 'http://localhost:8001';
const WS_URL = 'ws://localhost:8001/ws';

const dot = document.getElementById('status-dot');
const statusTxt = document.getElementById('status-text');
const wave = document.getElementById('wave');
const chatBox = document.getElementById('chat-box');
const memList = document.getElementById('memory-list');
const memCount = document.getElementById('memory-count');
const micSel = document.getElementById('mic-select');
const spkSel = document.getElementById('speaker-select');
const micLevel = document.getElementById('mic-level-bar');
const refreshBtn = document.getElementById('refresh-devices');
const muteBtn = document.getElementById('mute-btn');
const testBtn = document.getElementById('test-spk-btn');

let isMuted = false;

// ── WebSocket ──────────────────────────────────────────────────────────────
function connectWS() {
    const ws = new WebSocket(WS_URL);

    ws.onopen = () => updateState('listening', 'Listening...');

    ws.onmessage = ({ data }) => {
        const msg = JSON.parse(data);
        if (msg.type === 'state') updateState(msg.state, msg.text);
        else if (msg.type === 'chat') appendMessage(msg.role, msg.content);
        else if (msg.type === 'memory_refresh') loadMemory();
        else if (msg.type === 'volume') {
            // level is already 0-100 from backend
            const percent = msg.level;
            micLevel.style.width = percent + '%';
            if (percent > 85) {
                micLevel.style.backgroundColor = 'var(--red)';
                micLevel.style.boxShadow = '0 0 8px var(--red)';
            } else if (percent > 55) {
                micLevel.style.backgroundColor = 'var(--amber)';
                micLevel.style.boxShadow = '0 0 8px var(--amber)';
            } else {
                micLevel.style.backgroundColor = 'var(--green)';
                micLevel.style.boxShadow = '0 0 8px var(--green)';
            }
        }
    };

    ws.onclose = () => {
        updateState('offline', 'Offline — retrying...');
        setTimeout(connectWS, 3000);
    };
}

// ── State ──────────────────────────────────────────────────────────────────
function updateState(state, text) {
    statusTxt.textContent = text;
    dot.className = `dot ${state}`;

    wave.className = {
        speaking: 'wave-speaking',
        thinking: 'wave-thinking',
    }[state] || 'wave-idle';
}

// ── Chat ───────────────────────────────────────────────────────────────────
function appendMessage(role, content) {
    // Remove welcome message on first real message
    const welcome = chatBox.querySelector('.chat-welcome');
    if (welcome) welcome.remove();

    const wrap = document.createElement('div');
    wrap.className = `msg ${role}`;
    wrap.innerHTML = `
        <div class="meta">${role === 'user' ? 'You' : 'Buddy'}</div>
        <div class="bubble">${escapeHtml(content)}</div>
    `;
    chatBox.appendChild(wrap);
    chatBox.scrollTop = chatBox.scrollHeight;
}

function escapeHtml(str) {
    return str
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/\n/g, '<br>');
}

// ── Devices ────────────────────────────────────────────────────────────────
async function loadDevices() {
    try {
        const { mics, speakers, active_mic, active_speaker } = await fetch(`${API}/api/devices`).then(r => r.json());

        micSel.innerHTML = mics.map(m =>
            `<option value="${m.id}" ${m.id === active_mic ? 'selected' : ''}>${m.name}</option>`
        ).join('');

        spkSel.innerHTML = speakers.map(s =>
            `<option value="${s.id}" ${s.id === active_speaker ? 'selected' : ''}>${s.name}</option>`
        ).join('');
    } catch (e) {
        console.warn('Device load failed:', e);
    }
}

async function setDevice(type, id) {
    await fetch(`${API}/api/devices`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type, id: parseInt(id) })
    }).catch(console.warn);
}

micSel.addEventListener('change', e => setDevice('mic', e.target.value));
spkSel.addEventListener('change', e => setDevice('speaker', e.target.value));
refreshBtn.addEventListener('click', loadDevices);

// ── Mute & Test ────────────────────────────────────────────────────────────
muteBtn.addEventListener('click', async () => {
    isMuted = !isMuted;
    muteBtn.classList.toggle('active', isMuted);
    muteBtn.textContent = isMuted ? 'Unmute' : 'Mute';

    await fetch(`${API}/api/mute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ muted: isMuted })
    }).catch(console.warn);
});

const mouthBtn = document.getElementById('test-mouth-btn');

mouthBtn.addEventListener('click', async () => {
    mouthBtn.disabled = true;
    mouthBtn.textContent = 'Testing...';
    await fetch(`${API}/api/test_mouth`, { method: 'POST' }).catch(console.warn);
    setTimeout(() => {
        mouthBtn.disabled = false;
        mouthBtn.textContent = 'Mouth';
    }, 2000);
});

testBtn.addEventListener('click', async () => {
    testBtn.disabled = true;
    testBtn.textContent = 'Testing...';

    await fetch(`${API}/api/test_speaker`, { method: 'POST' }).catch(console.warn);

    setTimeout(() => {
        testBtn.disabled = false;
        testBtn.textContent = 'Test';
    }, 4000); // Reset button after a few seconds
});

// ── Memory ─────────────────────────────────────────────────────────────────
async function loadMemory() {
    try {
        const facts = await fetch(`${API}/api/memory`).then(r => r.json());
        memCount.textContent = facts.length;

        if (facts.length === 0) {
            memList.innerHTML = '<li class="memory-empty">No memories yet. Start talking to Buddy!</li>';
            return;
        }

        memList.innerHTML = facts.map((fact, i) => `
            <li class="fact-item">
                <span>${escapeHtml(fact)}</span>
                <button class="delete-btn" onclick="deleteFact(${i})" title="Forget this">×</button>
            </li>
        `).join('');
    } catch (e) {
        console.warn('Memory load failed:', e);
    }
}

async function deleteFact(index) {
    await fetch(`${API}/api/memory/${index}`, { method: 'DELETE' }).catch(console.warn);
    loadMemory();
}

// ── Init ───────────────────────────────────────────────────────────────────
loadDevices();
loadMemory();
connectWS();

// Refresh devices and memory every 10 seconds in case something changes
setInterval(loadMemory, 10000);