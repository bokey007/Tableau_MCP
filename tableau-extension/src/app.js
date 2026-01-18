/**
 * AI Analytics Agent - Tableau Extension
 * Main application logic
 */

// Configuration - UPDATE THESE FOR YOUR ENVIRONMENT
const CONFIG = {
    // Backend API URL (your ARES deployment)
    API_URL: 'http://localhost:8000/api/v1',
    
    // Request timeout in milliseconds
    TIMEOUT: 120000,
    
    // Enable debug logging
    DEBUG: true
};

// State
let isInitialized = false;
let dashboardContext = null;

/**
 * Initialize the extension when Tableau is ready
 */
document.addEventListener('DOMContentLoaded', () => {
    // Initialize Tableau Extensions API
    tableau.extensions.initializeAsync().then(() => {
        log('Tableau Extensions API initialized');
        isInitialized = true;
        updateStatus('Connected', 'connected');
        
        // Get dashboard context
        captureDashboardContext();
        
        // Setup event listeners
        setupEventListeners();
        
    }).catch(err => {
        log('Failed to initialize Tableau Extensions API', err);
        updateStatus('Error: ' + err.message, 'error');
    });
});

/**
 * Capture current dashboard context (filters, parameters, datasources)
 */
async function captureDashboardContext() {
    try {
        const dashboard = tableau.extensions.dashboardContent.dashboard;
        
        dashboardContext = {
            name: dashboard.name,
            worksheets: [],
            filters: [],
            datasources: []
        };
        
        // Get worksheets
        for (const worksheet of dashboard.worksheets) {
            dashboardContext.worksheets.push({
                name: worksheet.name
            });
            
            // Get filters from each worksheet
            const filters = await worksheet.getFiltersAsync();
            for (const filter of filters) {
                dashboardContext.filters.push({
                    worksheet: worksheet.name,
                    field: filter.fieldName,
                    type: filter.filterType
                });
            }
        }
        
        // Get datasources
        const datasources = await tableau.extensions.dashboardContent.dashboard.worksheets[0]?.getDataSourcesAsync();
        if (datasources) {
            for (const ds of datasources) {
                dashboardContext.datasources.push({
                    name: ds.name,
                    id: ds.id
                });
            }
        }
        
        log('Dashboard context captured', dashboardContext);
        
    } catch (err) {
        log('Failed to capture dashboard context', err);
    }
}

/**
 * Setup event listeners
 */
function setupEventListeners() {
    const input = document.getElementById('userInput');
    const sendBtn = document.getElementById('sendBtn');
    
    // Enter key to send
    input.addEventListener('keypress', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });
    
    // Focus input on load
    input.focus();
}

/**
 * Send user message to the AI agent
 */
async function sendMessage() {
    const input = document.getElementById('userInput');
    const message = input.value.trim();
    
    if (!message) return;
    
    // Clear input
    input.value = '';
    
    // Add user message to chat
    addMessage(message, 'user');
    
    // Show loading indicator
    const loadingId = addLoadingMessage();
    
    try {
        // Refresh dashboard context before sending
        await captureDashboardContext();
        
        // Prepare request with dashboard context (new Dashboard Agent schema)
        const requestBody = {
            question: message,
            username: 'tableau-extension-user',
            // Dashboard context fields (flattened for new API)
            dashboard_name: dashboardContext?.name || null,
            worksheets: dashboardContext?.worksheets || [],
            filters: dashboardContext?.filters || [],
            datasources: dashboardContext?.datasources || [],
            parameters: dashboardContext?.parameters || [],
            selected_marks: dashboardContext?.selected_marks || []
        };
        
        log('Sending request to Dashboard Agent', requestBody);
        
        // Call Dashboard Agent API (new endpoint)
        const response = await fetch(`${CONFIG.API_URL}/dashboard/query`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(requestBody)
        });
        
        if (!response.ok) {
            throw new Error(`API error: ${response.status}`);
        }
        
        const data = await response.json();
        log('Received response', data);
        
        // Remove loading indicator
        removeMessage(loadingId);
        
        // Handle response
        if (data.success) {
            // Add analysis as message
            addMessage(data.analysis || 'Query completed successfully.', 'assistant');
            
            // If there's data, show a preview
            if (data.results?.data && data.results.data.length > 0) {
                addDataPreview(data.results.data);
            }
            
            // If there's a visualization recommendation
            if (data.visualization) {
                addVizRecommendation(data.visualization);
            }
        } else {
            addMessage(`Sorry, I encountered an error: ${data.error || 'Unknown error'}`, 'assistant');
        }
        
    } catch (err) {
        log('Request failed', err);
        removeMessage(loadingId);
        addMessage(`Connection error: ${err.message}. Please check if the backend is running.`, 'assistant');
    }
}

/**
 * Add a message to the chat
 */
function addMessage(content, role) {
    const container = document.getElementById('chatContainer');
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;
    messageDiv.innerHTML = `<div class="message-content">${formatMessage(content)}</div>`;
    container.appendChild(messageDiv);
    scrollToBottom();
    return messageDiv;
}

/**
 * Add loading indicator
 */
function addLoadingMessage() {
    const container = document.getElementById('chatContainer');
    const messageDiv = document.createElement('div');
    const id = 'loading-' + Date.now();
    messageDiv.id = id;
    messageDiv.className = 'message assistant loading';
    messageDiv.innerHTML = `
        <div class="message-content">
            <div class="loading-dot"></div>
            <div class="loading-dot"></div>
            <div class="loading-dot"></div>
        </div>
    `;
    container.appendChild(messageDiv);
    scrollToBottom();
    return id;
}

/**
 * Remove a message by ID
 */
function removeMessage(id) {
    const element = document.getElementById(id);
    if (element) {
        element.remove();
    }
}

/**
 * Add data preview table
 */
function addDataPreview(data, maxRows = 5) {
    if (!data || data.length === 0) return;
    
    const container = document.getElementById('chatContainer');
    const messageDiv = document.createElement('div');
    messageDiv.className = 'message assistant';
    
    // Get columns from first row
    const columns = Object.keys(data[0]);
    const previewData = data.slice(0, maxRows);
    
    let tableHtml = `
        <div class="message-content">
            <div class="data-table">
                <table>
                    <thead>
                        <tr>${columns.map(col => `<th>${col}</th>`).join('')}</tr>
                    </thead>
                    <tbody>
                        ${previewData.map(row => 
                            `<tr>${columns.map(col => `<td>${formatValue(row[col])}</td>`).join('')}</tr>`
                        ).join('')}
                    </tbody>
                </table>
            </div>
            ${data.length > maxRows ? `<div style="font-size: 11px; color: var(--text-secondary); margin-top: 8px;">Showing ${maxRows} of ${data.length} rows</div>` : ''}
        </div>
    `;
    
    messageDiv.innerHTML = tableHtml;
    container.appendChild(messageDiv);
    scrollToBottom();
}

/**
 * Add visualization recommendation
 */
function addVizRecommendation(viz) {
    const container = document.getElementById('chatContainer');
    const messageDiv = document.createElement('div');
    messageDiv.className = 'message assistant';
    messageDiv.innerHTML = `
        <div class="message-content">
            <div class="viz-container">
                <div class="viz-title">📊 Recommended Visualization</div>
                <div><strong>Type:</strong> ${viz.type || 'Chart'}</div>
                ${viz.description ? `<div style="margin-top: 4px; font-size: 12px; color: var(--text-secondary);">${viz.description}</div>` : ''}
            </div>
        </div>
    `;
    container.appendChild(messageDiv);
    scrollToBottom();
}

/**
 * Format message content (handle markdown-like formatting)
 */
function formatMessage(content) {
    if (!content) return '';
    
    return content
        // Bold
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        // Line breaks
        .replace(/\n/g, '<br>')
        // Lists
        .replace(/^- (.*)/gm, '• $1');
}

/**
 * Format cell values
 */
function formatValue(value) {
    if (value === null || value === undefined) return '-';
    if (typeof value === 'number') {
        return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
    }
    return String(value);
}

/**
 * Scroll chat to bottom
 */
function scrollToBottom() {
    const container = document.getElementById('chatContainer');
    container.scrollTop = container.scrollHeight;
}

/**
 * Update connection status
 */
function updateStatus(text, className) {
    const status = document.getElementById('connectionStatus');
    status.textContent = text;
    status.className = 'status ' + (className || '');
}

/**
 * Debug logging
 */
function log(message, data) {
    if (CONFIG.DEBUG) {
        console.log(`[AI Agent] ${message}`, data || '');
    }
}
