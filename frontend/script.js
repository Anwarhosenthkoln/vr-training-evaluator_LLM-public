const REPORTS_DIR = '../data/reports/';

let activeRequest = null;

document.addEventListener('DOMContentLoaded', () => {
    const reportSelect = document.getElementById('report-select');
    loadReport(reportSelect.value);
    reportSelect.addEventListener('change', (event) => loadReport(event.target.value));

    document.getElementById('download-pdf-btn').addEventListener('click', generatePDF);
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

    window.currentReport = report;
    window.currentFilename = filename;

    const info = report.session_info || {};
    const parts = [
        `Session: ${info.Modul || filename.replace('_report.json', '')}`,
        info.Patient ? `Patient: ${info.Patient}` : null,
        info.Datum ? `Date: ${info.Datum}` : null,
        `Duration: ${info.Dauer || 'n/a'}`,
    ].filter(Boolean);
    setText('session-info', parts.join(' | '));

    animateScore(Number(report.overall_score) || 0);

    // Verdict Badge
    const verdict = document.getElementById('verdict-badge');
    verdict.textContent = `Verdict: ${report.verdict || 'Unknown'}`;
    verdict.className = `verdict-badge ${(report.verdict || '').toLowerCase()}`;

    // Coverage Card
    const cov = report.coverage || {};
    setText('cov-total', cov.total_actions || 0);
    setText('cov-eval', cov.evaluated_actions || 0);
    setText('cov-unknown', cov.unknown_actions || 0);
    setText('cov-percent-text', `${cov.coverage_percent || 0}% Covered`);
    document.getElementById('coverage-progress').style.width = `${cov.coverage_percent || 0}%`;
    
    const unknownList = document.getElementById('unknown-list');
    unknownList.replaceChildren();
    if (cov.unknown_action_list && cov.unknown_action_list.length > 0) {
        cov.unknown_action_list.forEach(a => {
            const li = document.createElement('li');
            li.textContent = a;
            unknownList.append(li);
        });
    } else {
        const li = document.createElement('li');
        li.textContent = "None. Awesome!";
        li.className = "empty text-green";
        unknownList.append(li);
    }

    // Score Breakdown
    const breakdownList = document.getElementById('score-breakdown-list');
    breakdownList.replaceChildren();
    const sb = report.score_breakdown || {};
    for (const [category, pts] of Object.entries(sb)) {
        const li = document.createElement('li');
        li.textContent = `${category.replace('_', ' ')}: -${pts} pts`;
        if (pts > 0) li.className = 'fail';
        breakdownList.append(li);
    }

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

function generatePDF() {
    if (!window.currentReport) return;
    const { jsPDF } = window.jspdf;
    const doc = new jsPDF();
    const r = window.currentReport;
    
    // Add title
    doc.setFontSize(18);
    doc.text("VR Medical Evaluation Report", 105, 20, { align: "center" });
    
    doc.setFontSize(12);
    let y = 40;
    
    doc.text(`File: ${window.currentFilename}`, 10, y); y+=10;
    doc.text(`Score: ${r.overall_score} / 100 (${r.verdict})`, 10, y); y+=20;
    
    doc.setFontSize(14);
    doc.text("Coverage:", 10, y); y+=7;
    doc.setFontSize(11);
    const c = r.coverage || {};
    doc.text(`Total Actions: ${c.total_actions}, Evaluated: ${c.evaluated_actions}, Unknown: ${c.unknown_actions} (${c.coverage_percent}%)`, 10, y); y+=15;
    
    doc.setFontSize(14);
    doc.text("Feedback:", 10, y); y+=7;
    doc.setFontSize(10);
    (r.feedback || []).forEach(f => {
        let lines = doc.splitTextToSize("- " + f, 180);
        doc.text(lines, 10, y);
        y += lines.length * 5;
        if (y > 280) { doc.addPage(); y = 20; }
    });
    y+=10;
    
    doc.setFontSize(14);
    doc.text("Critical Errors:", 10, y); y+=7;
    doc.setFontSize(10);
    if (!r.critical_errors || r.critical_errors.length === 0) {
        doc.text("None", 10, y); y+=7;
    } else {
        r.critical_errors.forEach(f => {
            let lines = doc.splitTextToSize("- " + f, 180);
            doc.text(lines, 10, y);
            y += lines.length * 5;
            if (y > 280) { doc.addPage(); y = 20; }
        });
    }
    
    doc.save(`Evaluation_${window.currentFilename.replace('.json', '')}.pdf`);
}