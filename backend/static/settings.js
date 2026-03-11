/**
 * MCP Client Web - Settings Modal Logic
 * Handles MCP server configuration, standard LLM setup, enterprise gateway setup, and tool management.
 */

console.log('⚙️ Settings module initializing...');

const ENTERPRISE_DEFAULT_MODELS = [
    { model_id: 'claude-3-7-sonnet', provider: 'AWS', type: 'LLM', is_default: true },
    { model_id: 'claude-4-5-haiku', provider: 'AWS', type: 'LLM', is_default: true },
    { model_id: 'claude-4-5-sonnet', provider: 'AWS', type: 'LLM', is_default: true },
    { model_id: 'claude-4-6-sonnet', provider: 'AWS', type: 'LLM', is_default: true },
    { model_id: 'claude-4-sonnet', provider: 'AWS', type: 'LLM', is_default: true },
    { model_id: 'nova-lite', provider: 'AWS', type: 'LLM', is_default: true },
    { model_id: 'nova-micro', provider: 'AWS', type: 'LLM', is_default: true },
    { model_id: 'nova-pro', provider: 'AWS', type: 'LLM', is_default: true },
    { model_id: 'gpt-41', provider: 'Azure', type: 'LLM', is_default: true },
    { model_id: 'gpt-4o', provider: 'Azure', type: 'LLM', is_default: true },
    { model_id: 'gpt-5-1', provider: 'Azure', type: 'LLM', is_default: true },
    { model_id: 'gpt-5-2', provider: 'Azure', type: 'LLM', is_default: true },
    { model_id: 'gpt-5-mini', provider: 'Azure', type: 'LLM', is_default: true },
    { model_id: 'gpt-5-nano', provider: 'Azure', type: 'LLM', is_default: true },
    { model_id: 'o4-mini', provider: 'Azure', type: 'LLM', is_default: true },
    { model_id: 'text-embedding-3-large', provider: 'Azure', type: 'Embedding', is_default: true },
];

const STORAGE_KEYS = {
// Non-sensitive UI preferences only — credentials and configs live on the server
    gatewayMode: 'llmGatewayMode',
    enterpriseSelectedModel: 'enterpriseSelectedModel',
    enterpriseCustomModels: 'enterpriseCustomModels',
    autoRefreshServerHealth: 'autoRefreshServerHealth',
    includeHistory: 'includeHistory',
};

const SERVER_HEALTH_REFRESH_INTERVAL_MS = 30000;
let serverHealthRefreshIntervalId = null;
let isRefreshingServerHealth = false;
let pendingServerHealthRefresh = false;

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
const llmGatewayModeInputs = document.querySelectorAll('input[name="llmGatewayMode"]');
const standardLlmPanel = document.getElementById('standardLlmPanel');
const enterpriseLlmPanel = document.getElementById('enterpriseLlmPanel');
const enterpriseModelSelect = document.getElementById('enterpriseModel');
const addEnterpriseModelBtn = document.getElementById('addEnterpriseModelBtn');
const enterpriseModelForm = document.getElementById('enterpriseModelForm');
const enterpriseSaveModelBtn = document.getElementById('enterpriseSaveModelBtn');
const enterpriseCancelModelBtn = document.getElementById('enterpriseCancelModelBtn');
const fetchEnterpriseTokenBtn = document.getElementById('fetchEnterpriseTokenBtn');
const enterpriseTokenStatus = document.getElementById('enterpriseTokenStatus');
const refreshServerHealthBtn = document.getElementById('refreshServerHealthBtn');
const autoRefreshHealthToggle = document.getElementById('autoRefreshHealthToggle');
const includeHistoryToggle = document.getElementById('includeHistoryToggle');

document.addEventListener('DOMContentLoaded', () => {
    console.log('⚙️ Settings: DOM loaded');
    initializeSettings();
    window.setTimeout(() => {
        loadServersFromBackend();
    }, 0);
    loadLLMConfigFromBackend();
    loadEnterpriseTokenStatus();
    loadTools();
});

function initializeSettings() {
    settingsBtn?.addEventListener('click', () => {
        settingsModal.classList.add('active');
        console.log('⚙️ Settings: Modal opened');
    });

    closeSettings?.addEventListener('click', closeSettingsModal);

    settingsModal?.addEventListener('click', (e) => {
        if (e.target === settingsModal) {
            closeSettingsModal();
        }
    });

    tabButtons.forEach(button => {
        button.addEventListener('click', () => switchTab(button.dataset.tab));
    });

    authTypeSelect?.addEventListener('change', updateServerAuthUI);
    llmProviderSelect?.addEventListener('change', updateStandardProviderUI);

    llmGatewayModeInputs.forEach(input => {
        input.addEventListener('change', () => setGatewayMode(input.value));
    });

    addServerForm?.addEventListener('submit', handleAddServer);
    llmConfigForm?.addEventListener('submit', handleSaveLLMConfig);
    refreshToolsBtn?.addEventListener('click', handleRefreshTools);
    refreshServerHealthBtn?.addEventListener('click', () => refreshServerHealth());
    addEnterpriseModelBtn?.addEventListener('click', () => toggleEnterpriseModelForm(true));
    enterpriseSaveModelBtn?.addEventListener('click', saveEnterpriseCustomModel);
    enterpriseCancelModelBtn?.addEventListener('click', () => toggleEnterpriseModelForm(false));
    fetchEnterpriseTokenBtn?.addEventListener('click', handleFetchEnterpriseToken);
    autoRefreshHealthToggle?.addEventListener('change', (event) => {
        setServerHealthAutoRefresh(event.target.checked);
    });

    updateServerAuthUI();
    updateStandardProviderUI();
    renderEnterpriseModelOptions();
    renderEnterpriseModelsList();
    setGatewayMode(getGatewayMode(), false);
    initializeServerHealthAutoRefresh();
    initializeChatHistoryPreference();

    console.log('⚙️ Settings: Initialized');
}

function initializeChatHistoryPreference() {
    const includeHistory = localStorage.getItem(STORAGE_KEYS.includeHistory) !== 'false';
    if (includeHistoryToggle) {
        includeHistoryToggle.checked = includeHistory;
        includeHistoryToggle.addEventListener('change', (event) => {
            localStorage.setItem(STORAGE_KEYS.includeHistory, event.target.checked ? 'true' : 'false');
        });
    }
}

function closeSettingsModal() {
    settingsModal.classList.remove('active');
    console.log('⚙️ Settings: Modal closed');
    if (typeof window.loadToolsSidebar === 'function') {
        window.loadToolsSidebar();
    }
}

function switchTab(tabName) {
    tabButtons.forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === tabName);
    });

    document.querySelectorAll('.tab-content').forEach(content => {
        content.classList.remove('active');
    });

    const activeTab = document.getElementById(`${tabName}Tab`);
    if (activeTab) {
        activeTab.classList.add('active');
    }

    console.log(`⚙️ Settings: Switched to ${tabName} tab`);
}

function updateServerAuthUI() {
    const authType = authTypeSelect?.value;
    const bearerTokenGroup = document.getElementById('bearerTokenGroup');
    const apiKeyGroup = document.getElementById('apiKeyGroup');
    if (bearerTokenGroup) {
        bearerTokenGroup.style.display = authType === 'bearer' ? 'block' : 'none';
    }
    if (apiKeyGroup) {
        apiKeyGroup.style.display = authType === 'api_key' ? 'block' : 'none';
    }
}

function updateStandardProviderUI() {
    const provider = llmProviderSelect?.value;
    const apiKeyGroup = document.getElementById('llmApiKeyGroup');
    const baseUrlInput = document.getElementById('llmBaseUrl');

    if (apiKeyGroup) {
        apiKeyGroup.style.display = provider === 'openai' ? 'block' : 'none';
    }

    if (!baseUrlInput || !provider) {
        return;
    }

    if (provider === 'ollama' && !baseUrlInput.value) {
        baseUrlInput.value = 'http://127.0.0.1:11434';
    } else if (provider === 'openai' && !baseUrlInput.value) {
        baseUrlInput.value = 'https://api.openai.com';
    }
}

function getGatewayMode() {
    const selected = Array.from(llmGatewayModeInputs).find(input => input.checked);
    return selected?.value || localStorage.getItem(STORAGE_KEYS.gatewayMode) || 'standard';
}

function setGatewayMode(mode, persist = true) {
    const standardInput = document.getElementById('llmGatewayModeStandard');
    const enterpriseInput = document.getElementById('llmGatewayModeEnterprise');

    if (standardInput) standardInput.checked = mode === 'standard';
    if (enterpriseInput) enterpriseInput.checked = mode === 'enterprise';

    if (standardLlmPanel) {
        standardLlmPanel.style.display = mode === 'standard' ? 'block' : 'none';
    }
    if (enterpriseLlmPanel) {
        enterpriseLlmPanel.style.display = mode === 'enterprise' ? 'block' : 'none';
    }

    updateLlmFieldRequirements(mode);

    if (persist) {
        localStorage.setItem(STORAGE_KEYS.gatewayMode, mode);
    }

    if (mode === 'enterprise') {
        renderEnterpriseModelOptions(localStorage.getItem(STORAGE_KEYS.enterpriseSelectedModel) || 'gpt-4o');
        renderEnterpriseModelsList();
        loadEnterpriseTokenStatus();
    }
}

// ============================================================================
// Backend Config Loaders  (credentials never leave the server)
// ============================================================================

async function loadLLMConfigFromBackend() {
    try {
        const response = await fetch('/api/llm/config');
        if (!response.ok) {
            if (response.status !== 404) {
                throw new Error(`HTTP ${response.status}`);
            }
            loadLLMConfig(null);
            return;
        }
        const config = await response.json();
        loadLLMConfig(config);
    } catch (error) {
        console.error('⚙️ Settings: Failed to load LLM config from backend', error);
        loadLLMConfig(null);
    }
}

async function loadServersFromBackend() {
    try {
        const response = await fetch('/api/servers');
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const servers = await response.json();
        renderServersList(servers);
    } catch (error) {
        console.error('⚙️ Settings: Failed to load servers from backend', error);
        renderServersList([]);
    }
}

function initializeServerHealthAutoRefresh() {
    const enabled = localStorage.getItem(STORAGE_KEYS.autoRefreshServerHealth) === 'true';
    if (autoRefreshHealthToggle) {
        autoRefreshHealthToggle.checked = enabled;
    }
    setServerHealthAutoRefresh(enabled, false);
}

function setServerHealthAutoRefresh(enabled, persist = true) {
    if (persist) {
        localStorage.setItem(STORAGE_KEYS.autoRefreshServerHealth, enabled ? 'true' : 'false');
    }

    if (autoRefreshHealthToggle) {
        autoRefreshHealthToggle.checked = enabled;
    }

    if (serverHealthRefreshIntervalId) {
        clearInterval(serverHealthRefreshIntervalId);
        serverHealthRefreshIntervalId = null;
    }

    if (enabled) {
        serverHealthRefreshIntervalId = window.setInterval(() => {
            refreshServerHealth({ silent: true });
        }, SERVER_HEALTH_REFRESH_INTERVAL_MS);
        refreshServerHealth({ silent: true });
    }
}

function formatLastHealthCheck(timestamp) {
    if (!timestamp) {
        return 'Not checked yet';
    }

    const date = new Date(timestamp);
    if (Number.isNaN(date.getTime())) {
        return 'Not checked yet';
    }

    return date.toLocaleString();
}

function updateLlmFieldRequirements(mode) {
    const standardRequired = mode === 'standard';
    const enterpriseRequired = mode === 'enterprise';

    document.getElementById('llmProvider')?.toggleAttribute('required', standardRequired);
    document.getElementById('llmModel')?.toggleAttribute('required', standardRequired);
    document.getElementById('llmBaseUrl')?.toggleAttribute('required', standardRequired);

    document.getElementById('enterpriseModel')?.toggleAttribute('required', enterpriseRequired);
    document.getElementById('enterpriseGatewayUrl')?.toggleAttribute('required', enterpriseRequired);
    document.getElementById('enterpriseClientId')?.toggleAttribute('required', enterpriseRequired);
    document.getElementById('enterpriseClientSecret')?.toggleAttribute('required', enterpriseRequired);
    document.getElementById('enterpriseTokenEndpoint')?.toggleAttribute('required', enterpriseRequired);
}

function getEnterpriseCustomModels() {
    const value = safeParseStoredJson(STORAGE_KEYS.enterpriseCustomModels, []);
    return Array.isArray(value) ? value : [];
}

function getEnterpriseModels() {
    return [...ENTERPRISE_DEFAULT_MODELS, ...getEnterpriseCustomModels()];
}

function renderEnterpriseModelOptions(selectedModelId) {
    if (!enterpriseModelSelect) {
        return;
    }

    const models = getEnterpriseModels();
    enterpriseModelSelect.innerHTML = models.map(model => {
        const suffix = model.type === 'Embedding' ? ' [embedding]' : '';
        return `<option value="${model.model_id}">${model.model_id} (${model.provider})${suffix}</option>`;
    }).join('');

    enterpriseModelSelect.value = selectedModelId || localStorage.getItem(STORAGE_KEYS.enterpriseSelectedModel) || 'gpt-4o';
}

function renderEnterpriseModelsList() {
    const list = document.getElementById('enterpriseModelsList');
    if (!list) {
        return;
    }

    const customModels = getEnterpriseCustomModels();
    if (customModels.length === 0) {
        list.innerHTML = '<p class="empty-state">Using default enterprise model catalog.</p>';
        return;
    }

    list.innerHTML = customModels.map(model => `
        <div class="enterprise-model-item">
            <div>
                <strong>${model.model_id}</strong>
                <span class="enterprise-model-meta">${model.provider} · ${model.type}</span>
            </div>
            <button type="button" class="btn btn-danger btn-sm" onclick="window.removeEnterpriseCustomModel('${model.model_id}')">×</button>
        </div>
    `).join('');
}

function toggleEnterpriseModelForm(show) {
    if (!enterpriseModelForm) {
        return;
    }

    enterpriseModelForm.style.display = show ? 'block' : 'none';
    if (!show) {
        document.getElementById('enterpriseCustomModelId').value = '';
        document.getElementById('enterpriseCustomModelProvider').value = '';
        document.getElementById('enterpriseCustomModelType').value = 'LLM';
    }
}

function saveEnterpriseCustomModel() {
    const modelId = document.getElementById('enterpriseCustomModelId').value.trim();
    const provider = document.getElementById('enterpriseCustomModelProvider').value.trim();
    const type = document.getElementById('enterpriseCustomModelType').value;

    if (!modelId || !provider) {
        showFormError(llmConfigForm, 'Custom enterprise model requires both model ID and provider');
        return;
    }

    const allModels = getEnterpriseModels();
    if (allModels.some(model => model.model_id === modelId)) {
        showFormError(llmConfigForm, `Model '${modelId}' already exists`);
        return;
    }

    const customModels = getEnterpriseCustomModels();
    customModels.push({ model_id: modelId, provider, type, is_default: false });
    localStorage.setItem(STORAGE_KEYS.enterpriseCustomModels, JSON.stringify(customModels));
    localStorage.setItem(STORAGE_KEYS.enterpriseSelectedModel, modelId);

    renderEnterpriseModelOptions(modelId);
    renderEnterpriseModelsList();
    toggleEnterpriseModelForm(false);
}

function removeEnterpriseCustomModel(modelId) {
    const filtered = getEnterpriseCustomModels().filter(model => model.model_id !== modelId);
    localStorage.setItem(STORAGE_KEYS.enterpriseCustomModels, JSON.stringify(filtered));

    const selectedModel = localStorage.getItem(STORAGE_KEYS.enterpriseSelectedModel);
    if (selectedModel === modelId) {
        localStorage.setItem(STORAGE_KEYS.enterpriseSelectedModel, 'gpt-4o');
    }

    renderEnterpriseModelOptions(localStorage.getItem(STORAGE_KEYS.enterpriseSelectedModel) || 'gpt-4o');
    renderEnterpriseModelsList();
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
        api_key: document.getElementById('apiKey').value || null,
    };

    try {
        console.log('🔌 API: POST /api/servers', { ...serverData, bearer_token: serverData.bearer_token ? '[REDACTED]' : null, api_key: serverData.api_key ? '[REDACTED]' : null });
        const response = await fetch('/api/servers', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(serverData),
        });

        if (!response.ok) {
            const error = await safeReadJson(response);
            throw new Error(error.detail || `HTTP ${response.status}`);
        }

        const server = await response.json();
        await response.json();  // consume response body
        await loadServersFromBackend();
        addServerForm.reset();
        updateServerAuthUI();
        showSuccess('Server added successfully!');
    } catch (error) {
        console.error('⚙️ Settings: Add server failed', error);
        showFormError(addServerForm, error.message);
    }
}

function renderServersList(servers) {
    const serversList = document.getElementById('serversList');

    if (!Array.isArray(servers) || servers.length === 0) {
        serversList.innerHTML = '<p class="empty-state">No servers configured yet.</p>';
        return;
    }

    serversList.innerHTML = servers.map(server => `
        <div class="server-item">
            <div class="server-info">
                <div class="server-name">
                    <span class="server-health-dot ${server.health_status || 'unknown'}" title="${server.health_status || 'unknown'} · Last checked: ${formatLastHealthCheck(server.last_health_check)}"></span>
                    ${server.alias}
                </div>
                <div class="server-url">${server.base_url}</div>
                <div class="server-url">Status: ${server.health_status || 'unknown'}</div>
                <div class="server-health-meta">Last checked: ${formatLastHealthCheck(server.last_health_check)}</div>
            </div>
            <button class="btn btn-danger btn-sm" onclick="deleteServer('${server.server_id}')">Delete</button>
        </div>
    `).join('');
}

async function refreshServerHealth({ silent = false } = {}) {
    if (isRefreshingServerHealth) {
        pendingServerHealthRefresh = true;
        return;
    }

    isRefreshingServerHealth = true;
    if (refreshServerHealthBtn) {
        refreshServerHealthBtn.disabled = true;
        refreshServerHealthBtn.textContent = '🩺 Checking...';
    }

    try {
        const response = await fetch('/api/servers/refresh-health', { method: 'POST' });
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const result = await response.json();
        renderServersList(result.servers || []);

        if (!silent) {
            showSuccess(`Health checked: ${result.healthy_servers}/${result.servers_checked} healthy`);
        }

        if (result.errors?.length && !silent) {
            alert('Some health checks failed:\n' + result.errors.join('\n'));
        }
    } catch (error) {
        console.error('⚙️ Settings: Health refresh failed', error);
        if (!silent) {
            alert('Failed to refresh server health: ' + error.message);
        }
    } finally {
        isRefreshingServerHealth = false;
        if (refreshServerHealthBtn) {
            refreshServerHealthBtn.disabled = false;
            refreshServerHealthBtn.textContent = '🩺 Check Health';
        }

        if (pendingServerHealthRefresh) {
            pendingServerHealthRefresh = false;
            refreshServerHealth({ silent: true });
        }
    }
}

async function deleteServer(serverId) {
    if (!confirm('Delete this server?')) return;

    try {
        console.log(`🔌 API: DELETE /api/servers/${serverId}`);
        const response = await fetch(`/api/servers/${serverId}`, { method: 'DELETE' });
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        await loadServersFromBackend();
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
        const response = await fetch('/api/servers/refresh-tools', { method: 'POST' });
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const result = await response.json();
        await loadTools();
        await loadServersFromBackend();

        if (typeof window.loadToolsSidebar === 'function') {
            await window.loadToolsSidebar();
            console.log('🔧 Tools sidebar refreshed');
        }

        if (result.total_tools === 0) {
            showSuccess('No tools discovered. Make sure your MCP servers are running.');
        } else {
            showSuccess(`Discovered ${result.total_tools} tools from ${result.servers_refreshed} servers`);
        }

        if (result.errors?.length) {
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

    const byServer = tools.reduce((acc, tool) => {
        if (!acc[tool.server_alias]) {
            acc[tool.server_alias] = [];
        }
        acc[tool.server_alias].push(tool);
        return acc;
    }, {});

    toolsList.innerHTML = Object.entries(byServer).map(([server, serverTools]) => `
        <div class="server-tools">
            <h4>${server} <span class="tool-count">${serverTools.length}</span></h4>
            ${serverTools.map(tool => `
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
    const mode = getGatewayMode();
    const temperature = parseFloat(document.getElementById('llmTemperature').value || '0.7');
    const standardTimeoutMs = parseInt(document.getElementById('llmTimeoutMs').value || '180000', 10);
    const enterpriseTimeoutMs = parseInt(document.getElementById('enterpriseLlmTimeoutMs').value || '180000', 10);

    let llmConfig;
    if (mode === 'enterprise') {
        llmConfig = {
            gateway_mode: 'enterprise',
            provider: 'enterprise',
            model: enterpriseModelSelect.value,
            base_url: document.getElementById('enterpriseGatewayUrl').value,
            auth_method: document.getElementById('enterpriseAuthMethod').value,
            client_id: document.getElementById('enterpriseClientId').value,
            client_secret: document.getElementById('enterpriseClientSecret').value,
            token_endpoint_url: document.getElementById('enterpriseTokenEndpoint').value,
            temperature,
            llm_timeout_ms: enterpriseTimeoutMs,
        };
    } else {
        llmConfig = {
            gateway_mode: 'standard',
            provider: document.getElementById('llmProvider').value,
            model: document.getElementById('llmModel').value,
            base_url: document.getElementById('llmBaseUrl').value,
            api_key: document.getElementById('llmApiKey').value || null,
            temperature,
            llm_timeout_ms: standardTimeoutMs,
        };
    }

    try {
        console.log('🔌 API: POST /api/llm/config', redactLlmConfigForLog(llmConfig));
        const response = await fetch('/api/llm/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(llmConfig),
        });

        if (!response.ok) {
            const error = await safeReadJson(response);
            throw new Error(error.detail || `HTTP ${response.status}`);
        }

        const saved = await response.json();
        // Store only non-sensitive UI preferences — credentials stay on the server
        localStorage.setItem(STORAGE_KEYS.gatewayMode, mode);
        if (mode === 'enterprise') {
            localStorage.setItem(STORAGE_KEYS.enterpriseSelectedModel, saved.model);
        }

        showSuccess('LLM configuration saved!');
        if (mode === 'enterprise') {
            await loadEnterpriseTokenStatus();
        }
    } catch (error) {
        console.error('⚙️ Settings: Save LLM config failed', error);
        showFormError(llmConfigForm, error.message);
    }
}

function loadLLMConfig(config) {
    // config is supplied by loadLLMConfigFromBackend — never read sensitive config from localStorage
    const storedGatewayMode = localStorage.getItem(STORAGE_KEYS.gatewayMode);
    const inferredMode = config?.provider === 'enterprise' || config?.gateway_mode === 'enterprise'
        ? 'enterprise'
        : (storedGatewayMode === 'enterprise' || storedGatewayMode === 'standard' ? storedGatewayMode : 'standard');

    setGatewayMode(inferredMode, false);
    renderEnterpriseModelOptions(localStorage.getItem(STORAGE_KEYS.enterpriseSelectedModel) || config?.model || 'gpt-4o');
    renderEnterpriseModelsList();

    document.getElementById('llmTemperature').value = config?.temperature ?? '0.7';
    document.getElementById('llmTimeoutMs').value = config?.llm_timeout_ms ?? '180000';
    document.getElementById('enterpriseLlmTimeoutMs').value = config?.llm_timeout_ms ?? '180000';

    if (config?.provider === 'enterprise') {
        document.getElementById('enterpriseGatewayUrl').value = config.base_url || '';
        document.getElementById('enterpriseAuthMethod').value = config.auth_method || 'bearer';
        document.getElementById('enterpriseClientId').value = config.client_id || '';
        document.getElementById('enterpriseClientSecret').value = config.client_secret || '';
        document.getElementById('enterpriseTokenEndpoint').value = config.token_endpoint_url || '';
        enterpriseModelSelect.value = config.model || localStorage.getItem(STORAGE_KEYS.enterpriseSelectedModel) || 'gpt-4o';
    } else if (config) {
        document.getElementById('llmProvider').value = config.provider;
        document.getElementById('llmModel').value = config.model;
        document.getElementById('llmBaseUrl').value = config.base_url;
        document.getElementById('llmApiKey').value = config.api_key || '';
        llmProviderSelect?.dispatchEvent(new Event('change'));
    }
}

async function handleFetchEnterpriseToken() {
    const request = {
        token_endpoint_url: document.getElementById('enterpriseTokenEndpoint').value,
        client_id: document.getElementById('enterpriseClientId').value,
        client_secret: document.getElementById('enterpriseClientSecret').value,
    };

    try {
        fetchEnterpriseTokenBtn.disabled = true;
        fetchEnterpriseTokenBtn.textContent = 'Fetching...';

        console.log('🔌 API: POST /api/enterprise/token', {
            token_endpoint_url: request.token_endpoint_url,
            client_id: request.client_id ? '[REDACTED]' : '',
            client_secret: request.client_secret ? '[REDACTED]' : '',
        });

        const response = await fetch('/api/enterprise/token', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(request),
        });

        if (!response.ok) {
            const error = await safeReadJson(response);
            throw new Error(error.detail || `HTTP ${response.status}`);
        }

        showSuccess('Enterprise token fetched and cached!');
        await loadEnterpriseTokenStatus();
    } catch (error) {
        console.error('⚙️ Settings: Enterprise token fetch failed', error);
        renderEnterpriseTokenStatus({ token_cached: false, error: error.message });
        showFormError(llmConfigForm, error.message);
    } finally {
        fetchEnterpriseTokenBtn.disabled = false;
        fetchEnterpriseTokenBtn.textContent = 'Fetch Token';
    }
}

async function loadEnterpriseTokenStatus() {
    if (!enterpriseTokenStatus) {
        return;
    }

    try {
        const response = await fetch('/api/enterprise/token/status');
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const status = await response.json();
        renderEnterpriseTokenStatus(status);
    } catch (error) {
        console.error('⚙️ Settings: Failed to load enterprise token status', error);
        renderEnterpriseTokenStatus({ token_cached: false, error: error.message });
    }
}

function renderEnterpriseTokenStatus(status) {
    if (!enterpriseTokenStatus) {
        return;
    }

    enterpriseTokenStatus.className = 'token-status-badge';

    if (status.token_cached) {
        enterpriseTokenStatus.classList.add('token-status-active');
        enterpriseTokenStatus.textContent = status.cached_at
            ? `Token active · cached ${new Date(status.cached_at).toLocaleString()}`
            : 'Token active';
        return;
    }

    enterpriseTokenStatus.classList.add('token-status-idle');
    enterpriseTokenStatus.textContent = status.error ? `Token unavailable · ${status.error}` : 'Token not fetched';
}

// ============================================================================
// Settings Loader
// ============================================================================

async function loadSettings() {
    console.log('⚙️ Settings: Loading from backend...');
    await loadServersFromBackend();
    await loadLLMConfigFromBackend();
    await loadEnterpriseTokenStatus();
    loadTools();
}

// ============================================================================
// UI Helpers
// ============================================================================

async function safeReadJson(response) {
    try {
        return await response.json();
    } catch {
        return {};
    }
}

function redactLlmConfigForLog(config) {
    return {
        ...config,
        api_key: config.api_key ? '[REDACTED]' : null,
        client_id: config.client_id ? '[REDACTED]' : null,
        client_secret: config.client_secret ? '[REDACTED]' : null,
    };
}

function safeParseStoredJson(key, fallback) {
    try {
        const raw = localStorage.getItem(key);
        return raw ? JSON.parse(raw) : fallback;
    } catch {
        return fallback;
    }
}

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

window.deleteServer = deleteServer;
window.removeEnterpriseCustomModel = removeEnterpriseCustomModel;

console.log('⚙️ Settings: Module loaded');
