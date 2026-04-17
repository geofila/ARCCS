function checkApiKey() {
    fetch('/api/settings/check-api-key')
        .then((res) => res.json())
        .then((data) => {
            const warning = document.getElementById('apiKeyWarning');
            if (!warning) return;

            if (data.has_api_key) {
                warning.classList.add('hidden');
            } else {
                warning.classList.remove('hidden');
            }
        })
        .catch((err) => console.error('Error checking API key:', err));
}

function dismissWarning() {
    const warning = document.getElementById('apiKeyWarning');
    if (!warning) return;

    warning.classList.add('hidden');
    sessionStorage.setItem('warningDismissed', 'true');
}

document.addEventListener('DOMContentLoaded', function () {
    if (!sessionStorage.getItem('warningDismissed')) {
        checkApiKey();
    }
});

const steps = document.querySelectorAll('.step');
const stepLines = document.querySelectorAll('.step-line');
const stepContents = document.querySelectorAll('.step-content');

const regulationUploadZone = document.getElementById('regulationUploadZone');
const regulationFileInput = document.getElementById('regulationFile');
const regulationPreview = document.getElementById('regulationPreview');
const removeRegulationBtn = document.getElementById('removeRegulation');
const processRegulationBtn = document.getElementById('processRegulation');
const loadDefaultRegulationsBtn = document.getElementById('loadDefaultRegulations');
const regulationResults = document.getElementById('regulationResults');
const goToStep2Btn = document.getElementById('goToStep2');

const logsUploadZone = document.getElementById('logsUploadZone');
const logsFileInput = document.getElementById('logsFile');
const logsPreview = document.getElementById('logsPreview');
const removeLogsBtn = document.getElementById('removeLogs');
const projectIdInput = document.getElementById('projectIdInput');
const processLogsBtn = document.getElementById('processLogs');
const logsResults = document.getElementById('logsResults');
const backToStep1Btn = document.getElementById('backToStep1');
const goToStep3Btn = document.getElementById('goToStep3');

const backToStep2Btn = document.getElementById('backToStep2');
const runComplianceCheckBtn = document.getElementById('runComplianceCheck');
const loadingCard = document.getElementById('loadingCard');
const complianceResults = document.getElementById('complianceResults');
const resultsList = document.getElementById('resultsList');
const reportOutput = document.getElementById('reportOutput');
const exportResultsBtn = document.getElementById('exportResults');
const startOverBtn = document.getElementById('startOver');

const toast = document.getElementById('toast');
const toastMessage = document.getElementById('toastMessage');

let regulationFile = null;
let logsFile = null;
let regulationsLoaded = false;
let logsPrepared = false;
let currentStep = 1;
let selectedRegulationName = 'Not loaded';
let selectedLogsName = 'Not uploaded';
let selectedProjectId = 'Not selected';
let projectOverview = null;
let complianceResultsData = [];
let currentReportOutput = null;
let eventSource = null;
let regulationEventSource = null;

function showToast(message, type = 'success') {
    toast.className = 'toast show ' + type;
    toastMessage.textContent = message;

    setTimeout(() => {
        toast.classList.remove('show');
    }, 3000);
}

function formatFileSize(bytes) {
    if (!bytes) return '0 Bytes';

    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

function getFileIcon(filename) {
    const ext = filename.split('.').pop().toLowerCase();
    const icons = {
        csv: 'fa-file-csv',
        json: 'fa-file-code',
    };
    return icons[ext] || 'fa-file';
}

function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function goToStep(stepNumber) {
    steps.forEach((step, index) => {
        step.classList.remove('active', 'completed');
        if (index + 1 < stepNumber) {
            step.classList.add('completed');
        } else if (index + 1 === stepNumber) {
            step.classList.add('active');
        }
    });

    stepLines.forEach((line, index) => {
        line.classList.remove('completed');
        if (index < stepNumber - 1) {
            line.classList.add('completed');
        }
    });

    stepContents.forEach((content, index) => {
        content.classList.remove('active');
        if (index + 1 === stepNumber) {
            content.classList.add('active');
        }
    });

    currentStep = stepNumber;
}

function setupDragDrop(zone, callback) {
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach((eventName) => {
        zone.addEventListener(eventName, preventDefaults, false);
    });

    function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }

    ['dragenter', 'dragover'].forEach((eventName) => {
        zone.addEventListener(eventName, () => {
            zone.classList.add('dragover');
        }, false);
    });

    ['dragleave', 'drop'].forEach((eventName) => {
        zone.addEventListener(eventName, () => {
            zone.classList.remove('dragover');
        }, false);
    });

    zone.addEventListener('drop', (e) => {
        const files = e.dataTransfer.files;
        if (files.length > 0) {
            callback(files[0]);
        }
    }, false);
}

function updateStep2ButtonState() {
    processLogsBtn.disabled = !(logsFile && projectIdInput.value.trim());
}

function setPreview(previewEl, uploadZoneEl, file) {
    previewEl.classList.remove('hidden');
    uploadZoneEl.classList.add('hidden');

    const fileIcon = previewEl.querySelector('.file-icon');
    fileIcon.className = 'fas ' + getFileIcon(file.name) + ' file-icon';

    previewEl.querySelector('.file-name').textContent = file.name;
    previewEl.querySelector('.file-size').textContent = formatFileSize(file.size);
}

function handleRegulationFile(file) {
    regulationFile = file;
    regulationsLoaded = false;
    selectedRegulationName = file.name;
    setPreview(regulationPreview, regulationUploadZone, file);
    processRegulationBtn.disabled = false;
    regulationResults.classList.add('hidden');
    goToStep2Btn.disabled = true;
    goToStep2Btn.classList.add('btn-disabled');
    document.getElementById('summaryRegulation').textContent = selectedRegulationName;
}

function handleLogsFile(file) {
    logsFile = file;
    logsPrepared = false;
    selectedLogsName = file.name;
    setPreview(logsPreview, logsUploadZone, file);
    logsResults.classList.add('hidden');
    goToStep3Btn.disabled = true;
    goToStep3Btn.classList.add('btn-disabled');
    document.getElementById('summaryLogs').textContent = selectedLogsName;
    updateStep2ButtonState();
}

function startLogStream() {
    const logContent = document.getElementById('logContent');
    if (logContent) {
        logContent.innerHTML = '<div class="log-entry">Connecting to server...</div>';
    }

    if (eventSource) {
        eventSource.close();
    }

    eventSource = new EventSource('/stream-logs');
    eventSource.onmessage = function (event) {
        const data = JSON.parse(event.data);
        addLogEntry(data.message, data.level);
    };

    eventSource.onerror = function () {
        if (eventSource) {
            eventSource.close();
            eventSource = null;
        }
    };
}

function stopLogStream() {
    if (eventSource) {
        eventSource.close();
        eventSource = null;
    }
}

function startRegulationLogStream() {
    const logContent = document.getElementById('regulationLogContent');
    if (logContent) {
        logContent.innerHTML = '<div class="log-entry">Connecting to server...</div>';
    }

    if (regulationEventSource) {
        regulationEventSource.close();
    }

    regulationEventSource = new EventSource('/stream-logs');
    regulationEventSource.onmessage = function (event) {
        const data = JSON.parse(event.data);
        addRegulationLogEntry(data.message, data.level);
    };

    regulationEventSource.onerror = function () {
        if (regulationEventSource) {
            regulationEventSource.close();
            regulationEventSource = null;
        }
    };
}

function stopRegulationLogStream() {
    if (regulationEventSource) {
        regulationEventSource.close();
        regulationEventSource = null;
    }
}

function addRegulationLogEntry(message, level = 'info') {
    if (!message) return;

    const logContent = document.getElementById('regulationLogContent');
    if (!logContent) return;

    const entry = document.createElement('div');
    entry.className = 'log-entry ' + level;
    entry.textContent = message;
    logContent.appendChild(entry);
    logContent.scrollTop = logContent.scrollHeight;
}

function addLogEntry(message, level = 'info') {
    if (!message) return;

    const logContent = document.getElementById('logContent');
    if (!logContent) return;

    const entry = document.createElement('div');
    entry.className = 'log-entry ' + level;
    entry.textContent = message;
    logContent.appendChild(entry);
    logContent.scrollTop = logContent.scrollHeight;
}

function applyRegulationSummary(filename, features) {
    regulationsLoaded = true;
    selectedRegulationName = filename;
    document.getElementById('totalRegulations').textContent = features.total_regulations || 0;
    document.getElementById('totalCategories').textContent = (features.sections || []).length;
    document.getElementById('totalKeywords').textContent = (features.keywords || []).length;
    document.getElementById('summaryRegulation').textContent = filename;
    regulationResults.classList.remove('hidden');
    goToStep2Btn.disabled = false;
    goToStep2Btn.classList.remove('btn-disabled');
}

async function processUploadedRegulations() {
    processRegulationBtn.disabled = true;
    processRegulationBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Uploading...';
    regulationResults.classList.remove('hidden');
    startRegulationLogStream();

    try {
        const formData = new FormData();
        formData.append('file', regulationFile);

        const response = await fetch('/upload-log-regulations', {
            method: 'POST',
            body: formData,
        });

        const result = await response.json();
        stopRegulationLogStream();

        if (!result.success) {
            addRegulationLogEntry('Error: ' + (result.message || 'Failed to load regulations.'), 'error');
            showToast(result.message || 'Failed to load regulations.', 'error');
            return;
        }

        addRegulationLogEntry('Regulations ready.', 'success');
        applyRegulationSummary(result.filename || regulationFile.name, result.features || {});
        showToast('Regulations loaded successfully.', 'success');
    } catch (error) {
        stopRegulationLogStream();
        console.error('Error uploading regulations:', error);
        showToast('Error loading regulations: ' + error.message, 'error');
    } finally {
        processRegulationBtn.disabled = false;
        processRegulationBtn.innerHTML = '<i class="fas fa-cogs"></i> Use Uploaded Regulations';
    }
}

async function loadDefaultRegulations() {
    loadDefaultRegulationsBtn.disabled = true;
    loadDefaultRegulationsBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Loading...';
    processRegulationBtn.disabled = true;
    regulationResults.classList.remove('hidden');
    startRegulationLogStream();

    try {
        const response = await fetch('/load-log-regulations', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
        });

        const result = await response.json();
        stopRegulationLogStream();

        if (!result.success) {
            addRegulationLogEntry('Error: ' + (result.message || 'Failed to load default regulations.'), 'error');
            showToast(result.message || 'Failed to load default regulations.', 'error');
            return;
        }

        regulationPreview.classList.add('hidden');
        regulationUploadZone.classList.add('hidden');
        addRegulationLogEntry('Default regulations ready.', 'success');
        applyRegulationSummary(result.filename || 'extracted_regulations_CELEX.json', result.features || {});
        showToast('Default regulations loaded successfully.', 'success');
    } catch (error) {
        stopRegulationLogStream();
        console.error('Error loading default regulations:', error);
        showToast('Error loading default regulations: ' + error.message, 'error');
    } finally {
        loadDefaultRegulationsBtn.disabled = false;
        loadDefaultRegulationsBtn.innerHTML = '<i class="fas fa-database"></i> Load Default CELEX Regulations';
        processRegulationBtn.disabled = !regulationFile;
    }
}

function updateProjectOverview(data) {
    logsPrepared = true;
    projectOverview = data;
    selectedProjectId = data.selected_case_id || projectIdInput.value.trim();

    document.getElementById('selectedProjectId').textContent = data.selected_case_id || '--';
    document.getElementById('totalCasesFound').textContent = data.total_cases || 0;
    document.getElementById('projectLogRows').textContent = data.row_count || 0;
    document.getElementById('projectEventsCount').textContent = data.event_count || 0;
    document.getElementById('projectDateRange').textContent = `${data.first_date || 'N/A'} -> ${data.last_date || 'N/A'}`;
    document.getElementById('projectEventsList').textContent = (data.events_present || []).join(', ') || 'No events found';
    document.getElementById('summaryProjectId').textContent = selectedProjectId;
    document.getElementById('summaryEvents').textContent = `Events: ${(data.events_present || []).join(', ') || '--'}`;
    document.getElementById('summaryRows').textContent = `Rows: ${data.row_count || 0}`;

    logsResults.classList.remove('hidden');
    goToStep3Btn.disabled = false;
    goToStep3Btn.classList.remove('btn-disabled');
}

async function processLogsInput() {
    processLogsBtn.disabled = true;
    processLogsBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Uploading CSV...';

    try {
        const formData = new FormData();
        formData.append('file', logsFile);

        const uploadResponse = await fetch('/upload-log-csv', {
            method: 'POST',
            body: formData,
        });

        const uploadResult = await uploadResponse.json();
        if (!uploadResult.success) {
            showToast(uploadResult.message || 'Failed to upload logs CSV.', 'error');
            return;
        }

        processLogsBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Validating project ID...';

        const processResponse = await fetch('/process-log-input', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ project_id: projectIdInput.value.trim() }),
        });

        const processResult = await processResponse.json();
        if (!processResult.success) {
            showToast(processResult.message || 'Failed to prepare logs input.', 'error');
            return;
        }

        selectedLogsName = uploadResult.filename || logsFile.name;
        document.getElementById('summaryLogs').textContent = selectedLogsName;
        updateProjectOverview(processResult.data || {});
        showToast('Logs CSV and project ID validated successfully.', 'success');
    } catch (error) {
        console.error('Error processing logs input:', error);
        showToast('Error processing logs input: ' + error.message, 'error');
    } finally {
        processLogsBtn.innerHTML = '<i class="fas fa-cogs"></i> Validate CSV and Select Project';
        updateStep2ButtonState();
    }
}

async function runComplianceCheck() {
    loadingCard.classList.remove('hidden');
    complianceResults.classList.add('hidden');
    runComplianceCheckBtn.disabled = true;
    startLogStream();

    try {
        showToast('Running log compliance analysis...', 'success');

        const response = await fetch('/run-log-compliance-check', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
        });

        const result = await response.json();
        stopLogStream();

        if (!result.success) {
            addLogEntry('Error: ' + (result.message || 'Unknown error'), 'error');
            loadingCard.classList.add('hidden');
            showToast(result.message || 'Analysis failed.', 'error');
            return;
        }

        addLogEntry('Analysis complete. Rendering results...', 'success');
        currentReportOutput = result.report_output || null;

        setTimeout(() => {
            loadingCard.classList.add('hidden');
            displayComplianceResults(result.results || [], result.summary || {}, result.overall_status, result.report_output);
        }, 600);
    } catch (error) {
        stopLogStream();
        loadingCard.classList.add('hidden');
        console.error('Error running analysis:', error);
        showToast('Error running analysis: ' + error.message, 'error');
    } finally {
        runComplianceCheckBtn.disabled = false;
    }
}

function displayComplianceResults(results, summary, overallStatus, rawOutput) {
    complianceResultsData = results || [];

    const passed = summary.passed || 0;
    const failed = summary.failed || 0;
    const warnings = summary.warnings || 0;
    const total = summary.total || 0;
    const complianceRate = typeof summary.compliance_rate === 'number'
        ? summary.compliance_rate
        : (total ? ((passed / total) * 100).toFixed(2) : 0);

    document.getElementById('passedCount').textContent = passed;
    document.getElementById('failedCount').textContent = failed;
    document.getElementById('warningCount').textContent = warnings;
    document.getElementById('totalCount').textContent = total;
    document.getElementById('overallStatus').textContent = `Overall status: ${overallStatus || '--'}`;
    document.getElementById('complianceRate').textContent = `Compliance rate: ${complianceRate}%`;

    if (!results.length) {
        resultsList.innerHTML = `
            <div class="result-item warning">
                <div class="result-icon"><i class="fas fa-exclamation"></i></div>
                <div class="result-content">
                    <div class="result-title">No results</div>
                    <div class="result-message">No compliance results were returned.</div>
                </div>
                <span class="result-badge">No Data</span>
            </div>
        `;
    } else {
        resultsList.innerHTML = results.map((result, index) => {
            let icon = 'fa-exclamation';
            let badge = 'Human Required';

            if (result.status === 'pass') {
                icon = 'fa-check';
                badge = 'Compliant';
            } else if (result.status === 'fail') {
                icon = 'fa-times';
                badge = 'Non-Compliant';
            } else if (result.status === 'info') {
                icon = 'fa-circle-info';
                badge = 'Insufficient Info';
            }

            return `
                <div class="result-item ${escapeHtml(result.status)}" data-index="${index}" onclick="showResultDetail(${index})">
                    <div class="result-icon">
                        <i class="fas ${icon}"></i>
                    </div>
                    <div class="result-content">
                        <div class="result-title">${escapeHtml(result.regulation)}</div>
                        <div class="result-message">${escapeHtml(result.message || 'No details available.')}</div>
                        ${result.evidence ? `<div class="result-evidence"><strong>Evidence:</strong> ${escapeHtml(result.evidence.length > 160 ? result.evidence.substring(0, 157) + '...' : result.evidence)}</div>` : ''}
                    </div>
                    <span class="result-badge">${badge}</span>
                    <i class="fas fa-chevron-right result-arrow"></i>
                </div>
            `;
        }).join('');
    }

    reportOutput.textContent = rawOutput ? JSON.stringify(rawOutput, null, 2) : 'No output available.';
    complianceResults.classList.remove('hidden');
    showToast('Log compliance analysis completed.', 'success');
}

function showResultDetail(index) {
    const result = complianceResultsData[index];
    if (!result) return;

    const modal = document.getElementById('resultModal');
    document.getElementById('modalTitle').textContent = 'Analysis Result Details';

    const statusBadge = document.getElementById('modalStatus');
    let badgeText = 'HUMAN REQUIRED';
    let badgeClass = 'warning';

    if (result.status === 'pass') {
        badgeText = 'COMPLIANT';
        badgeClass = 'pass';
    } else if (result.status === 'fail') {
        badgeText = 'NON-COMPLIANT';
        badgeClass = 'fail';
    } else if (result.status === 'info') {
        badgeText = 'INSUFFICIENT INFORMATION';
        badgeClass = 'info';
    }

    statusBadge.innerHTML = `<span class="status-badge ${badgeClass}">${badgeText}</span>`;
    document.getElementById('modalRegulation').textContent = result.regulation || 'Unknown Regulation';
    document.getElementById('modalRegulationId').textContent = result.regulation_id || 'N/A';

    const relevantFields = Array.isArray(result.relevant_log_fields) && result.relevant_log_fields.length
        ? result.relevant_log_fields.join(', ')
        : 'No specific fields listed';
    document.getElementById('modalDomain').textContent = relevantFields;

    const contradictionSection = document.getElementById('modalContradictionSection');
    if (result.contradiction_details && result.contradiction_details.trim()) {
        contradictionSection.style.display = 'block';
        document.getElementById('modalContradiction').textContent = result.contradiction_details;
    } else {
        contradictionSection.style.display = 'none';
    }

    const evidenceSection = document.getElementById('modalEvidenceSection');
    if (result.evidence && result.evidence.trim()) {
        evidenceSection.style.display = 'block';
        document.getElementById('modalEvidence').textContent = result.evidence;
    } else {
        evidenceSection.style.display = 'none';
    }

    document.getElementById('modalExplanation').textContent = result.explanation || 'No explanation available.';

    const confidence = Number(result.confidence_score ?? result.confidence ?? 0);
    const confidencePercent = Math.round(confidence * 100);
    document.getElementById('modalConfidenceFill').style.width = confidencePercent + '%';
    document.getElementById('modalConfidenceValue').textContent = confidencePercent + '%';

    modal.classList.remove('hidden');
}

function closeResultModal() {
    document.getElementById('resultModal').classList.add('hidden');
}

async function exportResults() {
    try {
        const response = await fetch('/export-report');
        const result = await response.json();

        if (!result.success || !result.report) {
            showToast(result.message || 'Failed to export report.', 'error');
            return;
        }

        const blob = new Blob([JSON.stringify(result.report, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = `log_compliance_report_${new Date().toISOString().split('T')[0]}.json`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);

        showToast('Report exported successfully.', 'success');
    } catch (error) {
        console.error('Export error:', error);
        showToast('Error exporting report: ' + error.message, 'error');
    }
}

function resetRegulationState() {
    regulationFile = null;
    regulationsLoaded = false;
    selectedRegulationName = 'Not loaded';
    regulationPreview.classList.add('hidden');
    regulationUploadZone.classList.remove('hidden');
    regulationResults.classList.add('hidden');
    processRegulationBtn.disabled = true;
    regulationFileInput.value = '';
    document.getElementById('summaryRegulation').textContent = 'Not loaded';
    document.getElementById('totalRegulations').textContent = '--';
    document.getElementById('totalCategories').textContent = '--';
    document.getElementById('totalKeywords').textContent = '--';
    goToStep2Btn.disabled = true;
    goToStep2Btn.classList.add('btn-disabled');
}

function resetLogsState() {
    logsFile = null;
    logsPrepared = false;
    selectedLogsName = 'Not uploaded';
    selectedProjectId = 'Not selected';
    projectOverview = null;
    logsPreview.classList.add('hidden');
    logsUploadZone.classList.remove('hidden');
    logsResults.classList.add('hidden');
    logsFileInput.value = '';
    projectIdInput.value = '';
    document.getElementById('summaryLogs').textContent = 'Not uploaded';
    document.getElementById('summaryProjectId').textContent = 'Not selected';
    document.getElementById('summaryEvents').textContent = 'Events: --';
    document.getElementById('summaryRows').textContent = 'Rows: --';
    document.getElementById('selectedProjectId').textContent = '--';
    document.getElementById('totalCasesFound').textContent = '--';
    document.getElementById('projectLogRows').textContent = '--';
    document.getElementById('projectEventsCount').textContent = '--';
    document.getElementById('projectDateRange').textContent = 'No date range yet';
    document.getElementById('projectEventsList').textContent = 'No events yet';
    goToStep3Btn.disabled = true;
    goToStep3Btn.classList.add('btn-disabled');
    updateStep2ButtonState();
}

function resetResultsState() {
    currentReportOutput = null;
    complianceResultsData = [];
    loadingCard.classList.add('hidden');
    complianceResults.classList.add('hidden');
    resultsList.innerHTML = '';
    reportOutput.textContent = 'No output yet.';
    document.getElementById('passedCount').textContent = '0';
    document.getElementById('failedCount').textContent = '0';
    document.getElementById('warningCount').textContent = '0';
    document.getElementById('totalCount').textContent = '0';
    document.getElementById('overallStatus').textContent = 'Overall status: --';
    document.getElementById('complianceRate').textContent = 'Compliance rate: --';
}

function startOver() {
    stopLogStream();
    stopRegulationLogStream();
    fetch('/reset', { method: 'POST' }).catch((err) => console.error('Reset error:', err));
    resetRegulationState();
    resetLogsState();
    resetResultsState();
    goToStep(1);
    showToast('Ready for a new log compliance run.', 'success');
}

document.addEventListener('DOMContentLoaded', () => {
    setupDragDrop(regulationUploadZone, handleRegulationFile);
    setupDragDrop(logsUploadZone, handleLogsFile);

    regulationFileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            handleRegulationFile(e.target.files[0]);
        }
    });

    logsFileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            handleLogsFile(e.target.files[0]);
        }
    });

    projectIdInput.addEventListener('input', updateStep2ButtonState);

    removeRegulationBtn.addEventListener('click', resetRegulationState);
    removeLogsBtn.addEventListener('click', resetLogsState);

    processRegulationBtn.addEventListener('click', processUploadedRegulations);
    loadDefaultRegulationsBtn.addEventListener('click', loadDefaultRegulations);
    processLogsBtn.addEventListener('click', processLogsInput);

    goToStep2Btn.addEventListener('click', () => goToStep(2));
    backToStep1Btn.addEventListener('click', () => goToStep(1));
    goToStep3Btn.addEventListener('click', () => goToStep(3));
    backToStep2Btn.addEventListener('click', () => goToStep(2));

    runComplianceCheckBtn.addEventListener('click', runComplianceCheck);
    exportResultsBtn.addEventListener('click', exportResults);
    startOverBtn.addEventListener('click', startOver);

    document.getElementById('closeModal').addEventListener('click', closeResultModal);
    document.getElementById('resultModal').addEventListener('click', (e) => {
        if (e.target.id === 'resultModal') {
            closeResultModal();
        }
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            closeResultModal();
        }
    });

    regulationUploadZone.addEventListener('click', (e) => {
        if (e.target.tagName !== 'INPUT' && !e.target.closest('label') && !e.target.closest('button')) {
            regulationFileInput.click();
        }
    });

    logsUploadZone.addEventListener('click', (e) => {
        if (e.target.tagName !== 'INPUT' && !e.target.closest('label')) {
            logsFileInput.click();
        }
    });

    resetRegulationState();
    resetLogsState();
    resetResultsState();
});
