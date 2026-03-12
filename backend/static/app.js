/**
 * MCP Client Web - Chat Application Logic
 * Handles chat interface, message sending, and session management
 */

console.log('💬 Chat app initializing...');

// State
let currentSessionId = null;
let isProcessing = false;
const CHAT_PREFERENCE_STORAGE_KEY = 'includeHistory';

// DOM Elements
const chatMessages = document.getElementById('chatMessages');
const messageInput = document.getElementById('messageInput');
const sendBtn = document.getElementById('sendBtn');
const newChatBtn = document.getElementById('newChatBtn');
const darkModeBtn = document.getElementById('darkModeBtn');

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    console.log('💬 Chat: DOM loaded');
    initializeChat();
});

function initializeChat() {
    // Auto-resize textarea
    messageInput.addEventListener('input', () => {
        messageInput.style.height = 'auto';
        messageInput.style.height = messageInput.scrollHeight + 'px';
        
        // Enable/disable send button
        sendBtn.disabled = !messageInput.value.trim() || isProcessing;
    });

    // Send on Enter (Shift+Enter for new line)
    messageInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            if (!sendBtn.disabled) {
                sendMessage();
            }
        }
    });

    // Send button click
    sendBtn.addEventListener('click', sendMessage);

    // New chat button
    newChatBtn.addEventListener('click', createNewSession);

    // Dark mode toggle
    applyTheme(localStorage.getItem('theme') === 'dark');
    darkModeBtn.addEventListener('click', () => {
        const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
        applyTheme(!isDark);
    });

    console.log('💬 Chat: Initialized');
}

async function createNewSession() {
    console.log('💬 Chat: Creating new session...');

    try {
        const llmConfigResponse = await fetch('/api/llm/config');
        if (!llmConfigResponse.ok) {
            if (llmConfigResponse.status === 404) {
                showError('Please configure LLM provider in Settings first');
                return;
            }
            throw new Error(`HTTP ${llmConfigResponse.status}`);
        }

        const llmConfig = await llmConfigResponse.json();

        const serversResponse = await fetch('/api/servers');
        const enabledServers = serversResponse.ok
            ? (await serversResponse.json()).map(server => server.alias)
            : [];

        const response = await fetch('/api/sessions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                llm_config: llmConfig,
                enabled_servers: enabledServers,
                include_history: localStorage.getItem(CHAT_PREFERENCE_STORAGE_KEY) !== 'false'
            })
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();
        currentSessionId = data.session_id;
        
        // Clear chat
        chatMessages.innerHTML = '';
        addSystemMessage('New chat session started');
        
        console.log(`💬 Chat: Session created: ${currentSessionId}`);
    } catch (error) {
        console.error('💬 Chat: Session creation failed', error);
        showError('Failed to create session: ' + error.message);
    }
}

function applyTheme(dark) {
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
    if (darkModeBtn) {
        darkModeBtn.textContent = dark ? '☀️' : '🌙';
        darkModeBtn.title = dark ? 'Switch to light mode' : 'Switch to dark mode';
    }
    localStorage.setItem('theme', dark ? 'dark' : 'light');
}

async function sendMessage() {
    const content = messageInput.value.trim();
    if (!content || isProcessing) return;

    console.log(`💬 Chat: Sending message: ${content.substring(0, 50)}...`);

    // Create session if needed
    if (!currentSessionId) {
        await createNewSession();
        if (!currentSessionId) return;
    }

    // Add user message to UI
    const querySentAt = new Date();
    addMessage('user', content, [], '', querySentAt);
    messageInput.value = '';
    messageInput.style.height = 'auto';
    sendBtn.disabled = true;
    isProcessing = true;

    // Show loading
    const loadingId = addLoadingMessage();

    try {
        const response = await fetch(`/api/sessions/${currentSessionId}/messages`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                role: 'user',
                content: content
            })
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();
        
        // Remove loading
        removeMessage(loadingId);
        
        // Add assistant response
        addMessage('assistant', data.message.content, data.tool_executions, data.initial_llm_response, new Date());
        
        // Log final LLM message
        console.log('💬 Final LLM Response:', data.message.content);
        if (data.tool_executions && data.tool_executions.length > 0) {
            console.log(`🔧 Tools executed (${data.tool_executions.length}):`, 
                data.tool_executions.map(t => `${t.tool} (${t.success ? 'success' : 'failed'})`).join(', '));
        }
    } catch (error) {
        console.error('💬 Chat: Send failed', error);
        removeMessage(loadingId);
        showError('Failed to send message: ' + error.message);
    } finally {
        isProcessing = false;
        sendBtn.disabled = !messageInput.value.trim();
    }
}

function addMessage(role, content, toolExecutions = [], initialLlmResponse = '', timestamp = null) {
    const messageWrapper = document.createElement('div');
    messageWrapper.classList.add('message-wrapper', role);

    const messageContent = document.createElement('div');
    messageContent.classList.add('message-content');
    
    // Format content with line breaks and preserve formatting
    const primaryContent = content || initialLlmResponse || '';
    const formattedContent = formatMessageContent(primaryContent);
    messageContent.innerHTML = formattedContent;

    messageWrapper.appendChild(messageContent);

    // Timestamp
    if (timestamp) {
        const ts = document.createElement('div');
        ts.classList.add('message-timestamp');
        const timeStr = timestamp.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        const label = role === 'user' ? 'Sent' : 'Received';
        ts.textContent = `${label} at ${timeStr}`;
        messageWrapper.appendChild(ts);
    }

    const hasInitialSuggestion = role === 'assistant'
        && Boolean(initialLlmResponse)
        && Boolean(content)
        && initialLlmResponse.trim() !== content.trim();

    if (hasInitialSuggestion) {
        const suggestionDetails = document.createElement('details');
        suggestionDetails.className = 'assistant-meta-details';
        suggestionDetails.innerHTML = `
            <summary class="assistant-meta-summary">
                <span class="assistant-meta-icon">💡</span>
                <span class="assistant-meta-title">Initial LLM suggestion</span>
            </summary>
            <div class="assistant-meta-body">${formatMessageContent(initialLlmResponse)}</div>
        `;
        messageWrapper.appendChild(suggestionDetails);
    }

    // Collapsible tool execution cards
    if (toolExecutions && toolExecutions.length > 0) {
        const section = document.createElement('div');
        section.classList.add('tool-executions-section');

        const escHtml = s => String(s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');

        toolExecutions.forEach(exec => {
            const statusClass = exec.success ? 'success' : 'error';
            const statusLabel = exec.success ? '✓ OK' : '✗ Error';
            const durationLabel = exec.duration_ms != null ? `${exec.duration_ms} ms` : '';
            const argsStr = exec.arguments && Object.keys(exec.arguments).length
                ? JSON.stringify(exec.arguments, null, 2) : '{}';
            const resultStr = typeof exec.result === 'string'
                ? exec.result : JSON.stringify(exec.result, null, 2);

            const details = document.createElement('details');
            details.className = `tool-exec-details ${statusClass}`;
            details.innerHTML = `
                <summary class="tool-exec-summary">
                    <span class="tool-exec-icon">🔧</span>
                    <span class="tool-exec-name">${escHtml(exec.tool)}</span>
                    ${durationLabel ? `<span class="tool-exec-duration">${escHtml(durationLabel)}</span>` : ''}
                    <span class="tool-exec-status ${statusClass}">${statusLabel}</span>
                </summary>
                <div class="tool-exec-body">
                    <div class="tool-exec-section">
                        <label>Arguments</label>
                        <code>${escHtml(argsStr)}</code>
                    </div>
                    <div class="tool-exec-section">
                        <label>Result</label>
                        <code>${escHtml(resultStr)}</code>
                    </div>
                </div>`;
            section.appendChild(details);
        });

        messageWrapper.appendChild(section);
    }

    chatMessages.appendChild(messageWrapper);
    scrollToBottom();
}

function formatMessageContent(content) {
    if (!content) return '';
    
    // Escape HTML to prevent XSS
    const escapeHtml = (text) => {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    };
    
    let formatted = escapeHtml(content);
    
    // Convert newlines to <br> tags
    formatted = formatted.replace(/\n/g, '<br>');
    
    // Format code blocks (```...```)
    formatted = formatted.replace(/```(\w*)\n([\s\S]*?)```/g, (match, lang, code) => {
        return `<pre><code class="language-${lang}">${code}</code></pre>`;
    });
    
    // Format inline code (`...`)
    formatted = formatted.replace(/`([^`]+)`/g, '<code>$1</code>');
    
    // Format bold (**...** or __...__)
    formatted = formatted.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    formatted = formatted.replace(/__([^_]+)__/g, '<strong>$1</strong>');
    
    // Format italic (*...* or _..._)
    formatted = formatted.replace(/\*([^*]+)\*/g, '<em>$1</em>');
    formatted = formatted.replace(/_([^_]+)_/g, '<em>$1</em>');
    
    return formatted;
}

function addSystemMessage(content) {
    const messageWrapper = document.createElement('div');
    messageWrapper.classList.add('message-wrapper');
    messageWrapper.innerHTML = `
        <div class="message-content" style="background-color: var(--bg-tertiary); color: var(--text-secondary); font-style: italic;">
            ${content}
        </div>
    `;
    chatMessages.appendChild(messageWrapper);
    scrollToBottom();
}

function addLoadingMessage() {
    const id = 'loading-' + Date.now();
    const messageWrapper = document.createElement('div');
    messageWrapper.id = id;
    messageWrapper.classList.add('message-wrapper', 'assistant');
    messageWrapper.innerHTML = `
        <div class="message-content">
            <div class="typing-dots">
                <span class="walking-man">&#x1F426;</span><span></span><span></span><span></span>
            </div>
        </div>
    `;
    chatMessages.appendChild(messageWrapper);
    scrollToBottom();
    return id;
}

function removeMessage(id) {
    const element = document.getElementById(id);
    if (element) {
        element.remove();
    }
}

function showError(message) {
    const errorDiv = document.createElement('div');
    errorDiv.classList.add('message-wrapper');
    errorDiv.innerHTML = `
        <div class="error-message">
            ❌ ${message}
        </div>
    `;
    chatMessages.appendChild(errorDiv);
    scrollToBottom();
}

function scrollToBottom() {
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

// ============================================================================
// Tools Sidebar
// ============================================================================

// Sidebar tool filter - pure client-side, no API calls
function filterTools(query) {
    const groups = document.querySelectorAll('.tool-server-group');
    groups.forEach(group => {
        let groupHasMatch = false;
        group.querySelectorAll('.tool-item').forEach(item => {
            const match = !query ||
                (item.dataset.toolName || '').includes(query) ||
                (item.dataset.toolDesc || '').includes(query);
            item.style.display = match ? '' : 'none';
            if (match) groupHasMatch = true;
        });
        group.style.display = groupHasMatch ? '' : 'none';
    });
}

// Make this function global so settings.js can call it
window.loadToolsSidebar = async function() {
    console.log('🔧 Loading tools for sidebar...');
    const toolsSidebarContent = document.getElementById('toolsSidebarContent');

    if (!toolsSidebarContent) {
        console.error('❌ toolsSidebarContent element not found!');
        return;
    }

    // Show loading spinner
    toolsSidebarContent.innerHTML = '<div class="tools-loading"><div class="spinner"></div><span>Loading tools…</span></div>';

    try {
        const response = await fetch('/api/tools');
        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        const tools = await response.json();

        // Update count badge
        const countBadge = document.getElementById('toolsCountBadge');
        if (countBadge) {
            if (tools.length > 0) {
                countBadge.textContent = tools.length;
                countBadge.style.display = 'inline-flex';
            } else {
                countBadge.style.display = 'none';
            }
        }

        if (!tools.length) {
            toolsSidebarContent.innerHTML = '<p class="empty-state">No tools discovered yet.<br>Add servers and refresh tools.</p>';
            return;
        }

        // Group by server
        const toolsByServer = {};
        tools.forEach(tool => {
            if (!toolsByServer[tool.server_alias]) toolsByServer[tool.server_alias] = [];
            toolsByServer[tool.server_alias].push(tool);
        });

        let html = '';
        for (const [serverAlias, serverTools] of Object.entries(toolsByServer)) {
            const toolItems = serverTools.map((tool, idx) => {
                const params = tool.parameters?.properties
                    ? Object.keys(tool.parameters.properties)
                    : [];
                const chipsHtml = params.length
                    ? `<div class="tool-params-chips">${params.map(p => `<span class="tool-param-chip">${p}</span>`).join('')}</div>`
                    : '';
                const escapedDesc = (tool.description || '').replace(/"/g, '&quot;');
                const delay = idx * 0.04;
                return `<div class="tool-item" style="animation-delay:${delay}s"
                    data-tool-name="${tool.name.toLowerCase()}"
                    data-tool-desc="${escapedDesc.toLowerCase()}"
                    title="${escapedDesc}">
                    <div class="tool-name">${tool.name}</div>
                    ${tool.description ? `<div class="tool-description">${tool.description}</div>` : ''}
                    ${chipsHtml}
                </div>`;
            }).join('');

            html += `
                <div class="tool-server-group" data-server="${serverAlias}">
                    <div class="tool-server-header" onclick="this.closest('.tool-server-group').classList.toggle('collapsed')">
                        <span class="tool-server-name">${serverAlias}</span>
                        <span class="tool-server-meta">
                            <span class="server-tool-count">${serverTools.length}</span>
                            <span class="tool-server-chevron">▼</span>
                        </span>
                    </div>
                    <div class="tool-server-tools">${toolItems}</div>
                </div>`;
        }

        toolsSidebarContent.innerHTML = html;

        // Re-apply active search filter if any
        const searchInput = document.getElementById('toolsSearchInput');
        if (searchInput && searchInput.value.trim()) {
            filterTools(searchInput.value.trim().toLowerCase());
        }
    } catch (error) {
        console.error('❌ Error loading tools:', error);
        toolsSidebarContent.innerHTML = '<p class="error-message">Failed to load tools: ' + error.message + '</p>';
    }
};

console.log('🔧 Setting up tools sidebar...');

document.addEventListener('DOMContentLoaded', () => {
    const sidebarFooterItems = [
        {
            btn: document.getElementById('actionsToggleBtn'),
            content: document.getElementById('sidebarActionsContent'),
            block: document.getElementById('sidebarActionBlock'),
        },
        {
            btn: document.getElementById('infoToggleBtn'),
            content: document.getElementById('sidebarInfoContent'),
            block: document.getElementById('sidebarInfoBlock'),
        },
        {
            btn: document.getElementById('guideToggleBtn'),
            content: document.getElementById('sidebarGuideContent'),
            block: document.getElementById('sidebarGuideBlock'),
        },
    ].filter((item) => item.btn && item.content && item.block);

    if (sidebarFooterItems.length > 0) {
        const setSidebarFooterState = (activeBtn = null) => {
            sidebarFooterItems.forEach(({ btn, content, block }) => {
                const isActive = btn === activeBtn;
                btn.setAttribute('aria-expanded', isActive ? 'true' : 'false');
                btn.classList.toggle('active', isActive);
                content.hidden = !isActive;
                block.hidden = !isActive;
                block.classList.toggle('open', isActive);
            });
        };

        setSidebarFooterState();

        sidebarFooterItems.forEach(({ btn }) => {
            btn.addEventListener('click', () => {
                const isExpanded = btn.getAttribute('aria-expanded') === 'true';
                setSidebarFooterState(isExpanded ? null : btn);
            });
        });
    }

    // Refresh tools button
    const refreshBtn = document.getElementById('refreshToolsSidebarBtn');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', () => window.loadToolsSidebar());
    }

    // Collapse / expand sidebar
    const collapseBtn = document.getElementById('collapseSidebarBtn');
    const sidebar = document.getElementById('toolsSidebar');
    if (collapseBtn && sidebar) {
        const syncSidebarCollapseButton = () => {
            const isCollapsed = sidebar.classList.contains('collapsed');
            collapseBtn.textContent = isCollapsed ? '◀' : '▶';
            collapseBtn.title = isCollapsed ? 'Expand sidebar' : 'Collapse sidebar';
            collapseBtn.setAttribute('aria-label', isCollapsed ? 'Expand sidebar' : 'Collapse sidebar');
        };

        collapseBtn.addEventListener('click', () => {
            sidebar.classList.toggle('collapsed');
            const isCollapsed = sidebar.classList.contains('collapsed');
            syncSidebarCollapseButton();
            try { localStorage.setItem('sidebarCollapsed', isCollapsed ? '1' : '0'); } catch (e) {}
        });
        // Restore persisted state
        try {
            if (localStorage.getItem('sidebarCollapsed') === '1') {
                sidebar.classList.add('collapsed');
            }
        } catch (e) {}
        syncSidebarCollapseButton();
    }

    // Client-side search / filter (no API calls)
    const searchInput = document.getElementById('toolsSearchInput');
    if (searchInput) {
        searchInput.addEventListener('input', (e) => {
            filterTools(e.target.value.trim().toLowerCase());
        });
    }

    window.loadToolsSidebar();
});

// Live clock
(function startClock() {
    const dateEl = document.getElementById('clockDate');
    const timeEl = document.getElementById('clockTime');
    if (!dateEl || !timeEl) return;
    const tick = () => {
        const now = new Date();
        dateEl.textContent = now.toLocaleDateString(undefined, { weekday: 'short', year: 'numeric', month: 'short', day: 'numeric' });
        timeEl.textContent = now.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    };
    tick();
    setInterval(tick, 1000);
}());

console.log('💬 Chat: Module loaded');
