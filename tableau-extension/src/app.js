/**
 * AI Analytics Agent - Tableau Extension
 * Main application logic with markdown rendering and Chart.js visualizations
 */

// Configuration - UPDATE THESE FOR YOUR ENVIRONMENT
const CONFIG = {
    // Backend API URL (your deployment)
    API_URL: 'http://localhost:8000/api/v1',
    
    // Request timeout in milliseconds
    TIMEOUT: 120000,
    
    // Enable debug logging
    DEBUG: true
};

// State
let isInitialized = false;
let dashboardContext = null;
let sessionThreadId = null;  // For conversation memory
let messageCount = 0;

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
                let filterValue = null;
                
                // Try to get filter value based on type
                if (filter.filterType === 'categorical') {
                    const appliedValues = filter.appliedValues;
                    if (appliedValues && appliedValues.length > 0) {
                        filterValue = appliedValues.map(v => v.value).join(', ');
                    }
                } else if (filter.filterType === 'range') {
                    filterValue = `${filter.minValue} - ${filter.maxValue}`;
                }
                
                dashboardContext.filters.push({
                    worksheet: worksheet.name,
                    field: filter.fieldName,
                    type: filter.filterType,
                    value: filterValue
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
 * Quick query helper for quick action buttons
 */
function quickQuery(query) {
    document.getElementById('userInput').value = query;
    sendMessage();
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
    messageCount++;
    
    // Add user message to chat
    addMessage(message, 'user');
    
    // Check streaming mode
    const streamingCheckbox = document.getElementById('streamingMode');
    const useStreaming = streamingCheckbox ? streamingCheckbox.checked : false;
    
    if (useStreaming) {
        await sendMessageWithStreaming(message);
    } else {
        await sendMessageStandard(message);
    }
}

/**
 * Send message with SSE streaming
 */
async function sendMessageWithStreaming(message) {
    const loadingId = addLoadingMessage('🤔 Analyzing...');
    
    try {
        // Refresh dashboard context before sending
        await captureDashboardContext();
        
        const requestBody = {
            question: message,
            username: 'tableau-extension-user',
            thread_id: sessionThreadId,
            dashboard_name: dashboardContext?.name || null,
            worksheets: dashboardContext?.worksheets || [],
            filters: dashboardContext?.filters || [],
            datasources: dashboardContext?.datasources || [],
            parameters: dashboardContext?.parameters || [],
            selected_marks: dashboardContext?.selected_marks || []
        };
        
        log('Sending streaming request', { question: message });
        
        const response = await fetch(`${CONFIG.API_URL}/dashboard/query/stream`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(requestBody)
        });
        
        if (!response.ok) throw new Error(`API error: ${response.status}`);
        
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            
            buffer += decoder.decode(value, { stream: true });
            
            // Process complete SSE events
            const lines = buffer.split('\n\n');
            buffer = lines.pop(); // Keep incomplete event
            
            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    try {
                        const eventData = JSON.parse(line.slice(6));
                        handleStreamEvent(eventData, loadingId);
                    } catch (e) {
                        log('Parse error', e);
                    }
                }
            }
        }
    } catch (err) {
        log('Streaming failed', err);
        removeMessage(loadingId);
        addMessage(`Connection error: ${err.message}`, 'assistant');
    }
}

/**
 * Handle SSE stream events
 */
function handleStreamEvent(event, loadingId) {
    log('Stream event', event);
    
    if (event.event === 'thinking') {
        updateLoadingMessage(loadingId, '🤔 ' + event.message);
    } else if (event.event === 'querying') {
        updateLoadingMessage(loadingId, '🔄 ' + event.message);
    } else if (event.event === 'analyzing') {
        updateLoadingMessage(loadingId, '📊 ' + event.message);
    } else if (event.event === 'complete' || event.event === 'error') {
        removeMessage(loadingId);
        const data = event.data;
        
        // Store thread_id
        if (data.thread_id && !sessionThreadId) {
            sessionThreadId = data.thread_id;
        }
        updateStatus(`Connected • ${messageCount} messages`, 'connected');
        
        if (data.success !== false || data.analysis) {
            const intentBadge = `<span style="background: var(--primary-color); padding: 2px 8px; border-radius: 12px; font-size: 10px; margin-right: 8px;">${data.intent || 'query'}</span>`;
            const queryTypeBadge = data.query_type && data.query_type !== 'standard' 
                ? `<span style="background: #48bb78; padding: 2px 8px; border-radius: 12px; font-size: 10px; margin-right: 8px;">${data.query_type}</span>` 
                : '';
            const analysisHtml = parseMarkdown(data.analysis || 'Query completed.');
            addMessage(intentBadge + queryTypeBadge + analysisHtml, 'assistant');
            
            if (data.visualization && data.results?.data) {
                renderVisualization(data.visualization, data.results.data);
            }
            if (data.results?.data?.length > 0) {
                addDataPreview(data.results.data);
            }
        } else {
            addMessage(`Error: ${data.error || 'Unknown error'}`, 'assistant');
        }
    }
}

/**
 * Update loading message text
 */
function updateLoadingMessage(id, text) {
    const el = document.getElementById(id);
    if (el) {
        el.querySelector('.message-content').innerHTML = `<div style="display: flex; align-items: center; gap: 8px;">${text}</div>`;
    }
}

/**
 * Send message without streaming (standard mode)
 */
async function sendMessageStandard(message) {
    const loadingId = addLoadingMessage();
    
    try {
        // Refresh dashboard context before sending
        await captureDashboardContext();
        
        // Prepare request with dashboard context and thread_id
        const requestBody = {
            question: message,
            username: 'tableau-extension-user',
            thread_id: sessionThreadId,  // Include thread_id for conversation memory
            // Dashboard context fields
            dashboard_name: dashboardContext?.name || null,
            worksheets: dashboardContext?.worksheets || [],
            filters: dashboardContext?.filters || [],
            datasources: dashboardContext?.datasources || [],
            parameters: dashboardContext?.parameters || [],
            selected_marks: dashboardContext?.selected_marks || []
        };
        
        log('Sending request to Dashboard Agent', { ...requestBody, thread_id: sessionThreadId || '(new session)' });
        
        // Call Dashboard Agent API
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
        
        // Store thread_id for conversation continuity
        if (data.thread_id && !sessionThreadId) {
            sessionThreadId = data.thread_id;
            log('Session started', { thread_id: sessionThreadId.substring(0, 8) + '...' });
        }
        
        // Update status with message count
        if (sessionThreadId) {
            updateStatus(`Connected • ${messageCount} messages`, 'connected');
        }
        
        // Remove loading indicator
        removeMessage(loadingId);
        
        // Handle response
        if (data.success !== false) {
            // Show intent badge + query type badge + parsed markdown analysis
            const intentBadge = `<span style="background: var(--primary-color); padding: 2px 8px; border-radius: 12px; font-size: 10px; margin-right: 8px;">${data.intent || 'query'}</span>`;
            const queryTypeBadge = data.query_type && data.query_type !== 'standard' 
                ? `<span style="background: #48bb78; padding: 2px 8px; border-radius: 12px; font-size: 10px; margin-right: 8px;">${data.query_type}</span>` 
                : '';
            const analysisHtml = parseMarkdown(data.analysis || 'Query completed.');
            addMessage(intentBadge + queryTypeBadge + analysisHtml, 'assistant');
            
            // Show visualization if available
            if (data.visualization && data.results?.data) {
                renderVisualization(data.visualization, data.results.data);
            }
            
            // Show data preview if available
            if (data.results?.data && data.results.data.length > 0) {
                addDataPreview(data.results.data);
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
 * Parse markdown to HTML using marked.js
 */
function parseMarkdown(text) {
    if (!text) return '';
    try {
        if (typeof marked !== 'undefined') {
            return marked.parse(text);
        }
    } catch (e) {
        console.warn('Markdown parsing failed:', e);
    }
    // Fallback: basic formatting
    return text
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\n/g, '<br>');
}

/**
 * Render visualization (chart) from backend config + data
 */
function renderVisualization(vizConfig, data) {
    if (!vizConfig || !data || !data.length) {
        log('Cannot render visualization - missing config or data', { vizConfig, dataLength: data?.length });
        return;
    }
    
    log('Rendering visualization', { vizConfig, dataRows: data.length });
    
    // Get chart type (backend uses chart_type, Chart.js expects type)
    const chartType = vizConfig.chart_type || vizConfig.type || 'bar';
    
    // Extract labels and values from data using vizConfig's axis definitions
    const xAxis = vizConfig.x_axis || Object.keys(data[0])[0];
    const yAxis = vizConfig.y_axis || Object.keys(data[0])[1];
    
    // Clean axis names (remove aggregation wrappers)
    const xAxisClean = xAxis.replace(/^(SUM|AVG|COUNT|MAX|MIN)\((.+)\)$/i, '$2');
    const yAxisClean = yAxis.replace(/^(SUM|AVG|COUNT|MAX|MIN)\((.+)\)$/i, '$2');
    
    // Find matching columns in data
    const findColumn = (axis) => {
        const axisLower = axis.toLowerCase().replace(/[^a-z0-9]/g, '');
        const keys = Object.keys(data[0]);
        return keys.find(k => {
            const keyLower = k.toLowerCase().replace(/[^a-z0-9]/g, '');
            return keyLower.includes(axisLower) || axisLower.includes(keyLower);
        }) || keys[0];
    };
    
    const labelKey = findColumn(xAxisClean);
    const valueKey = findColumn(yAxisClean);
    
    log('Chart axes mapped', { xAxis, yAxis, labelKey, valueKey });
    
    // Extract labels and values (limit to 10)
    const chartData = data.slice(0, 10);
    const labels = chartData.map(row => {
        const val = row[labelKey];
        return typeof val === 'string' && val.length > 25 ? val.substring(0, 22) + '...' : val;
    });
    const values = chartData.map(row => {
        const val = row[valueKey];
        return typeof val === 'number' ? val : parseFloat(val) || 0;
    });
    
    const container = document.getElementById('chatContainer');
    const chartId = 'chart-' + Date.now();
    
    // Create chart container
    const chartDiv = document.createElement('div');
    chartDiv.className = 'message assistant';
    chartDiv.innerHTML = `
        <div class="message-content">
            <div class="chart-container">
                <canvas id="${chartId}"></canvas>
            </div>
            <div style="font-size: 11px; color: var(--text-secondary); margin-top: 8px;">
                📊 ${chartType.toUpperCase()} chart: ${yAxisClean} by ${xAxisClean}
            </div>
        </div>
    `;
    container.appendChild(chartDiv);
    scrollToBottom();
    
    // Render chart
    setTimeout(() => {
        const ctx = document.getElementById(chartId);
        if (!ctx || typeof Chart === 'undefined') {
            log('Chart.js not available');
            return;
        }
        
        try {
            new Chart(ctx, {
                type: chartType === 'bar' ? 'bar' : chartType,
                data: {
                    labels: labels,
                    datasets: [{
                        label: yAxisClean,
                        data: values,
                        backgroundColor: [
                            '#4a90d9', '#48bb78', '#fc8181', '#f6ad55', '#9f7aea',
                            '#4fd1c5', '#f687b3', '#68d391', '#63b3ed', '#fbd38d'
                        ],
                        borderColor: 'rgba(255,255,255,0.2)',
                        borderWidth: 1
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: true,
                    indexAxis: chartType === 'horizontalBar' ? 'y' : 'x',
                    plugins: {
                        legend: { display: false },
                        title: {
                            display: true,
                            text: `${yAxisClean} by ${xAxisClean}`,
                            color: '#ffffff',
                            font: { size: 13 }
                        }
                    },
                    scales: chartType === 'pie' || chartType === 'doughnut' ? {} : {
                        x: { ticks: { color: '#a0aec0', maxRotation: 45 }, grid: { color: '#2d3748' } },
                        y: { ticks: { color: '#a0aec0' }, grid: { color: '#2d3748' } }
                    }
                }
            });
            log('Chart rendered successfully');
        } catch (e) {
            log('Chart rendering failed', e);
        }
    }, 100);
}

/**
 * Add a message to the chat
 */
function addMessage(content, role) {
    const container = document.getElementById('chatContainer');
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;
    messageDiv.innerHTML = `<div class="message-content">${content}</div>`;
    container.appendChild(messageDiv);
    scrollToBottom();
    return messageDiv;
}

/**
 * Add loading indicator
 */
function addLoadingMessage(customText = null) {
    const container = document.getElementById('chatContainer');
    const messageDiv = document.createElement('div');
    const id = 'loading-' + Date.now();
    messageDiv.id = id;
    messageDiv.className = 'message assistant loading';
    if (customText) {
        messageDiv.innerHTML = `
            <div class="message-content">
                <div style="display: flex; align-items: center; gap: 8px;">${customText}</div>
            </div>
        `;
    } else {
        messageDiv.innerHTML = `
            <div class="message-content">
                <div class="loading-dot"></div>
                <div class="loading-dot"></div>
                <div class="loading-dot"></div>
            </div>
        `;
    }
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
