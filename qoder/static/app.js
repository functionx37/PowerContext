const API_BASE = window.location.origin;

// --- Tab Navigation ---
document.querySelectorAll('.nav-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById(`tab-${btn.dataset.tab}`).classList.add('active');

        if (btn.dataset.tab === 'dashboard') loadDashboard();
    });
});

// --- Status Check ---
async function checkStatus() {
    const badge = document.getElementById('statusBadge');
    const dot = badge.querySelector('.status-dot');
    const text = badge.querySelector('.status-text');
    try {
        const resp = await fetch(`${API_BASE}/api/health`);
        const data = await resp.json();
        if (data.powercontext === 'connected') {
            badge.className = 'status-badge connected';
            text.textContent = 'PowerContext 已连接';
        } else {
            badge.className = 'status-badge';
            text.textContent = 'PowerContext 未连接';
        }
        document.getElementById('pcStatus').textContent = data.powercontext === 'connected' ? '✓' : '✗';
    } catch {
        badge.className = 'status-badge error';
        text.textContent = '服务不可用';
        document.getElementById('pcStatus').textContent = '✗';
    }
}

// --- Dashboard ---
async function loadDashboard() {
    try {
        const [statsResp, historyResp] = await Promise.all([
            fetch(`${API_BASE}/api/stats`),
            fetch(`${API_BASE}/api/study/history?limit=20`)
        ]);
        const stats = await statsResp.json();
        const history = await historyResp.json();

        document.getElementById('totalSessions').textContent = stats.total_sessions || 0;
        document.getElementById('totalMinutes').textContent = stats.total_minutes || 0;
        document.getElementById('uniqueTopics').textContent = stats.unique_topics || 0;

        // Render history
        const historyEl = document.getElementById('recentHistory');
        if (history.records && history.records.length > 0) {
            historyEl.innerHTML = history.records.slice(0, 10).map(r => {
                const lines = (r.text || '').split('\n');
                const topic = lines.find(l => l.includes('学习主题:'))?.split(':').slice(1).join(':').trim() || '未知主题';
                const duration = lines.find(l => l.includes('时长:'))?.trim() || '';
                const confidence = lines.find(l => l.includes('掌握程度:'))?.trim() || '';
                return `<div class="history-item">
                    <div class="topic">${escapeHtml(topic)}</div>
                    <div class="meta">${escapeHtml(duration)} ${confidence ? '· ' + escapeHtml(confidence) : ''}</div>
                </div>`;
            }).join('');
        } else {
            historyEl.innerHTML = '<p class="empty-hint">暂无学习记录，开始你的第一次学习吧！</p>';
        }

        // Render top topics
        const topicsEl = document.getElementById('topTopics');
        if (stats.top_topics && stats.top_topics.length > 0) {
            topicsEl.innerHTML = stats.top_topics.map(([topic, count]) =>
                `<span class="topic-tag">${escapeHtml(topic)}<span class="topic-count">${count}</span></span>`
            ).join('');
        } else {
            topicsEl.innerHTML = '<p class="empty-hint">记录学习后这里会显示你的高频主题</p>';
        }
    } catch (err) {
        console.error('Failed to load dashboard:', err);
    }
}

// --- Study Form ---
const confidenceSlider = document.getElementById('confidence');
const confValue = document.getElementById('confValue');
if (confidenceSlider) {
    confidenceSlider.addEventListener('input', () => {
        confValue.textContent = confidenceSlider.value;
    });
}

const studyForm = document.getElementById('studyForm');
if (studyForm) {
    studyForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const btn = document.getElementById('submitBtn');
        const result = document.getElementById('formResult');
        btn.disabled = true;
        btn.textContent = '保存中...';
        result.classList.add('hidden');

        try {
            const resp = await fetch(`${API_BASE}/api/study/record`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    topic: document.getElementById('topic').value,
                    duration_minutes: parseInt(document.getElementById('duration').value),
                    difficulty: document.getElementById('difficulty').value,
                    confidence: parseInt(document.getElementById('confidence').value),
                    notes: document.getElementById('notes').value,
                })
            });
            const data = await resp.json();

            if (data.success) {
                result.className = 'form-result success';
                result.textContent = `✓ ${data.message}`;
                studyForm.reset();
                confValue.textContent = '5';
            } else {
                result.className = 'form-result error';
                result.textContent = `✗ 保存失败: ${data.message || '未知错误'}`;
            }
        } catch (err) {
            result.className = 'form-result error';
            result.textContent = `✗ 网络错误: ${err.message}`;
        } finally {
            result.classList.remove('hidden');
            btn.disabled = false;
            btn.textContent = '保存学习记录';
        }
    });
}

// --- Review ---
const reviewBtn = document.getElementById('reviewBtn');
if (reviewBtn) {
    reviewBtn.addEventListener('click', async () => {
        const query = document.getElementById('reviewQuery').value.trim();
        if (!query) return;

        reviewBtn.disabled = true;
        reviewBtn.textContent = '检索中...';

        try {
            const resp = await fetch(`${API_BASE}/api/study/review`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ query, limit: 10 })
            });
            const data = await resp.json();

            const resultsEl = document.getElementById('reviewResults');
            const topicsEl = document.getElementById('reviewTopics');
            const contextEl = document.getElementById('reviewContext');

            resultsEl.classList.remove('hidden');

            if (data.related_topics && data.related_topics.length > 0) {
                topicsEl.innerHTML = data.related_topics.map(t =>
                    `<div class="review-topic-item">
                        <div class="topic-name">${escapeHtml(t.topic || '未知主题')}</div>
                        <div class="topic-score">相关度: ${(t.score * 100).toFixed(1)}%</div>
                        <div class="topic-preview">${escapeHtml(t.text_preview || '')}</div>
                    </div>`
                ).join('');
            } else {
                topicsEl.innerHTML = '<p class="empty-hint">未找到相关学习记录，先记录一些学习内容吧！</p>';
            }

            contextEl.textContent = data.context_summary || '暂无上下文信息';
        } catch (err) {
            console.error('Review search failed:', err);
        } finally {
            reviewBtn.disabled = false;
            reviewBtn.textContent = '检索复习内容';
        }
    });
}

// --- Chat ---
async function sendMessage() {
    const input = document.getElementById('chatInput');
    const msg = input.value.trim();
    if (!msg) return;

    input.value = '';
    appendMessage('user', msg);

    const loadingId = appendMessage('assistant', '<span class="loading"></span> 思考中...', true);

    try {
        const resp = await fetch(`${API_BASE}/api/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: msg })
        });
        const data = await resp.json();

        let content = `<strong>${escapeHtml(data.suggestion || '')}</strong>`;

        if (data.retrieved_context && data.retrieved_context !== '暂无相关学习记录') {
            content += `<div class="context-label">📎 从 PowerContext 检索到的相关记忆:</div>`;
            content += `<div class="context-text">${escapeHtml(data.retrieved_context)}</div>`;
        }

        if (data.related_memories && data.related_memories.length > 0) {
            content += `<div class="context-label">📝 相关学习记录 (${data.related_memories.length}条):</div>`;
            data.related_memories.forEach((m, i) => {
                content += `<div class="context-text">[${i + 1}] ${escapeHtml(m)}</div>`;
            });
        }

        updateMessage(loadingId, content);
    } catch (err) {
        updateMessage(loadingId, `请求失败: ${err.message}`);
    }
}

let msgCounter = 0;
function appendMessage(role, content, isHtml = false) {
    const container = document.getElementById('chatMessages');
    const id = `msg-${++msgCounter}`;
    const avatar = role === 'user' ? '👤' : '🤖';
    const div = document.createElement('div');
    div.className = `message ${role}`;
    div.id = id;
    div.innerHTML = `
        <div class="message-avatar">${avatar}</div>
        <div class="message-content">${isHtml ? content : escapeHtml(content)}</div>
    `;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
    return id;
}

function updateMessage(id, content) {
    const el = document.getElementById(id);
    if (el) {
        const contentEl = el.querySelector('.message-content');
        contentEl.innerHTML = content;
    }
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// --- Init ---
checkStatus();
loadDashboard();
setInterval(checkStatus, 30000);
