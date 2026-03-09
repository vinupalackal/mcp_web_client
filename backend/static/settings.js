/**
 * MCP Client Web - Settings Modal Logic
 * Handles MCP server configuration, LLM setup, and tool management
 */

console.log('⚙️ Settings module initializing...');

// DOM Elements
const settingsModal = document.getElementById('settingsModal');
const settingsBtn = document.getElementById('settingsBtn');
const closeSettings = document.getElementById('closeSettings');
const tabButtons = document.querySelectorAll('.tab-button');
const addServerForm = document.getElementById('addServerForm');
const llmConfigForm = document.getElementById('llmConfigForm');
const authTypeSelect = document.getElementById('authType');
const llmProviderSelect = document.getElementById('llmProvider');
const refreshToolsBtn = document.getElementById('refreshToolsBtn');

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    console.log('⚙️ Settings: DOM loaded');
    initializeSettings();
    loadSettings();
});

function initializeSettings() {
    // Modal open/close
    settingsBtn.addEventListener('click', () => {
        settingsModal.classList.add('active');
        console.log('⚙️ Settings: Modal opened');
    });

    closeSettings.addEventListener('click', () => {
        settingsModal.classList.remove('active');
        console.log('⚙️ Settings: Modal closed');
        // Refresh tools sidebar when closing settings
        if (typeof window.loadToolsSidebar === 'function') {
            window.loadToolsSidebar();
        }
    });

    // Close on outside click
    settingsModal.addEventListener('click', (e) => {
        if (e.target === settingsModal) {
            settingsModal.classList.remove('active');
            // Refresh tools sidebar when closing settings
            if (typeof window.loadToolsSidebar === 'function') {
                window.loadToolsSidebar();
            }
        }
    });

    // Tab switching
    tabButtons.forEach(button => {
        button.addEventListener('click', () => {
            const tabName = button.dataset.tab;
            switchTab(tabName);
        });
    });

    // Auth type toggle
    authTypeSelect.addEventListener('change', () => {
        const authType = authTypeSelect.value;
        document.getElementById('bearerTokenGroup').style.display = 
            authType === 'bearer' ? 'block' : 'none';
        document.getElementById('apiKeyGroup').style.display = 
            authType === 'api_key' ? 'block' : 'none';
    });

    // LLM provider toggle
    llmProviderSelect.addEventListener('change', () => {
        const provider = llmProviderSelect.value;
        document.getElementById('llmApiKeyGroup').style.display = 
            provider === 'openai' ? 'block' : 'none';
        
        // Set default base URLs
        const baseUrlInput = document.getElementById('llmBaseUrl');
        if (provider === 'ollama' && !baseUrlInput.value) {
            baseUrlInput.value = 'http://127.0.0.1:11434';
        } else if (provider === 'openai' && !baseUrlInput.value) {
            baseUrlInput.value = 'https://api.openai.com';
        }
    });

    // Form submissions
    addServerForm.addEventListener('submit', handleAddServer);
    llmConfigForm.addEventListener('submit', handleSaveLLMConfig);
    refreshToolsBtn.addEventListener('click', handleRefreshTools);

    console.log('⚙️ Settings: Initialized');
}

function switchTab(tabName) {
    // Update buttons
    tabButtons.forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === tabName);
    });

    // Update content
    document.querySelectorAll('.tab-content').forEach(content => {
        content.classList.remove('active');
    });
    document.getElementById(tabName + 'Tab').classList.add('active');

    console.log(`⚙️ Settings: Switched to ${tabName} tab`);
}

// ============================================================================
// Server Management
// ============================================================================

async function handleAddServer(e) {
    e.preventDefault();
    console.log('⚙️ Settings: Adding server...');

    const serverData = {
        alias: document.getElementById('serverAlias').value,
        base_url: document.getElementById('serverUrl').value,
        auth_type: authTypeSelect.value,
        bearer_token: document.getElementById('bearerToken').value || null,
        api_key: document.getElementById('apiKey').value || null
    };

    try {
        console.log('🔌 API: POST /api/servers', serverData);
        const response = await fetch('/api/servers', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(serverData)
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || `HTTP ${response.status}`);
        }

        const server = await response.json();
        console.log('🔌 API: ← 201 Created', server);

        // Save to localStorage
        const servers = JSON.parse(localStorage.getItem('mcpServers') || '[]');
        servers.push(server);
        localStorage.setItem('mcpServers', JSON.stringify(servers));

        // Update UI
        renderServersList();
        addServerForm.reset();
        showSuccess('Server added successfully!');

    } catch (error) {
        console.error('⚙️ Settings: Add server failed', error);
        showFormError(addServerForm, error.message);
    }
}

function renderServersList() {
    const servers = JSON.parse(localStorage.getItem('mcpServers') || '[]');
    const serversList = document.getElementById('serversList');

    if (servers.length === 0) {
        serversList.innerHTML = '<p class="empty-state">No servers configured yet.</p>';
        return;
    }

    serversList.innerHTML = servers.map(server => `
        <div class="server-item">
            <div class="server-info">
                <div class="server-name">${server.alias}</div>
                <div class="server-url">${server.base_url}</div>
            </div>
            <button class="btn btn-danger btn-sm" onclick="deleteServer('${server.server_id}')">
                Delete
            </button>
        </div>
    `).join('');
}

async function deleteServer(serverId) {
    if (!confirm('Delete this server?')) return;

    console.log(`⚙️ Settings: Deleting server ${serverId}`);

    try {
        console.log(`🔌 API: DELETE /api/servers/${serverId}`);
        const response = await fetch(`/api/servers/${serverId}`, {
            method: 'DELETE'
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        console.log('🔌 API: ← 200 OK');

        // Remove from localStorage
        let servers = JSON.parse(localStorage.getItem('mcpServers') || '[]');
        servers = servers.filter(s => s.server_id !== serverId);
        localStorage.setItem('mcpServers', JSON.stringify(servers));

        // Update UI
        renderServersList();
        showSuccess('Server deleted');

    } catch (error) {
        console.error('⚙️ Settings: Delete failed', error);
        alert('Failed to delete server: ' + error.message);
    }
}

async function handleRefreshTools() {
    console.log('🔧 Tools: Refreshing...');
    refreshToolsBtn.disabled = true;
    refreshToolsBtn.textContent = '🔄 Refreshing...';

    try {
        // Sync servers to backend first (in case backend restarted)
        await syncServersToBackend();
        
        console.log('🔌 API: POST /api/servers/refresh-tools');
        const response = await fetch('/api/servers/refresh-tools', {
            method: 'POST'
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const result = await response.json();
        console.log('🔌 API: ← 200 OK', result);

        // Fetch tools
        await loadTools();
        
        // Refresh the tools sidebar on the main page
        if (typeof window.loadToolsSidebar === 'function') {
            await window.loadToolsSidebar();
            console.log('🔧 Tools sidebar refreshed');
        }
        
        if (result.total_tools === 0) {
            showSuccess('No tools discovered. Make sure your MCP servers are running.');
        } else {
            showSuccess(`Discovered ${result.total_tools} tools from ${result.servers_refreshed} servers`);
        }
        
        // Show errors if any
        if (result.errors && result.errors.length > 0) {
            console.warn('🔧 Tools: Errors during refresh:', result.errors);
            alert('Some servers failed:\n' + result.errors.join('\n'));
        }

    } catch (error) {
        console.error('🔧 Tools: Refresh failed', error);
        alert('Failed to refresh tools: ' + error.message);
    } finally {
        refreshToolsBtn.disabled = false;
        refreshToolsBtn.textContent = '🔄 Refresh Tools';
    }
}

async function loadTools() {
try {
        const response = await fetch('/api/tools');
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const tools = await response.json();
        
        console.log(`🔧 Loaded ${tools.length} tools`);

        renderToolsList(tools);

    } catch (error) {
        console.error('🔧 Tools: Load failed', error);
    }
}

function renderToolsList(tools) {
    const toolsList = document.getElementById('toolsList');

    if (tools.length === 0) {
        toolsList.innerHTML = '<p class="empty-state">No tools discovered yet. Add servers and refresh tools.</p>';
        return;
    }

    // Group by server
    const byServer = tools.reduce((acc, tool) => {
        if (!acc[tool.server_alias]) {
            acc[tool.server_alias] = [];
        }
        acc[tool.server_alias].push(tool);
        return acc;
    }, {});

    toolsList.innerHTML = Object.entries(byServer).map(([server, tools]) => `
        <div class="server-tools">
            <h4>${server} <span class="tool-count">${tools.length}</span></h4>
            ${tools.map(tool => `
                <div class="tool-item">
                    <div class="tool-info">
                        <div class="tool-name">${tool.name}</div>
                        <div class="tool-description">${tool.description}</div>
                    </div>
                </div>
            `).join('')}
        </div>
    `).join('');
}

// ============================================================================
// LLM Configuration
// ============================================================================

async function handleSaveLLMConfig(e) {
    e.preventDefault();
    console.log('⚙️ Settings: Saving LLM config...');

    const llmConfig = {
        provider: document.getElementById('llmProvider').value,
        model: document.getElementById('llmModel').value,
        base_url: document.getElementById('llmBaseUrl').value,
        api_key: document.getElementById('llmApiKey').value || null,
        temperature: parseFloat(document.getElementById('llmTemperature').value)
    };

    try {
        console.log('🔌 API: POST /api/llm/config', llmConfig);
        const response = await fetch('/api/llm/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(llmConfig)
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const saved = await response.json();
        console.log('🔌 API: ← 200 OK', saved);

        // Save to localStorage
        localStorage.setItem('llmConfig', JSON.stringify(saved));
        showSuccess('LLM configuration saved!');

    } catch (error) {
        console.error('⚙️ Settings: Save LLM config failed', error);
        showFormError(llmConfigForm, error.message);
    }
}

function loadLLMConfig() {
    const config = JSON.parse(localStorage.getItem('llmConfig') || 'null');
    if (!config) return;

    document.getElementById('llmProvider').value = config.provider;
    document.getElementById('llmModel').value = config.model;
    document.getElementById('llmBaseUrl').value = config.base_url;
    document.getElementById('llmApiKey').value = config.api_key || '';
    document.getElementById('llmTemperature').value = config.temperature;

    // Trigger provider change to show/hide API key
    llmProviderSelect.dispatchEvent(new Event('change'));
}

async function syncLLMConfigToBackend() {
    const config = JSON.parse(localStorage.getItem('llmConfig') || 'null');
    
    if (!config) {
        console.log('⚙️ Settings: No LLM config to sync');
        return;
    }
    
    console.log('⚙️ Settings: Syncing LLM config to backend...');
    
    try {
        const response = await fetch('/api/llm/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        });
        
        if (response.ok) {
            console.log('✓ LLM config synced');
        } else {
            console.warn('⚠️ Failed to sync LLM config:', response.status);
        }
    } catch (error) {
        console.error('✗ Failed to sync LLM config:', error);
    }
}

// ============================================================================
// Settings Loader
// ============================================================================

async function loadSettings() {
    console.log('⚙️ Settings: Loading from localStorage...');
    
    // Sync servers from localStorage to backend
    await syncServersToBackend();
    
    // Sync LLM config from localStorage to backend
    await syncLLMConfigToBackend();
    
    renderServersList();
    loadLLMConfig();
    loadTools();
}

async function syncServersToBackend() {
    const servers = JSON.parse(localStorage.getItem('mcpServers') || '[]');
    
    if (servers.length === 0) {
        console.log('⚙️ Settings: No servers to sync');
        return;
    }
    
    console.log(`⚙️ Settings: Syncing ${servers.length} servers to backend...`);
    
    for (const server of servers) {
        try {
            // POST each server to backend
            const response = await fetch('/api/servers', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(server)
            });
            
            if (response.ok) {
                console.log(`✓ Synced: ${server.alias}`);
            } else if (response.status === 409) {
                // Server already exists, that's fine
                console.log(`✓ Already exists: ${server.alias}`);
            }
        } catch (error) {
            console.error(`✗ Failed to sync ${server.alias}:`, error);
        }
    }
}

// ============================================================================
// UI Helpers
// ============================================================================

function showFormError(form, message) {
    let errorDiv = form.querySelector('.error-message');
    if (!errorDiv) {
        errorDiv = document.createElement('div');
        errorDiv.classList.add('error-message');
        form.appendChild(errorDiv);
    }
    errorDiv.textContent = message;
    setTimeout(() => errorDiv.remove(), 5000);
}

function showSuccess(message) {
    const successDiv = document.createElement('div');
    successDiv.classList.add('success-message');
    successDiv.textContent = message;
    
    const modalBody = document.querySelector('.modal-body');
    modalBody.insertBefore(successDiv, modalBody.firstChild);
    
    setTimeout(() => successDiv.remove(), 3000);
}

// Make functions available globally
window.deleteServer = deleteServer;
window.syncServersToBackend = syncServersToBackend;
window.syncLLMConfigToBackend = syncLLMConfigToBackend;

console.log('⚙️ Settings: Module loaded');
