'use strict';

const REPORTS_DIR = '../data/reports/';

let activeRequest = null;
let activeAbcdeKey = null;   // currently-open ABCDE panel key

// ──────────────────────────────────────────
// Boot
// ──────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    const sel = document.getElementById('report-select');
    loadReport(sel.value);
    sel.addEventListener('change', e => loadReport(e.target.value));
    document.getElementById('download-pdf-btn').addEventListener('click', generatePDF);
    document.getElementById('detail-panel-close').addEventListener('click', closeDetailPanel);
});

// ──────────────────────────────────────────
// Data loading
// ──────────────────────────────────────────
async function loadReport(filename) {
    if (activeRequest) activeRequest.abort();
    activeRequest = new AbortController();
    showLoading(filename);
    try {
        const res = await fetch(REPORTS_DIR + filename, { cache: 'no-store', signal: activeRequest.signal });
        if (!res.ok) throw new Error(`HTTP ${res.status} – ${REPORTS_DIR}${filename} not found.`);
        const report = await res.json();
        window.currentReport = report;
        window.currentFilename = filename;
        populateDashboard(report, filename);
    } catch (err) {
        if (err.name === 'AbortError') return;
        showError(err.message);
    }
}

// ──────────────────────────────────────────
// Dashboard population
// ──────────────────────────────────────────
function populateDashboard(report, filename) {
    hideError();

    // Session info bar
    const info = report.session_info || {};
    const parts = [
        `Session: ${info.Modul || filename.replace('_report.json', '')}`,
        info.Patient  ? `Patient: ${info.Patient}` : null,
        info.Datum    ? `Date: ${info.Datum}`       : null,
        `Duration: ${info.Dauer || 'n/a'}`,
        info.Entscheidung ? `Decision: ${info.Entscheidung}` : null,
    ].filter(Boolean);
    setText('session-info', parts.join('  ·  '));

    // Score ring
    animateScore(Number(report.overall_score) || 0);

    // Verdict badge
    const vb = document.getElementById('verdict-badge');
    const verdict = report.verdict || 'Unknown';
    vb.textContent = `Verdict: ${verdict}`;
    vb.className = `verdict-badge ${verdict.toLowerCase()}`;

    // Coverage
    const cov = report.coverage || {};
    setText('cov-total',   cov.total_actions    || 0);
    setText('cov-eval',    cov.evaluated_actions || 0);
    setText('cov-unknown', cov.unknown_actions   || 0);
    setText('cov-percent-text', `${cov.coverage_percent || 0}% Covered`);
    document.getElementById('coverage-progress').style.width = `${cov.coverage_percent || 0}%`;

    const unknownList = document.getElementById('unknown-list');
    unknownList.replaceChildren();
    const ua = cov.unknown_action_list || [];
    if (ua.length === 0) {
        appendLi(unknownList, 'None — all actions were recognised. 🎉', 'empty');
    } else {
        ua.forEach(a => appendLi(unknownList, a));
    }

    // Score breakdown bars
    renderBreakdownBars(report.score_breakdown || {});

    // ABCDE grid (new interactive)
    renderAbcdeGrid(report);

    // Feedback log
    const feedback = document.getElementById('feedback-list');
    feedback.replaceChildren();
    if (!report.feedback || report.feedback.length === 0) {
        appendLi(feedback, 'No feedback for this session.', 'empty');
    } else {
        report.feedback.forEach(f => {
            const li = document.createElement('li');
            li.textContent = f;
            if (f.startsWith('CRITICAL') || f.startsWith('ERROR')) li.classList.add('fail');
            feedback.append(li);
        });
    }

    // Critical errors
    const errList = document.getElementById('critical-errors-list');
    errList.replaceChildren();
    const errs = report.critical_errors || [];
    if (errs.length === 0) {
        appendLi(errList, 'No critical errors 🎉', 'empty');
    } else {
        errs.forEach(e => appendLi(errList, formatErrorCode(e)));
    }

    // Close any open detail panel when switching reports
    closeDetailPanel();
}

// ──────────────────────────────────────────
// Score breakdown bars
// ──────────────────────────────────────────
const BAR_COLORS = {
    completeness: '#3b82f6',
    timing:       '#f59e0b',
    order:        '#8b5cf6',
    critical_errors: '#ef4444',
};

function renderBreakdownBars(sb) {
    const container = document.getElementById('score-breakdown-bars');
    container.replaceChildren();
    for (const [cat, pts] of Object.entries(sb)) {
        const deduction = (typeof pts === 'object' && pts !== null) ? (pts.points_deducted || 0) : (pts || 0);
        const pct = Math.min(100, deduction);   // each deduction vs 100-pt scale
        const color = BAR_COLORS[cat] || '#9ca3af';
        const label = cat.replace('_', ' ').replace(/\b\w/g, c => c.toUpperCase());

        const wrap = document.createElement('div');
        wrap.className = 'breakdown-bar-row';
        wrap.innerHTML = `
            <div class="breakdown-label">
                <span>${label}</span>
                <span>${deduction > 0 ? `−${deduction} pts` : '✓ 0 pts'}</span>
            </div>
            <div class="breakdown-bar-bg">
                <div class="breakdown-bar-fill" style="width:${pct}%;background:${color}"></div>
            </div>`;
        container.append(wrap);
    }
}

// ──────────────────────────────────────────
// ABCDE interactive grid
// ──────────────────────────────────────────
const ABCDE_META = {
    A_Airway:      { letter: 'A', name: 'Airway',      icon: '🫁' },
    B_Breathing:   { letter: 'B', name: 'Breathing',   icon: '💨' },
    C_Circulation: { letter: 'C', name: 'Circulation', icon: '🫀' },
    D_Disability:  { letter: 'D', name: 'Disability',  icon: '🧠' },
    E_Exposure:    { letter: 'E', name: 'Exposure',     icon: '👁' },
};

function renderAbcdeGrid(report) {
    const grid = document.getElementById('abcde-grid');
    grid.replaceChildren();
    activeAbcdeKey = null;

    const breakdown = report.abcde_breakdown || {};
    const detail    = report.abcde_detail    || {};

    for (const [key, meta] of Object.entries(ABCDE_META)) {
        const bd      = breakdown[key] || {};
        const passed  = bd.status === 'Passed';
        const deducted = bd.points_deducted || 0;
        const actions  = (detail[key] || {}).actions || [];

        const total     = actions.length;
        const completed = actions.filter(a => a.result === 'Completed').length;

        const tile = document.createElement('div');
        tile.className = `abcde-tile ${passed ? 'pass' : 'fail'}`;
        tile.id = `tile-${key}`;
        tile.dataset.key = key;
        tile.setAttribute('role', 'button');
        tile.setAttribute('tabindex', '0');
        tile.setAttribute('aria-expanded', 'false');
        tile.innerHTML = `
            <div class="tile-header">
                <span class="tile-letter">${meta.letter}</span>
                <span class="tile-name">${meta.name}</span>
            </div>
            <span class="tile-badge">${passed ? '✓ Passed' : '✗ ' + bd.status}</span><br>
            <span class="tile-meta">${completed}/${total} actions done</span><br>
            ${deducted > 0 ? `<span class="tile-deduction">−${deducted} pts</span>` : '<span style="color:#10b981;font-size:.8rem;font-weight:600">No deductions</span>'}
            <span class="tile-expand-hint">▼ details</span>`;

        tile.addEventListener('click',  () => toggleDetailPanel(key, actions, meta, bd));
        tile.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') toggleDetailPanel(key, actions, meta, bd); });
        grid.append(tile);
    }
}

function toggleDetailPanel(key, actions, meta, bd) {
    if (activeAbcdeKey === key) {
        closeDetailPanel();
        return;
    }

    // Deactivate previous tile
    if (activeAbcdeKey) {
        const prev = document.getElementById(`tile-${activeAbcdeKey}`);
        if (prev) { prev.classList.remove('active'); prev.setAttribute('aria-expanded', 'false'); }
    }

    activeAbcdeKey = key;
    const tile = document.getElementById(`tile-${key}`);
    tile.classList.add('active');
    tile.setAttribute('aria-expanded', 'true');

    // Build panel
    const panel = document.getElementById('abcde-detail-panel');
    const title = document.getElementById('detail-panel-title');
    const body  = document.getElementById('detail-panel-body');

    title.textContent = `${meta.letter} — ${meta.name} ${meta.icon}`;
    body.replaceChildren();

    if (!actions || actions.length === 0) {
        const p = document.createElement('p');
        p.style.cssText = 'padding:16px;color:#6b7280;font-style:italic';
        p.textContent = 'No detailed action data available for this category.';
        body.append(p);
    } else {
        const table = document.createElement('table');
        table.className = 'action-table';
        table.innerHTML = `<thead><tr>
            <th>Action</th>
            <th>Result</th>
            <th>Time</th>
            <th>Points Deducted</th>
            <th>Note / Reason</th>
        </tr></thead>`;
        const tbody = document.createElement('tbody');

        actions.forEach(a => {
            const tr = document.createElement('tr');
            const pillClass = a.result === 'Not Required' ? 'not-required' :
                              a.result === 'Wrong Order'  ? 'wrong-order'  : a.result;
            const pts = a.points_deducted > 0 ? `−${a.points_deducted} pts` : '—';
            tr.innerHTML = `
                <td>${escHtml(a.action)}</td>
                <td><span class="result-pill ${pillClass}">${escHtml(a.result)}</span></td>
                <td>${a.time ? escHtml(a.time) : '—'}</td>
                <td style="font-weight:${a.points_deducted > 0 ? 700 : 400};color:${a.points_deducted > 0 ? '#b91c1c' : '#6b7280'}">${pts}</td>
                <td>${a.note ? `<span class="action-note">${escHtml(a.note)}</span>` : '—'}</td>`;
            tbody.append(tr);
        });
        table.append(tbody);
        body.append(table);

        // Summary row
        const total     = actions.length;
        const completed = actions.filter(a => a.result === 'Completed').length;
        const missed    = actions.filter(a => a.result === 'Missed').length;
        const late      = actions.filter(a => a.result === 'Late').length;
        const summary = document.createElement('div');
        summary.style.cssText = 'padding:10px 14px;background:#f8fafc;border-top:1px solid #e5e7eb;font-size:0.8rem;color:#4b5563;display:flex;gap:18px;flex-wrap:wrap;';
        summary.innerHTML = `
            <span>✅ Completed: <b>${completed}</b></span>
            <span>❌ Missed: <b>${missed}</b></span>
            <span>⏱ Late: <b>${late}</b></span>
            <span>Total actions in category: <b>${total}</b></span>
            <span>Points deducted: <b style="color:#b91c1c">−${bd.points_deducted || 0}</b></span>`;
        body.append(summary);
    }

    panel.classList.add('open');

    // Scroll panel into view smoothly
    setTimeout(() => panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' }), 60);
}

function closeDetailPanel() {
    if (activeAbcdeKey) {
        const tile = document.getElementById(`tile-${activeAbcdeKey}`);
        if (tile) { tile.classList.remove('active'); tile.setAttribute('aria-expanded', 'false'); }
        activeAbcdeKey = null;
    }
    const panel = document.getElementById('abcde-detail-panel');
    panel.classList.remove('open');
    document.getElementById('detail-panel-body').replaceChildren();
}

// ──────────────────────────────────────────
// Score ring animation
// ──────────────────────────────────────────
const RING_COLORS = { good: '#10b981', ok: '#f59e0b', bad: '#ef4444' };
let scoreTimer = null;

function animateScore(target) {
    const el   = document.getElementById('total-score');
    const ring = document.querySelector('.progress-ring__circle');
    const circ = 2 * Math.PI * ring.r.baseVal.value;
    clearInterval(scoreTimer);

    const level = target >= 85 ? 'good' : target >= 70 ? 'ok' : 'bad';
    ring.style.stroke = RING_COLORS[level];
    ring.style.strokeDasharray  = `${circ} ${circ}`;
    ring.style.strokeDashoffset = `${circ}`;

    let current = 0;
    const step = Math.max(1, Math.round(target / 40));
    function render() {
        el.textContent = current;
        ring.style.strokeDashoffset = circ * (1 - current / 100);
    }
    render();
    scoreTimer = setInterval(() => {
        current = Math.min(target, current + step);
        render();
        if (current >= target) clearInterval(scoreTimer);
    }, 20);
}

// ──────────────────────────────────────────
// PDF Generation — comprehensive report
// ──────────────────────────────────────────
function generatePDF() {
    if (!window.currentReport) return;
    const { jsPDF } = window.jspdf;
    const doc = new jsPDF({ orientation: 'portrait', unit: 'mm', format: 'a4' });
    const r = window.currentReport;
    const info = r.session_info || {};

    const LM = 14;     // left margin
    const PW = 182;    // printable width
    let y = 15;

    function checkPage(needed = 10) {
        if (y + needed > 278) { doc.addPage(); y = 15; }
    }
    function rule(color = '#e5e7eb') {
        doc.setDrawColor(color);
        doc.setLineWidth(0.4);
        doc.line(LM, y, LM + PW, y);
        y += 4;
    }
    function heading(txt, size = 13, bold = true) {
        checkPage(10);
        doc.setFontSize(size);
        doc.setFont('helvetica', bold ? 'bold' : 'normal');
        doc.setTextColor(30, 30, 30);
        doc.text(txt, LM, y);
        y += size > 12 ? 7 : 5;
    }
    function body(txt, indent = 0, color = '#374151') {
        const rgb = hexToRgb(color);
        doc.setTextColor(rgb.r, rgb.g, rgb.b);
        doc.setFontSize(10);
        doc.setFont('helvetica', 'normal');
        const lines = doc.splitTextToSize(txt, PW - indent);
        checkPage(lines.length * 5 + 2);
        doc.text(lines, LM + indent, y);
        y += lines.length * 5;
    }
    function kv(key, value, indent = 0) {
        doc.setFontSize(10);
        doc.setFont('helvetica', 'bold');
        doc.setTextColor(60, 60, 60);
        doc.text(`${key}:`, LM + indent, y);
        doc.setFont('helvetica', 'normal');
        doc.setTextColor(30, 30, 30);
        const lines = doc.splitTextToSize(String(value), PW - 45 - indent);
        doc.text(lines, LM + 45 + indent, y);
        y += lines.length * 5;
    }

    // ── TITLE BLOCK ──
    doc.setFillColor(30, 48, 80);
    doc.rect(0, 0, 210, 28, 'F');
    doc.setTextColor(255, 255, 255);
    doc.setFontSize(18); doc.setFont('helvetica', 'bold');
    doc.text('VR Medical Evaluation Report', 105, 12, { align: 'center' });
    doc.setFontSize(10); doc.setFont('helvetica', 'normal');
    doc.text(`Generated: ${new Date().toLocaleDateString('de-DE')}   |   VR Medical Evaluator v2.0`, 105, 20, { align: 'center' });
    y = 36;

    // ── SESSION INFO ──
    heading('Session Information', 13);
    rule();
    kv('Module',   info.Modul     || 'n/a');
    kv('Patient',  info.Patient   || 'n/a');
    kv('Date',     info.Datum     || 'n/a');
    kv('Duration', info.Dauer     || 'n/a');
    kv('Decision', info.Entscheidung || 'n/a');
    y += 4;

    // ── SCORE SUMMARY ──
    heading('Score Summary', 13);
    rule();
    kv('Overall Score', `${r.overall_score} / 100`);
    const verdict = r.verdict || '—';
    doc.setFontSize(11);
    doc.setFont('helvetica', 'bold');
    if (verdict === 'Pass') doc.setTextColor(6, 95, 70); else doc.setTextColor(153, 27, 27);
    doc.text(`Verdict: ${verdict.toUpperCase()}${verdict === 'Fail' ? '  (Pass threshold: 70 points)' : ''}`, LM + 45, y);
    doc.setTextColor(30, 30, 30);
    y += 7;
    y += 2;

    // Score breakdown table
    const sb = r.score_breakdown || {};
    const sbRows = [
        ['Completeness deductions', `-${sb.completeness?.points_deducted || 0} pts`],
        ['Timing deductions',       `-${sb.timing?.points_deducted || 0} pts`],
        ['Order violations',        `-${sb.order?.points_deducted || 0} pts`],
        ['Critical error deductions',`-${sb.critical_errors?.points_deducted || 0} pts`],
    ];
    sbRows.forEach(([k, v]) => kv(k, v));
    y += 4;

    // ── ACTION COVERAGE ──
    heading('Action Coverage', 13);
    rule();
    const cov = r.coverage || {};
    kv('Total Actions Logged', cov.total_actions || 0);
    kv('Evaluated by Engine',  `${cov.evaluated_actions || 0} (${cov.coverage_percent || 0}%)`);
    kv('Unknown / Unrecognised', cov.unknown_actions || 0);
    if ((cov.unknown_action_list || []).length > 0) {
        body(`Unknown actions: ${cov.unknown_action_list.join(', ')}`, 4, '#6b7280');
    }
    y += 4;

    // -- ABCDE BREAKDOWN --
    heading('ABCDE Category Breakdown', 13);
    rule();
    const abcdMap = {
        A_Airway:      'A - Airway',
        B_Breathing:   'B - Breathing',
        C_Circulation: 'C - Circulation',
        D_Disability:  'D - Disability',
        E_Exposure:    'E - Exposure',
    };
    const breakdown = r.abcde_breakdown || {};
    const detail    = r.abcde_detail    || {};

    for (const [key, label] of Object.entries(abcdMap)) {
        const bd = breakdown[key] || {};
        const passed = bd.status === 'Passed';
        checkPage(14);
        doc.setFontSize(11); doc.setFont('helvetica', 'bold');
        if (passed) doc.setTextColor(6, 95, 70); else doc.setTextColor(153, 27, 27);
        const deductStr = bd.points_deducted > 0 ? `  (-${bd.points_deducted} pts)` : '';
        doc.text(`${label}: ${bd.status || '-'}${deductStr}`, LM, y);
        doc.setTextColor(30, 30, 30);
        y += 5;

        const actions = (detail[key] || {}).actions || [];
        actions.forEach(a => {
            const tag = a.result === 'Completed'    ? '[OK]' :
                        a.result === 'Missed'        ? '[MISSED]' :
                        a.result === 'Late'          ? '[LATE]' :
                        a.result === 'Not Required'  ? '[N/A]' : '[?]';
            let line = `  ${tag} ${a.action}`;
            if (a.time) line += ` @ ${a.time}`;
            if (a.points_deducted > 0) line += ` [-${a.points_deducted} pts]`;
            body(line, 4, a.result === 'Missed' ? '#991b1b' : a.result === 'Late' ? '#92400e' : '#374151');
            // Only show note for problem actions
            if (a.note && (a.result === 'Missed' || a.result === 'Late')) {
                body(`    Reason: ${a.note}`, 8, '#6b7280');
            }
        });
        y += 2;
    }

    // -- FURTHER DIAGNOSTICS --
    heading('Further Diagnostics', 13);
    rule();
    const fd = r.further_diagnostics || {};
    for (const [name, val] of Object.entries(fd)) {
        const pts = val.points_deducted > 0 ? `  [-${val.points_deducted} pts]` : '';
        body(`${name}: ${val.status || '-'}${pts}`);
    }
    y += 4;

    // ── FEEDBACK LOG ──
    checkPage(20);
    heading('Feedback Log', 13);
    rule();
    (r.feedback || []).forEach((f, i) => {
        body(`${i + 1}. ${f}`, 0, f.startsWith('CRITICAL') || f.startsWith('ERROR') ? '#991b1b' : '#374151');
    });
    if ((r.feedback || []).length === 0) body('No feedback recorded.');
    y += 4;

    // -- CRITICAL ERRORS --
    checkPage(20);
    heading('Critical Errors', 13);
    rule();
    const errs = r.critical_errors || [];
    if (errs.length === 0) {
        body('[OK] No critical errors recorded.', 0, '#065f46');
    } else {
        errs.forEach(e => body(`[!] ${formatErrorCode(e)}`, 0, '#991b1b'));
        y += 3;
        body('Note: Critical errors marked with safety-cap triggers result in automatic Fail regardless of total score.', 4, '#6b7280');
    }

    // ── FOOTER ──
    const pageCount = doc.getNumberOfPages();
    for (let i = 1; i <= pageCount; i++) {
        doc.setPage(i);
        doc.setFontSize(8); doc.setFont('helvetica', 'normal'); doc.setTextColor(150);
        doc.text(`VR Medical Evaluator — Confidential   |   Page ${i} of ${pageCount}`, 105, 290, { align: 'center' });
    }

    doc.save(`Evaluation_${(window.currentFilename || 'report').replace('.json', '')}.pdf`);
}

// ──────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────
function appendLi(parent, text, className = '') {
    const li = document.createElement('li');
    li.textContent = text;
    if (className) li.className = className;
    parent.append(li);
    return li;
}

function setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
}

function escHtml(str) {
    return String(str)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function hexToRgb(hex) {
    const m = String(hex).replace('#', '').match(/.{2}/g);
    if (!m) return { r: 0, g: 0, b: 0 };
    return { r: parseInt(m[0], 16), g: parseInt(m[1], 16), b: parseInt(m[2], 16) };
}

function formatErrorCode(code) {
    const MAP = {
        WRONG_MED_CATECHOLAMINE:          'Wrong medication: Catecholamine (Adrenalin/Noradrenalin on normal ward)',
        UNINDICATED_ANESTHESIA_INDUCTION: 'Unindicated anaesthesia induction (e.g. Ketamine)',
        INTUBATION_WITHOUT_CAPNOGRAPHY:   'Intubation without capnography verification (ERC 2025)',
        INTUBATION_WITHOUT_AIRWAY_CHECK:  'Intubation before explicit airway check',
        MISSED_CPR_INDICATION:            'CPR indication missed (HR<30 or apnea without CPR)',
        SHOCK_POSITION_WITHOUT_INDICATION:'Shock position placed without prior pulse/recap-time check',
        OXYGEN_WITHOUT_INDICATION:        'Oxygen given without indication (SpO2 > 96%)',
        OXYGEN_CHEST_PAIN_WITHOUT_INDICATION: 'Oxygen in chest-pain patient with SpO2 > 90%',
        SKIPPED_OXYGEN_CRITICAL_PATIENT:  'Oxygen omitted despite critical SpO2 (< 90%)',
        WRONG_DECISION_PCI:               'Wrong management decision: PCI / coronary angiography activated',
        MISSING_STEP_MONITORING:          'No monitoring equipment applied at all',
    };
    return MAP[code] || code.replace(/_/g, ' ');
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
}

function hideError() {
    document.getElementById('load-error').hidden = true;
}