// ===== API Key Check =====
function checkApiKey() {
    fetch('/api/settings/check-api-key')
        .then(res => res.json())
        .then(data => {
            const warning = document.getElementById('apiKeyWarning');
            if (warning) {
                if (data.has_api_key) {
                    warning.classList.add('hidden');
                } else {
                    warning.classList.remove('hidden');
                }
            }
        })
        .catch(err => console.error('Error checking API key:', err));
}

function dismissWarning() {
    const warning = document.getElementById('apiKeyWarning');
    if (warning) {
        warning.classList.add('hidden');
        // Remember dismissal for this session
        sessionStorage.setItem('warningDismissed', 'true');
    }
}

// Check API key on page load
document.addEventListener('DOMContentLoaded', function() {
    // Only check if not dismissed in this session
    if (!sessionStorage.getItem('warningDismissed')) {
        checkApiKey();
    }
});

// ===== DOM Elements =====
const steps = document.querySelectorAll('.step');
const stepLines = document.querySelectorAll('.step-line');
const stepContents = document.querySelectorAll('.step-content');

// Step 1 Elements
const regulationUploadZone = document.getElementById('regulationUploadZone');
const regulationFileInput = document.getElementById('regulationFile');
const regulationPreview = document.getElementById('regulationPreview');
const removeRegulationBtn = document.getElementById('removeRegulation');
const processRegulationBtn = document.getElementById('processRegulation');
const regulationResults = document.getElementById('regulationResults');
const goToStep2Btn = document.getElementById('goToStep2');

// Step 2 Elements
const proposalUploadZone = document.getElementById('proposalUploadZone');
const proposalFileInput = document.getElementById('proposalFile');
const proposalPreview = document.getElementById('proposalPreview');
const removeProposalBtn = document.getElementById('removeProposal');
const processProposalBtn = document.getElementById('processProposal');
const proposalResults = document.getElementById('proposalResults');
const backToStep1Btn = document.getElementById('backToStep1');
const goToStep3Btn = document.getElementById('goToStep3');

// Step 3 Elements
const backToStep2Btn = document.getElementById('backToStep2');
const runComplianceCheckBtn = document.getElementById('runComplianceCheck');
const loadingCard = document.getElementById('loadingCard');
const complianceResults = document.getElementById('complianceResults');
const resultsList = document.getElementById('resultsList');
const exportResultsBtn = document.getElementById('exportResults');
const startOverBtn = document.getElementById('startOver');

// Toast
const toast = document.getElementById('toast');
const toastMessage = document.getElementById('toastMessage');

// ===== State =====
let regulationFile = null;
let proposalFile = null;
let currentStep = 1;

// ===== Utility Functions =====
function showToast(message, type = 'success') {
    toast.className = 'toast show ' + type;
    toastMessage.textContent = message;
    
    setTimeout(() => {
        toast.classList.remove('show');
    }, 3000);
}

function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

function getFileIcon(filename) {
    const ext = filename.split('.').pop().toLowerCase();
    const icons = {
        'pdf': 'fa-file-pdf',
        'doc': 'fa-file-word',
        'docx': 'fa-file-word',
        'txt': 'fa-file-alt',
        'json': 'fa-file-code'
    };
    return icons[ext] || 'fa-file';
}

// ===== Step Navigation =====
function goToStep(stepNumber) {
    // Update steps
    steps.forEach((step, index) => {
        step.classList.remove('active', 'completed');
        if (index + 1 < stepNumber) {
            step.classList.add('completed');
        } else if (index + 1 === stepNumber) {
            step.classList.add('active');
        }
    });
    
    // Update step lines
    stepLines.forEach((line, index) => {
        line.classList.remove('completed');
        if (index < stepNumber - 1) {
            line.classList.add('completed');
        }
    });
    
    // Update content
    stepContents.forEach((content, index) => {
        content.classList.remove('active');
        if (index + 1 === stepNumber) {
            content.classList.add('active');
        }
    });
    
    currentStep = stepNumber;
}

// ===== Drag & Drop Handlers =====
function setupDragDrop(zone, callback) {
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        zone.addEventListener(eventName, preventDefaults, false);
    });
    
    function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }
    
    ['dragenter', 'dragover'].forEach(eventName => {
        zone.addEventListener(eventName, () => {
            zone.classList.add('dragover');
        }, false);
    });
    
    ['dragleave', 'drop'].forEach(eventName => {
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

// ===== File Upload Handlers =====
function handleRegulationFile(file) {
    regulationFile = file;
    
    // Update preview
    regulationPreview.classList.remove('hidden');
    regulationUploadZone.classList.add('hidden');
    
    const fileIcon = regulationPreview.querySelector('.file-icon');
    fileIcon.className = 'fas ' + getFileIcon(file.name) + ' file-icon';
    
    regulationPreview.querySelector('.file-name').textContent = file.name;
    regulationPreview.querySelector('.file-size').textContent = formatFileSize(file.size);
    
    processRegulationBtn.disabled = false;
    
    showToast('Regulation file uploaded successfully!', 'success');
}

function handleProposalFile(file) {
    proposalFile = file;
    
    // Update preview
    proposalPreview.classList.remove('hidden');
    proposalUploadZone.classList.add('hidden');
    
    const fileIcon = proposalPreview.querySelector('.file-icon');
    fileIcon.className = 'fas ' + getFileIcon(file.name) + ' file-icon';
    
    proposalPreview.querySelector('.file-name').textContent = file.name;
    proposalPreview.querySelector('.file-size').textContent = formatFileSize(file.size);
    
    processProposalBtn.disabled = false;
    
    showToast('Proposal file uploaded successfully!', 'success');
}

// ===== Process Handlers =====
async function processRegulation() {
    // First upload the file
    processRegulationBtn.disabled = true;
    processRegulationBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Uploading...';
    
    // Disable "Continue to Step 2" button during processing
    goToStep2Btn.disabled = true;
    goToStep2Btn.classList.add('btn-disabled');
    
    // Show results card with log console early
    regulationResults.classList.remove('hidden');
    startRegulationLogStream();
    
    try {
        // Upload the file
        const formData = new FormData();
        formData.append('file', regulationFile);
        
        const uploadResponse = await fetch('/upload-regulation', {
            method: 'POST',
            body: formData
        });
        
        const uploadResult = await uploadResponse.json();
        
        if (!uploadResult.success) {
            showToast(uploadResult.message || 'Upload failed', 'error');
            processRegulationBtn.disabled = false;
            processRegulationBtn.innerHTML = '<i class="fas fa-cogs"></i> Process Document';
            stopRegulationLogStream();
            return;
        }
        
        // Now process the document
        processRegulationBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Processing with AI...';
        showToast('Processing regulation document with AI. This may take a few minutes...', 'success');
        
        const processResponse = await fetch('/process-regulation', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        });
        
        const processResult = await processResponse.json();
        
        stopRegulationLogStream();
        
        if (processResult.success) {
            addRegulationLogEntry('✅ Processing complete!', 'success');
            
            // Update UI with results
            document.getElementById('totalRegulations').textContent = processResult.features.total_regulations || 0;
            document.getElementById('totalCategories').textContent = processResult.features.categories?.length || 0;
            document.getElementById('totalKeywords').textContent = processResult.features.keywords?.length || 0;
            
            // Update summary in step 3
            document.getElementById('summaryRegulation').textContent = regulationFile.name;
            
            // Enable "Continue to Step 2" button after successful processing
            goToStep2Btn.disabled = false;
            goToStep2Btn.classList.remove('btn-disabled');
            
            showToast('Regulation document processed successfully!', 'success');
        } else {
            addRegulationLogEntry('❌ ' + (processResult.message || 'Processing failed'), 'error');
            showToast(processResult.message || 'Processing failed', 'error');
        }
        
    } catch (error) {
        stopRegulationLogStream();
        console.error('Error processing regulation:', error);
        showToast('Error processing regulation document: ' + error.message, 'error');
    }
    
    processRegulationBtn.disabled = false;
    processRegulationBtn.innerHTML = '<i class="fas fa-cogs"></i> Process Document';
}

async function processProposal() {
    processProposalBtn.disabled = true;
    processProposalBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Uploading...';
    
    try {
        // Upload the file
        const formData = new FormData();
        formData.append('file', proposalFile);
        
        const uploadResponse = await fetch('/upload-proposal', {
            method: 'POST',
            body: formData
        });
        
        const uploadResult = await uploadResponse.json();
        
        if (!uploadResult.success) {
            showToast(uploadResult.message || 'Upload failed', 'error');
            processProposalBtn.disabled = false;
            processProposalBtn.innerHTML = '<i class="fas fa-cogs"></i> Process Document';
            return;
        }
        
        // Now process the document
        processProposalBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Processing...';
        
        const processResponse = await fetch('/process-proposal', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        });
        
        const processResult = await processResponse.json();
        
        if (processResult.success) {
            // Update UI with results
            document.getElementById('proposalSections').textContent = processResult.data.sections || '--';
            document.getElementById('proposalPages').textContent = processResult.data.pages || '--';
            document.getElementById('proposalComplexity').textContent = processResult.data.complexity || 'N/A';
            
            proposalResults.classList.remove('hidden');
            
            // Update summary in step 3
            document.getElementById('summaryProposal').textContent = proposalFile.name;
            
            showToast('Proposal document processed successfully!', 'success');
        } else {
            showToast(processResult.message || 'Processing failed', 'error');
        }
        
    } catch (error) {
        console.error('Error processing proposal:', error);
        showToast('Error processing proposal document: ' + error.message, 'error');
    }
    
    processProposalBtn.disabled = false;
    processProposalBtn.innerHTML = '<i class="fas fa-cogs"></i> Process Document';
}

// ===== Log Streaming =====
let eventSource = null;
let regulationEventSource = null;

function startLogStream() {
    // Clear previous logs
    const logContent = document.getElementById('logContent');
    if (logContent) {
        logContent.innerHTML = '<div class="log-entry">Connecting to server...</div>';
    }
    
    // Close existing connection
    if (eventSource) {
        eventSource.close();
    }
    
    // Start new SSE connection
    eventSource = new EventSource('/stream-logs');
    
    eventSource.onmessage = function(event) {
        const data = JSON.parse(event.data);
        addLogEntry(data.message, data.level);
    };
    
    eventSource.onerror = function(error) {
        console.log('SSE connection closed');
        eventSource.close();
        eventSource = null;
    };
}

function stopLogStream() {
    if (eventSource) {
        eventSource.close();
        eventSource = null;
    }
}

// Regulation-specific log streaming
function startRegulationLogStream() {
    const logContent = document.getElementById('regulationLogContent');
    if (logContent) {
        logContent.innerHTML = '<div class="log-entry">Connecting to server...</div>';
    }
    
    if (regulationEventSource) {
        regulationEventSource.close();
    }
    
    regulationEventSource = new EventSource('/stream-logs');
    
    regulationEventSource.onmessage = function(event) {
        const data = JSON.parse(event.data);
        addRegulationLogEntry(data.message, data.level);
    };
    
    regulationEventSource.onerror = function(error) {
        console.log('Regulation SSE connection closed');
        regulationEventSource.close();
        regulationEventSource = null;
    };
}

function stopRegulationLogStream() {
    if (regulationEventSource) {
        regulationEventSource.close();
        regulationEventSource = null;
    }
}

function addRegulationLogEntry(message, level = 'info') {
    const logContent = document.getElementById('regulationLogContent');
    if (!logContent) return;
    
    const entry = document.createElement('div');
    entry.className = 'log-entry ' + level;
    entry.textContent = message;
    logContent.appendChild(entry);
    
    // Auto-scroll to bottom
    logContent.scrollTop = logContent.scrollHeight;
}

function addLogEntry(message, level = 'info') {
    const logContent = document.getElementById('logContent');
    if (!logContent) return;
    
    const entry = document.createElement('div');
    entry.className = 'log-entry ' + level;
    entry.textContent = message;
    logContent.appendChild(entry);
    
    // Auto-scroll to bottom
    logContent.scrollTop = logContent.scrollHeight;
}

async function runComplianceCheck() {
    // Hide the check button card content and show loading
    loadingCard.classList.remove('hidden');
    complianceResults.classList.add('hidden');
    runComplianceCheckBtn.disabled = true;
    
    // Start log streaming
    startLogStream();
    
    try {
        showToast('Running compliance check with AI. This may take a few minutes...', 'success');
        
        const response = await fetch('/run-compliance-check', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        });
        
        const result = await response.json();
        
        // Stop log streaming
        stopLogStream();
        
        if (result.success) {
            addLogEntry('✅ Complete! Showing results...', 'success');
            // Short delay then show results
            setTimeout(() => {
                loadingCard.classList.add('hidden');
                displayComplianceResults(result.results, result.summary);
            }, 1000);
        } else {
            addLogEntry('❌ Error: ' + (result.message || 'Unknown error'), 'error');
            loadingCard.classList.add('hidden');
            showToast(result.message || 'Compliance check failed', 'error');
        }
        
    } catch (error) {
        stopLogStream();
        loadingCard.classList.add('hidden');
        console.error('Error running compliance check:', error);
        showToast('Error running compliance check: ' + error.message, 'error');
    }
    
    runComplianceCheckBtn.disabled = false;
}

// Store results globally for modal access
let complianceResultsData = [];

function displayComplianceResults(results, summary) {
    // Use provided results or fallback to mock
    if (!results || results.length === 0) {
        results = [
            {
                regulation: 'No results',
                status: 'warning',
                message: 'No compliance results available. Make sure both documents are processed.'
            }
        ];
    }
    
    // Store results globally for modal
    complianceResultsData = results;
    
    // Calculate stats from actual results
    const passed = summary?.passed || results.filter(r => r.status === 'pass').length;
    const failed = summary?.failed || results.filter(r => r.status === 'fail').length;
    const warnings = summary?.warnings || results.filter(r => r.status === 'warning').length;
    const total = summary?.total || results.length;
    
    document.getElementById('passedCount').textContent = passed;
    document.getElementById('failedCount').textContent = failed;
    document.getElementById('warningCount').textContent = warnings;
    document.getElementById('totalCount').textContent = total;
    
    // Populate results list with clickable items
    resultsList.innerHTML = results.map((result, index) => {
        let icon, badge;
        if (result.status === 'pass') {
            icon = 'fa-check';
            badge = 'Compliant';
        } else if (result.status === 'fail') {
            icon = 'fa-times';
            badge = 'Non-Compliant';
        } else if (result.status === 'info') {
            icon = 'fa-question';
            badge = 'Insufficient Info';
        } else {
            icon = 'fa-exclamation';
            badge = 'Human Required';
        }
        
        return `
            <div class="result-item ${result.status}" data-index="${index}" onclick="showResultDetail(${index})">
                <div class="result-icon">
                    <i class="fas ${icon}"></i>
                </div>
                <div class="result-content">
                    <div class="result-title">${result.regulation}</div>
                    <div class="result-message">${result.message || 'No details available'}</div>
                    ${result.evidence ? `<div class="result-evidence"><strong>Evidence:</strong> "${result.evidence.substring(0, 100)}..."</div>` : ''}
                </div>
                <span class="result-badge">${badge}</span>
                <i class="fas fa-chevron-right result-arrow"></i>
            </div>
        `;
    }).join('');
    
    complianceResults.classList.remove('hidden');
    showToast('Compliance check completed!', 'success');
}

// Show result detail in modal
function showResultDetail(index) {
    const result = complianceResultsData[index];
    if (!result) return;
    
    const modal = document.getElementById('resultModal');
    
    // Set title
    document.getElementById('modalTitle').textContent = 'Compliance Check Details';
    
    // Set status badge with all 4 labels
    const statusBadge = document.getElementById('modalStatus');
    let badgeText, badgeClass;
    if (result.status === 'pass') {
        badgeText = 'COMPLIANT';
        badgeClass = 'pass';
    } else if (result.status === 'fail') {
        badgeText = 'NON-COMPLIANT';
        badgeClass = 'fail';
    } else if (result.status === 'info') {
        badgeText = 'INSUFFICIENT INFORMATION';
        badgeClass = 'info';
    } else {
        badgeText = 'HUMAN REQUIRED';
        badgeClass = 'warning';
    }
    statusBadge.innerHTML = `<span class="status-badge ${badgeClass}">${badgeText}</span>`;
    
    // Set regulation name
    document.getElementById('modalRegulation').textContent = result.regulation || 'Unknown Regulation';
    
    // Set regulation ID
    document.getElementById('modalRegulationId').textContent = result.regulation_id || 'N/A';
    
    // Set domain
    const domain = result.domain || {};
    let domainText = 'General';
    if (typeof domain === 'object' && domain.primary_domain) {
        domainText = domain.primary_domain;
        if (domain.sub_domains && domain.sub_domains.length > 0) {
            domainText += ' → ' + domain.sub_domains.join(', ');
        }
    } else if (typeof domain === 'string') {
        domainText = domain;
    }
    document.getElementById('modalDomain').textContent = domainText;
    
    // Show/hide contradiction section
    const contradictionSection = document.getElementById('modalContradictionSection');
    if (result.contradiction_details && result.contradiction_details.trim()) {
        contradictionSection.style.display = 'block';
        document.getElementById('modalContradiction').textContent = result.contradiction_details;
    } else {
        contradictionSection.style.display = 'none';
    }
    
    // Show/hide evidence section
    const evidenceSection = document.getElementById('modalEvidenceSection');
    if (result.evidence && result.evidence.trim()) {
        evidenceSection.style.display = 'block';
        document.getElementById('modalEvidence').textContent = `"${result.evidence}"`;
    } else {
        evidenceSection.style.display = 'none';
    }
    
    // Set explanation (full text, not truncated)
    const explanation = result.explanation || 'No explanation available';
    document.getElementById('modalExplanation').textContent = explanation;
    
    // Set confidence
    const confidence = result.confidence || 0.85;
    const confidencePercent = Math.round(confidence * 100);
    document.getElementById('modalConfidenceFill').style.width = confidencePercent + '%';
    document.getElementById('modalConfidenceValue').textContent = confidencePercent + '%';
    
    // Show modal
    modal.classList.remove('hidden');
}

// Close modal
function closeResultModal() {
    document.getElementById('resultModal').classList.add('hidden');
}

function startOver() {
    // Reset state
    regulationFile = null;
    proposalFile = null;
    
    // Reset backend state
    fetch('/reset', { method: 'POST' }).catch(err => console.log('Reset error:', err));
    
    // Reset Step 1
    regulationPreview.classList.add('hidden');
    regulationUploadZone.classList.remove('hidden');
    regulationResults.classList.add('hidden');
    processRegulationBtn.disabled = true;
    
    // Reset Step 2
    proposalPreview.classList.add('hidden');
    proposalUploadZone.classList.remove('hidden');
    proposalResults.classList.add('hidden');
    processProposalBtn.disabled = true;
    
    // Reset Step 3
    loadingCard.classList.add('hidden');
    complianceResults.classList.add('hidden');
    document.getElementById('summaryRegulation').textContent = 'Not uploaded';
    document.getElementById('summaryProposal').textContent = 'Not uploaded';
    document.getElementById('progressFill').style.width = '0%';
    
    // Go to step 1
    goToStep(1);
    
    showToast('Ready for new compliance check', 'success');
}

async function exportResults() {
    try {
        showToast('Generating report...', 'success');
        
        const response = await fetch('/export-report');
        const result = await response.json();
        
        if (result.success && result.report) {
            // Create downloadable JSON file
            const blob = new Blob([JSON.stringify(result.report, null, 2)], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'compliance_report_' + new Date().toISOString().split('T')[0] + '.json';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
            
            showToast('Report downloaded successfully!', 'success');
        } else {
            showToast(result.message || 'Export failed', 'error');
        }
    } catch (error) {
        console.error('Export error:', error);
        showToast('Error exporting report: ' + error.message, 'error');
    }
}

// ===== Event Listeners =====
document.addEventListener('DOMContentLoaded', () => {
    // Setup drag and drop
    setupDragDrop(regulationUploadZone, handleRegulationFile);
    setupDragDrop(proposalUploadZone, handleProposalFile);
    
    // File input change handlers
    regulationFileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            handleRegulationFile(e.target.files[0]);
        }
    });
    
    proposalFileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            handleProposalFile(e.target.files[0]);
        }
    });
    
    // Remove file handlers
    removeRegulationBtn.addEventListener('click', () => {
        regulationFile = null;
        regulationPreview.classList.add('hidden');
        regulationUploadZone.classList.remove('hidden');
        regulationResults.classList.add('hidden');
        processRegulationBtn.disabled = true;
        regulationFileInput.value = '';
    });
    
    removeProposalBtn.addEventListener('click', () => {
        proposalFile = null;
        proposalPreview.classList.add('hidden');
        proposalUploadZone.classList.remove('hidden');
        proposalResults.classList.add('hidden');
        processProposalBtn.disabled = true;
        proposalFileInput.value = '';
    });
    
    // Load saved regulations button
    const loadSavedRegulationsBtn = document.getElementById('loadSavedRegulations');
    if (loadSavedRegulationsBtn) {
        loadSavedRegulationsBtn.addEventListener('click', loadSavedRegulations);
    }
    
    // Process button handlers
    processRegulationBtn.addEventListener('click', processRegulation);
    processProposalBtn.addEventListener('click', processProposal);
    
    // Navigation handlers
    goToStep2Btn.addEventListener('click', () => goToStep(2));
    backToStep1Btn.addEventListener('click', () => goToStep(1));
    goToStep3Btn.addEventListener('click', () => goToStep(3));
    backToStep2Btn.addEventListener('click', () => goToStep(2));
    
    // Compliance check handlers
    runComplianceCheckBtn.addEventListener('click', runComplianceCheck);
    exportResultsBtn.addEventListener('click', exportResults);
    startOverBtn.addEventListener('click', startOver);
    
    // Modal close handlers
    document.getElementById('closeModal').addEventListener('click', closeResultModal);
    document.getElementById('resultModal').addEventListener('click', (e) => {
        if (e.target.id === 'resultModal') {
            closeResultModal();
        }
    });
    
    // Close modal with Escape key
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            closeResultModal();
        }
    });
    
    // Click on upload zone to trigger file input
    regulationUploadZone.addEventListener('click', (e) => {
        if (e.target.tagName !== 'INPUT' && !e.target.closest('label') && !e.target.closest('button')) {
            regulationFileInput.click();
        }
    });
    
    proposalUploadZone.addEventListener('click', (e) => {
        if (e.target.tagName !== 'INPUT' && !e.target.closest('label')) {
            proposalFileInput.click();
        }
    });
});

// ===== Load Saved Regulations =====
async function loadSavedRegulations() {
    const btn = document.getElementById('loadSavedRegulations');
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Loading...';
    
    // Disable "Continue to Step 2" button during loading
    goToStep2Btn.disabled = true;
    goToStep2Btn.classList.add('btn-disabled');
    
    // Show results card with log console early
    regulationResults.classList.remove('hidden');
    startRegulationLogStream();
    
    try {
        const response = await fetch('/load-saved-regulations', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        });
        
        const result = await response.json();
        
        stopRegulationLogStream();
        
        if (result.success) {
            addRegulationLogEntry('✅ Loading complete!', 'success');
            
            // Update UI with results
            document.getElementById('totalRegulations').textContent = result.features.total_regulations || 0;
            document.getElementById('totalCategories').textContent = result.features.categories?.length || 0;
            document.getElementById('totalKeywords').textContent = result.features.keywords?.length || 0;
            
            regulationUploadZone.classList.add('hidden');
            
            // Update summary in step 3
            document.getElementById('summaryRegulation').textContent = 'GDPR (pre-extracted)';
            
            // Set a dummy file reference
            regulationFile = { name: 'extracted_regulations.json' };
            
            // Enable "Continue to Step 2" button after successful loading
            goToStep2Btn.disabled = false;
            goToStep2Btn.classList.remove('btn-disabled');
            
            showToast(`Loaded ${result.features.total_regulations} GDPR regulations!`, 'success');
        } else {
            addRegulationLogEntry('❌ ' + (result.message || 'Failed to load'), 'error');
            showToast(result.message || 'Failed to load regulations', 'error');
        }
        
    } catch (error) {
        stopRegulationLogStream();
        console.error('Error loading saved regulations:', error);
        showToast('Error loading saved regulations: ' + error.message, 'error');
    }
    
    btn.disabled = false;
    btn.innerHTML = '<i class="fas fa-database"></i> Load GDPR Regulations';
}
