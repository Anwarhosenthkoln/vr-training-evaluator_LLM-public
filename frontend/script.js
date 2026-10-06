const REPORTS_DIR = '../data/reports/';

let activeRequest = null;

document.addEventListener('DOMContentLoaded', () => {
    const reportSelect = document.getElementById('report-select');
    loadReport(reportSelect.value);
    reportSelect.addEventListener('change', (event) => loadReport(event.target.value));
});

async function loadReport(filename) {
    if (activeRequest) activeRequest.abort();
    activeRequest = new AbortController();

    showLoading(filename);

    try {
        const response = await fetch(REPORTS_DIR + encodeURIComponent(filename), {
            cache: 'no-store',
            signal: activeRequest.signal,
        });
        if (!response.ok) {
            throw new Error(`HTTP ${response.status} – ${REPORTS_DIR}${filename} not found. ` +
                            'Did you run "python src/evaluation/engine.py"?');
        }
        const report = await response.json();
        populateDashboard(report, filename);
    } catch (error) {
        if (error.name === 'AbortError') return;
        showError(error.message);
        console.error('Error loading report:', error);
    }
}

function populateDashboard(report, filename) {
    hideError();

    const info = report.session_info || {};
    const parts = [
        `Session: ${info.Modul || filename.replace('_report.json', '')}`,
        info.Patient ? `Patient: ${info.Patient}` : null,
        info.Datum ? `Date: ${info.Datum}` : null,
        `Duration: ${info.Dauer || 'n/a'}`,
    ].filter(Boolean);
    setText('session-info', parts.join(' | '));

    animateScore(Number(report.overall_score) || 0);

    const abcdeList = document.getElementById('abcde-list');
    abcdeList.replaceChildren();
    for (const [step, details] of Object.entries(report.abcde_breakdown || {})) {
        const passed = details.status === 'Passed';
        const li = document.createElement('li');
        li.className = passed ? 'pass' : 'fail';

        const label = document.createElement('strong');
        label.textContent = `${step.replace('_', ' – ')}: `;
        li.append(label, details.status);

        if (details.points_deducted > 0) {
            const pts = document.createElement('span');
            pts.className = 'deduction';
            pts.textContent = `−${details.points_deducted}`;
            li.append(pts);
        }
        abcdeList.append(li);
    }

    renderList('feedback-list', report.feedback, 'No feedback for this session.');
    renderList(
        'critical-errors-list',
        (report.critical_errors || []).map(e => e.replace('CRITICAL ERROR: ', '')),
        'No critical errors 🎉',
        true
    );
}

function renderList(id, items, emptyText, isErrorList = false) {
    const list = document.getElementById(id);
    list.replaceChildren();
    if (!items || items.length === 0) {
        const li = document.createElement('li');
        li.className = 'empty';
        li.textContent = emptyText;
        list.append(li);
        return;
    }
    items.forEach(text => {
        const li = document.createElement('li');
        li.textContent = text;
        list.append(li);
    });
}

const RING_COLORS = { good: '#10b981', ok: '#f59e0b', bad: '#ef4444' };

let scoreTimer = null;
function animateScore(target) {
    const el = document.getElementById('total-score');
    const ring = document.querySelector('.progress-ring__circle');
    const circumference = 2 * Math.PI * ring.r.baseVal.value;
    clearInterval(scoreTimer);

    const level = target >= 85 ? 'good' : target >= 70 ? 'ok' : 'bad';
    ring.style.stroke = RING_COLORS[level];
    ring.style.strokeDasharray = `${circumference} ${circumference}`;

    let current = 0;
    const step = Math.max(1, Math.round(target / 40));
    const render = () => {
        el.textContent = current;
        ring.style.strokeDashoffset = circumference * (1 - current / 100);
    };
    render();
    scoreTimer = setInterval(() => {
        current = Math.min(target, current + step);
        render();
        if (current >= target) clearInterval(scoreTimer);
    }, 20);
}

function showLoading(filename) {
    setText('session-info', `Loading ${filename}...`);
    setText('total-score', '--');
}

function showError(message) {
    const box = document.getElementById('load-error');
    box.textContent = message;
    box.hidden = false;
    setText('session-info', 'Could not load report');
    setText('total-score', '--');
    ['abcde-list', 'feedback-list', 'critical-errors-list'].forEach(id =>
        document.getElementById(id).replaceChildren());
}

function hideError() {
    document.getElementById('load-error').hidden = true;
}

function setText(id, text) {
    document.getElementById(id).textContent = text;
}