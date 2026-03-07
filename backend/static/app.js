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
        
        console.log('💬 Chat: Response received');
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
    messageContent.textContent = content;

    messageWrapper.appendChild(messageContent);

    // Add tool execution indicators
    if (toolExecutions && toolExecutions.length > 0) {
        toolExecutions.forEach(exec => {
            const toolIndicator = document.createElement('div');
            toolIndicator.classList.add('tool-indicator');
            toolIndicator.textContent = `🔧 ${exec.tool} (${exec.duration_ms}ms)`;
            messageWrapper.appendChild(toolIndicator);
        });
    }

    chatMessages.appendChild(messageWrapper);
    scrollToBottom();
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

console.log('💬 Chat: Module loaded');
