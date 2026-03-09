/**
 * MCP Client Web - Chat Application Logic
 * Handles chat interface, message sending, and session management
 */

console.log('💬 Chat app initializing...');

// State
let currentSessionId = null;
let isProcessing = false;

// DOM Elements
const chatMessages = document.getElementById('chatMessages');
const messageInput = document.getElementById('messageInput');
const sendBtn = document.getElementById('sendBtn');
const newChatBtn = document.getElementById('newChatBtn');

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

    console.log('💬 Chat: Initialized');
}

async function createNewSession() {
    console.log('💬 Chat: Creating new session...');
    
    // Get LLM config from localStorage
    const llmConfig = JSON.parse(localStorage.getItem('llmConfig') || 'null');
    if (!llmConfig) {
        showError('Please configure LLM provider in Settings first');
        return;
    }

    // Get enabled servers from localStorage
    const servers = JSON.parse(localStorage.getItem('mcpServers') || '[]');
    const enabledServers = servers.map(s => s.alias);

    try {
        const response = await fetch('/api/sessions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                llm_config: llmConfig,
                enabled_servers: enabledServers
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

async function sendMessage() {
    const content = messageInput.value.trim();
    if (!content || isProcessing) return;

    console.log(`💬 Chat: Sending message: ${content.substring(0, 50)}...`);

    // Sync servers and LLM config from localStorage before sending
    // (in case backend was restarted and lost in-memory data)
    console.log('💬 Chat: Syncing servers and LLM config...');
    if (window.syncServersToBackend) {
        await window.syncServersToBackend();
    }
    if (window.syncLLMConfigToBackend) {
        await window.syncLLMConfigToBackend();
    }

    // Create session if needed
    if (!currentSessionId) {
        await createNewSession();
        if (!currentSessionId) return;
    }

    // Add user message to UI
    addMessage('user', content);
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
        addMessage('assistant', data.message.content, data.tool_executions);
        
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

function addMessage(role, content, toolExecutions = []) {
    const messageWrapper = document.createElement('div');
    messageWrapper.classList.add('message-wrapper', role);

    const messageContent = document.createElement('div');
    messageContent.classList.add('message-content');
    
    // Format content with line breaks and preserve formatting
    const formattedContent = formatMessageContent(content);
    messageContent.innerHTML = formattedContent;

    messageWrapper.appendChild(messageContent);

    // Add compact tools used summary
    if (toolExecutions && toolExecutions.length > 0) {
        const toolsSummary = document.createElement('div');
        toolsSummary.classList.add('tools-used-summary');
        const toolNames = toolExecutions.map(exec => {
            const successIcon = exec.success ? '✓' : '✗';
            return `<span class="tool-badge ${exec.success ? 'success' : 'error'}">${successIcon} ${exec.tool}</span>`;
        }).join(' ');
        toolsSummary.innerHTML = `<div class="tools-label">🔧 Tools Used:</div><div class="tools-badges">${toolNames}</div>`;
        messageWrapper.appendChild(toolsSummary);
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
            <span class="loading"></span> Thinking...
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

// Make this function global so settings.js can call it
window.loadToolsSidebar = async function() {
    console.log('🔧 Loading tools for sidebar...');
    const toolsSidebarContent = document.getElementById('toolsSidebarContent');
    
    if (!toolsSidebarContent) {
        console.error('❌ toolsSidebarContent element not found!');
        return;
    }
    
    try {
        const response = await fetch('/api/tools');
        console.log('🔧 API Response status:', response.status);
        
        if (!response.ok) {
            throw new Error(`Failed to load tools: ${response.status}`);
        }
        
        const tools = await response.json();
        console.log(`🔧 Loaded ${tools.length} tools`);
        
        if (tools.length === 0) {
            toolsSidebarContent.innerHTML = '<p class="empty-state">No tools discovered yet.<br>Add servers and refresh tools.</p>';
            return;
        }
        
        // Group tools by server
        const toolsByServer = {};
        tools.forEach(tool => {
            if (!toolsByServer[tool.server_alias]) {
                toolsByServer[tool.server_alias] = [];
            }
            toolsByServer[tool.server_alias].push(tool);
        });
        
        // Render tools
        let html = '';
        for (const [serverAlias, serverTools] of Object.entries(toolsByServer)) {
            serverTools.forEach(tool => {
                const paramsCount = tool.parameters?.properties 
                    ? Object.keys(tool.parameters.properties).length 
                    : 0;
                
                html += `
                    <div class="tool-item" title="${tool.description || ''}">
                        <div class="tool-name">${tool.name}</div>
                        ${tool.description ? `<div class="tool-description">${tool.description}</div>` : ''}
                        ${paramsCount > 0 ? `<div class="tool-params">${paramsCount} parameter${paramsCount > 1 ? 's' : ''}</div>` : ''}
                    </div>
                `;
            });
        }
        
        toolsSidebarContent.innerHTML = html;
        
    } catch (error) {
        console.error('❌ Error loading tools:', error);
        toolsSidebarContent.innerHTML = '<p class="error-message">Failed to load tools: ' + error.message + '</p>';
    }
}

// Initialize tools sidebar
console.log('🔧 Setting up tools sidebar...');

// Refresh tools sidebar button
document.addEventListener('DOMContentLoaded', () => {
    const refreshBtn = document.getElementById('refreshToolsSidebarBtn');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', () => {
            window.loadToolsSidebar();
        });
    }
    
    // Load tools on page load
    window.loadToolsSidebar();
});

console.log('💬 Chat: Module loaded');
