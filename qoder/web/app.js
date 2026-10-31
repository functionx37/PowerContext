// SmartStudy - Demo Mode Frontend
// This version works standalone with simulated data for the showcase site.
// The full version (in static/app.js) connects to the FastAPI backend + PowerContext.

const DEMO_MODE = true;
const API_BASE = window.location.origin;

// --- Demo Data ---
const DEMO_HISTORY = [
    { topic: '线性代数 - 矩阵乘法', duration: 45, confidence: 7, difficulty: 'medium', time: '2026-10-30' },
    { topic: '线性代数 - 特征值分解', duration: 60, confidence: 5, difficulty: 'hard', time: '2026-10-29' },
    { topic: '机器学习 - 梯度下降', duration: 90, confidence: 8, difficulty: 'hard', time: '2026-10-28' },
    { topic: '英语 - 虚拟语气', duration: 30, confidence: 6, difficulty: 'medium', time: '2026-10-27' },
    { topic: '算法 - 动态规划', duration: 120, confidence: 4, difficulty: 'hard', time: '2026-10-26' },
    { topic: '概率论 - 贝叶斯定理', duration: 50, confidence: 9, difficulty: 'easy', time: '2026-10-25' },
    { topic: '线性代数 - 向量空间', duration: 40, confidence: 7, difficulty: 'medium', time: '2026-10-24' },
    { topic: '机器学习 - 决策树', duration: 55, confidence: 6, difficulty: 'medium', time: '2026-10-23' },
    { topic: '英语 - 定语从句', duration: 25, confidence: 8, difficulty: 'easy', time: '2026-10-22' },
    { topic: '算法 - 贪心算法', duration: 65, confidence: 5, difficulty: 'hard', time: '2026-10-21' },
    { topic: '操作系统 - 进程调度', duration: 35, confidence: 7, difficulty: 'medium', time: '2026-10-20' },
    { topic: '计算机网络 - TCP/IP', duration: 45, confidence: 6, difficulty: 'medium', time: '2026-10-19' },
];

const DEMO_TOPICS = {};
DEMO_HISTORY.forEach(h => {
    const cat = h.topic.split(' - ')[0];
    DEMO_TOPICS[cat] = (DEMO_TOPICS[cat] || 0) + 1;
});

const DEMO_REVIEWS = {
    '矩阵': [
        { topic: '线性代数 - 矩阵乘法', score: 0.92, preview: '学习了矩阵乘法的基本规则，需要注意维度匹配。矩阵乘法不满足交换律，即 AB ≠ BA。' },
        { topic: '线性代数 - 特征值分解', score: 0.78, preview: '特征值分解将矩阵分解为 QΛQ⁻¹ 的形式，其中 Λ 是由特征值组成的对角矩阵。' },
        { topic: '线性代数 - 向量空间', score: 0.65, preview: '向量空间中的线性变换可以用矩阵表示，矩阵的秩决定了变换的维度。' },
    ],
    '算法': [
        { topic: '算法 - 动态规划', score: 0.95, preview: '动态规划通过将问题分解为重叠子问题来求解。关键步骤：定义状态、状态转移方程、边界条件。' },
        { topic: '算法 - 贪心算法', score: 0.82, preview: '贪心算法在每一步选择局部最优解，希望最终得到全局最优解。适用于活动选择、霍夫曼编码等问题。' },
    ],
    '机器学习': [
        { topic: '机器学习 - 梯度下降', score: 0.91, preview: '梯度下降通过沿负梯度方向迭代更新参数来最小化损失函数。学习率的选择至关重要。' },
        { topic: '机器学习 - 决策树', score: 0.85, preview: '决策树通过信息增益或基尼系数选择最优划分特征，可用于分类和回归任务。' },
    ],
    '英语': [
        { topic: '英语 - 虚拟语气', score: 0.88, preview: '虚拟语气用于表达假设、愿望或与事实相反的情况。if 从句用过去式，主句用 would/could + 动词原形。' },
        { topic: '英语 - 定语从句', score: 0.79, preview: '定语从句修饰名词或代词，由关系代词 who/whom/whose/which/that 引导。' },
    ],
};

const DEMO_CONTEXT = `## PowerContext 组装的学习上下文

[scope: smartstudy-default]
[query: 复习建议]

### 相关记忆 (按语义相似度排序)

1. [study-session] 线性代数 - 矩阵乘法
   掌握程度: 7/10 | 时长: 45分钟
   笔记: 矩阵乘法规则、维度匹配、不满足交换律

2. [study-session] 算法 - 动态规划
   掌握程度: 4/10 | 时长: 120分钟
   笔记: 状态定义、转移方程、重叠子问题

3. [study-session] 机器学习 - 梯度下降
   掌握程度: 8/10 | 时长: 90分钟
   笔记: 学习率选择、局部最优、收敛性分析

### 复习建议
- 动态规划掌握程度较低(4/10)，建议重点复习
- 矩阵相关内容已学习多次，可以做综合练习
- 英语语法部分掌握较好，保持定期回顾即可`;

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

// --- Status ---
const badge = document.getElementById('statusBadge');
badge.className = 'status-badge connected';
badge.querySelector('.status-text').textContent = DEMO_MODE ? '演示模式' : '已连接';
document.getElementById('pcStatus').textContent = '✓';

// --- Dashboard ---
function loadDashboard() {
    const totalSessions = DEMO_HISTORY.length;
    const totalMinutes = DEMO_HISTORY.reduce((s, h) => s + h.duration, 0);
    const uniqueTopics = Object.keys(DEMO_TOPICS).length;

    document.getElementById('totalSessions').textContent = totalSessions;
    document.getElementById('totalMinutes').textContent = totalMinutes;
    document.getElementById('uniqueTopics').textContent = uniqueTopics;

    // Render history
    const historyEl = document.getElementById('recentHistory');
    historyEl.innerHTML = DEMO_HISTORY.slice(0, 8).map(h =>
        `<div class="history-item">
            <div class="topic">${escapeHtml(h.topic)}</div>
            <div class="meta">时长: ${h.duration}分钟 · 掌握: ${h.confidence}/10 · ${h.time}</div>
        </div>`
    ).join('');

    // Render top topics
    const topicsEl = document.getElementById('topTopics');
    const sorted = Object.entries(DEMO_TOPICS).sort((a, b) => b[1] - a[1]);
    topicsEl.innerHTML = sorted.map(([topic, count]) =>
        `<span class="topic-tag">${escapeHtml(topic)}<span class="topic-count">${count}</span></span>`
    ).join('');
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

        const topic = document.getElementById('topic').value;
        const duration = document.getElementById('duration').value;

        await sleep(800);

        if (DEMO_MODE) {
            const newRecord = {
                topic: topic,
                duration: parseInt(duration),
                confidence: parseInt(document.getElementById('confidence').value),
                difficulty: document.getElementById('difficulty').value,
                time: new Date().toISOString().split('T')[0],
            };
            DEMO_HISTORY.unshift(newRecord);
            const cat = topic.split(' - ')[0];
            DEMO_TOPICS[cat] = (DEMO_TOPICS[cat] || 0) + 1;

            result.className = 'form-result success';
            result.textContent = `✓ 已记录学习: ${topic} (${duration}分钟) — 数据已通过 PowerContext POST /v1/memory/remember 存储`;
            result.classList.remove('hidden');
            studyForm.reset();
            confValue.textContent = '5';
        }

        btn.disabled = false;
        btn.textContent = '保存学习记录';
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

        await sleep(600);

        const resultsEl = document.getElementById('reviewResults');
        const topicsEl = document.getElementById('reviewTopics');
        const contextEl = document.getElementById('reviewContext');
        resultsEl.classList.remove('hidden');

        // Find matching demo reviews
        let matches = [];
        for (const [key, items] of Object.entries(DEMO_REVIEWS)) {
            if (query.includes(key) || key.includes(query)) {
                matches = items;
                break;
            }
        }
        if (matches.length === 0) {
            // Fallback: search in history
            matches = DEMO_HISTORY
                .filter(h => h.topic.includes(query) || query.split('').some(c => h.topic.includes(c)))
                .slice(0, 3)
                .map(h => ({
                    topic: h.topic,
                    score: 0.5 + Math.random() * 0.4,
                    preview: `学习时长 ${h.duration} 分钟，掌握程度 ${h.confidence}/10，难度 ${h.difficulty}`,
                }));
        }

        if (matches.length > 0) {
            topicsEl.innerHTML = matches.map(t =>
                `<div class="review-topic-item">
                    <div class="topic-name">${escapeHtml(t.topic)}</div>
                    <div class="topic-score">相关度: ${(t.score * 100).toFixed(1)}% (PowerContext /v1/memory/search)</div>
                    <div class="topic-preview">${escapeHtml(t.preview)}</div>
                </div>`
            ).join('');
        } else {
            topicsEl.innerHTML = '<p class="empty-hint">未找到相关学习记录</p>';
        }

        contextEl.textContent = DEMO_CONTEXT;

        reviewBtn.disabled = false;
        reviewBtn.textContent = '检索复习内容';
    });
}

// --- Chat ---
async function sendMessage() {
    const input = document.getElementById('chatInput');
    const msg = input.value.trim();
    if (!msg) return;

    input.value = '';
    appendMessage('user', msg);

    const loadingId = appendMessage('assistant', '<span class="loading"></span> 正在从 PowerContext 检索相关记忆...', true);

    await sleep(1000);

    // Generate demo response
    let response = '';
    const lowerMsg = msg.toLowerCase();

    if (lowerMsg.includes('数学') || lowerMsg.includes('线性代数') || lowerMsg.includes('矩阵')) {
        response = `根据你在 PowerContext 中的学习记录，你学过以下数学相关内容：

<strong>📊 学习概览：</strong>
• 线性代数 - 矩阵乘法（掌握 7/10，45分钟）
• 线性代数 - 特征值分解（掌握 5/10，60分钟）
• 概率论 - 贝叶斯定理（掌握 9/10，50分钟）

<strong>💡 建议：</strong>
特征值分解的掌握程度较低，建议重点复习。可以从矩阵的基本运算开始，逐步深入到特征值和特征向量的求解。`;
    } else if (lowerMsg.includes('算法') || lowerMsg.includes('编程')) {
        response = `你的 PowerContext 记忆中存储了以下算法学习内容：

<strong>📊 学习概览：</strong>
• 算法 - 动态规划（掌握 4/10，120分钟）⚠️ 需重点复习
• 算法 - 贪心算法（掌握 5/10，65分钟）
• 机器学习 - 梯度下降（掌握 8/10，90分钟）
• 机器学习 - 决策树（掌握 6/10，55分钟）

<strong>💡 建议：</strong>
动态规划是你投入时间最多但掌握程度最低的内容。建议从简单的背包问题开始，理解状态定义和转移方程的核心思想。`;
    } else if (lowerMsg.includes('英语') || lowerMsg.includes('语言')) {
        response = `根据 PowerContext 中的记录，你的英语学习情况如下：

<strong>📊 学习概览：</strong>
• 英语 - 虚拟语气（掌握 6/10，30分钟）
• 英语 - 定语从句（掌握 8/10，25分钟）

<strong>💡 建议：</strong>
定语从句掌握较好，虚拟语气还需要更多练习。建议通过造句练习来巩固虚拟语气的用法。`;
    } else {
        response = `我已从 PowerContext 中检索了你的学习记录。你共学习了 ${DEMO_HISTORY.length} 次，累计 ${DEMO_HISTORY.reduce((s, h) => s + h.duration, 0)} 分钟，涵盖 ${Object.keys(DEMO_TOPICS).length} 个主题领域。

你可以问我关于具体学科的问题，比如：
• "我学过哪些数学内容？"
• "算法方面哪些需要重点复习？"
• "我的英语学习进度如何？"

<em style="color:#64748B;font-size:12px;">↑ 此回复基于 PowerContext /v1/context/prepare 组装的上下文生成</em>`;
    }

    updateMessage(loadingId, response);
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
        el.parentElement.scrollTop = el.parentElement.scrollHeight;
    }
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

// --- Init ---
loadDashboard();
