console.log('🧪 Tool tester initializing...');

const TOOL_TEST_PROMPTS_ENDPOINT = '/api/tools/test-prompts';
const TOOL_TEST_OUTPUT_ENDPOINT = '/api/tools/test-results-output';
const CHAT_PREFERENCE_STORAGE_KEY = 'includeHistory';
const TOOL_TEST_DEVICE_IDENTIFIER_STORAGE_KEY = 'toolTesterDeviceIdentifier';
const TOOL_TEST_DEVICE_IDENTIFIER_DEFAULT_TYPE = 'ip';

let currentSessionId = null;
let isProcessing = false;
let availableTools = [];
let promptExamples = new Map();

const darkModeBtn = document.getElementById('toolTesterDarkModeBtn');
const refreshBtn = document.getElementById('toolTesterRefreshBtn');
const testAllBtn = document.getElementById('toolTesterTestAllBtn');
const newSessionBtn = document.getElementById('toolTesterNewSessionBtn');
const clearResultsBtn = document.getElementById('toolTesterClearResultsBtn');
const searchInput = document.getElementById('toolTesterSearchInput');
const deviceIdentifierTypeSelect = document.getElementById('toolTesterDeviceIdentifierType');
const deviceIdentifierValueInput = document.getElementById('toolTesterDeviceIdentifierValue');
const statusEl = document.getElementById('toolTesterStatus');
const resultsProgressEl = document.getElementById('toolTesterResultsProgress');
const toolsListEl = document.getElementById('toolTesterToolsList');
const resultsEl = document.getElementById('toolTesterResults');
const countBadgeEl = document.getElementById('toolTesterCountBadge');

document.addEventListener('DOMContentLoaded', () => {
    applyTheme(localStorage.getItem('theme') === 'dark');
    darkModeBtn?.addEventListener('click', () => {
        const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
        applyTheme(!isDark);
    });

    refreshBtn?.addEventListener('click', handleRefreshTools);
    testAllBtn?.addEventListener('click', handleTestAllTools);
    newSessionBtn?.addEventListener('click', async () => {
        await createNewSession({ announce: true, clearResults: false });
    });
    clearResultsBtn?.addEventListener('click', clearResults);
    searchInput?.addEventListener('input', renderToolsList);
    deviceIdentifierTypeSelect?.addEventListener('change', handleDeviceIdentifierTypeChange);
    deviceIdentifierValueInput?.addEventListener('input', handleDeviceIdentifierValueInput);

    startClock();
    restoreDeviceIdentifierSelection();
    loadToolsAndPrompts();
});

function applyTheme(dark) {
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
    if (darkModeBtn) {
        darkModeBtn.textContent = dark ? '☀️' : '🌙';
        darkModeBtn.title = dark ? 'Switch to light mode' : 'Switch to dark mode';
    }
    localStorage.setItem('theme', dark ? 'dark' : 'light');
}

function startClock() {
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
}

function setStatus(message, tone = 'neutral') {
    if (!statusEl) return;
    statusEl.textContent = message;
    statusEl.dataset.tone = tone;
    if (resultsProgressEl) {
        resultsProgressEl.textContent = message;
        resultsProgressEl.dataset.tone = tone;
    }
}

function getPromptForTool(tool) {
    if (!tool) return '';
    return promptExamples.get(tool.name) || promptExamples.get(tool.namespaced_id) || '';
}

function getDecoratedPromptForTool(tool) {
    const prompt = getPromptForTool(tool);
    if (!prompt) return '';

    const deviceContext = getSelectedDeviceIdentifierContext();
    if (!deviceContext) {
        return prompt;
    }

    return `${prompt} Focus on the device with ${deviceContext.label} ${deviceContext.value}.`;
}

function getSelectedDeviceIdentifierContext() {
    const identifierType = deviceIdentifierTypeSelect?.value || '';
    const identifierValue = (deviceIdentifierValueInput?.value || '').trim();

    if (!identifierValue) {
        return null;
    }

    return {
        type: identifierType,
        label: identifierType === 'mac'
            ? 'MAC address'
            : identifierType === 'ip'
                ? 'IP address'
                : 'device information',
        value: identifierValue,
    };
}

function restoreDeviceIdentifierSelection() {
    const rawValue = sessionStorage.getItem(TOOL_TEST_DEVICE_IDENTIFIER_STORAGE_KEY);
    if (rawValue) {
        try {
            const parsedValue = JSON.parse(rawValue);
            if (deviceIdentifierTypeSelect && typeof parsedValue?.type === 'string' && parsedValue.type) {
                deviceIdentifierTypeSelect.value = parsedValue.type;
            }
            if (deviceIdentifierValueInput && typeof parsedValue?.value === 'string') {
                deviceIdentifierValueInput.value = parsedValue.value;
            }
        } catch (error) {
            console.warn('🧪 Failed to restore tool tester device identifier', error);
        }
    }

    if (deviceIdentifierTypeSelect && !deviceIdentifierTypeSelect.value) {
        deviceIdentifierTypeSelect.value = TOOL_TEST_DEVICE_IDENTIFIER_DEFAULT_TYPE;
    }

    syncDeviceIdentifierControls();
}

function persistDeviceIdentifierSelection() {
    sessionStorage.setItem(TOOL_TEST_DEVICE_IDENTIFIER_STORAGE_KEY, JSON.stringify({
        type: deviceIdentifierTypeSelect?.value || '',
        value: deviceIdentifierValueInput?.value || '',
    }));
}

function syncDeviceIdentifierControls() {
    if (!deviceIdentifierTypeSelect || !deviceIdentifierValueInput) return;

    const identifierType = deviceIdentifierTypeSelect.value;
    const hasIdentifierType = Boolean(identifierType);

    deviceIdentifierValueInput.placeholder = hasIdentifierType
        ? `Enter device ${identifierType === 'mac' ? 'MAC address' : 'IP address'}`
        : 'Enter device IP address or MAC address';
}

function handleDeviceIdentifierTypeChange() {
    syncDeviceIdentifierControls();
    persistDeviceIdentifierSelection();
    renderToolsList();
}

function handleDeviceIdentifierValueInput() {
    persistDeviceIdentifierSelection();
    renderToolsList();
}

function getTestableTools() {
    return availableTools.filter((tool) => Boolean(getPromptForTool(tool)));
}

function updateActionButtons() {
    const testableCount = getTestableTools().length;
    if (testAllBtn) {
        testAllBtn.disabled = isProcessing || testableCount === 0;
        testAllBtn.textContent = isProcessing
            ? '🧪 Running...'
            : (testableCount > 0 ? `🧪 Test All (${testableCount})` : '🧪 Test All');
    }

    document.querySelectorAll('.tool-tester-test-btn').forEach((button) => {
        const hasPrompt = button.dataset.hasPrompt === 'true';
        button.disabled = isProcessing || !hasPrompt;
    });

    if (refreshBtn) refreshBtn.disabled = isProcessing;
    if (newSessionBtn) newSessionBtn.disabled = isProcessing;
}

async function loadPromptExamples() {
    const response = await fetch(TOOL_TEST_PROMPTS_ENDPOINT);
    if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
    }

    const entries = await response.json();
    promptExamples = new Map(
        (Array.isArray(entries) ? entries : [])
            .filter((entry) => entry?.tool_name && entry?.prompt)
            .map((entry) => [entry.tool_name, entry.prompt])
    );
}

async function loadToolsAndPrompts() {
    setStatus('Loading tools and prompt examples…', 'running');
    toolsListEl.innerHTML = '<p class="empty-state">Loading tools…</p>';
    updateActionButtons();

    try {
        const [toolsResponse] = await Promise.all([
            fetch('/api/tools'),
            loadPromptExamples(),
        ]);

        if (!toolsResponse.ok) {
            throw new Error(`HTTP ${toolsResponse.status}`);
        }

        availableTools = await toolsResponse.json();
        renderToolsList();

        const testableCount = getTestableTools().length;
        setStatus(
            testableCount > 0
                ? `${testableCount} tools ready for testing with prompts from USAGE-EXAMPLES.md.`
                : 'Tools loaded, but no matching prompt examples were found in USAGE-EXAMPLES.md.',
            testableCount > 0 ? 'ready' : 'warning'
        );
    } catch (error) {
        console.error('🧪 Tool tester failed to load tools', error);
        availableTools = [];
        promptExamples = new Map();
        toolsListEl.innerHTML = `<p class="error-message">Failed to load tools: ${error.message}</p>`;
        setStatus('Failed to load tools or prompt examples.', 'error');
    } finally {
        updateActionButtons();
    }
}

function renderToolsList() {
    const query = (searchInput?.value || '').trim().toLowerCase();
    const filteredTools = availableTools.filter((tool) => {
        const prompt = getPromptForTool(tool).toLowerCase();
        return !query
            || tool.name.toLowerCase().includes(query)
            || tool.server_alias.toLowerCase().includes(query)
            || (tool.description || '').toLowerCase().includes(query)
            || prompt.includes(query);
    });

    if (countBadgeEl) {
        if (availableTools.length > 0) {
            countBadgeEl.textContent = String(availableTools.length);
            countBadgeEl.style.display = 'inline-flex';
        } else {
            countBadgeEl.style.display = 'none';
        }
    }

    if (!filteredTools.length) {
        toolsListEl.innerHTML = '<p class="empty-state">No tools match the current search.</p>';
        updateActionButtons();
        return;
    }

    const grouped = filteredTools.reduce((acc, tool) => {
        if (!acc[tool.server_alias]) acc[tool.server_alias] = [];
        acc[tool.server_alias].push(tool);
        return acc;
    }, {});

    toolsListEl.innerHTML = Object.entries(grouped).map(([serverAlias, serverTools]) => `
        <section class="tool-tester-server-group">
            <header class="tool-tester-server-header">
                <h4>${serverAlias}</h4>
                <span class="server-tool-count">${serverTools.length}</span>
            </header>
            <div class="tool-tester-server-tools">
                ${serverTools.map((tool) => {
                    const basePrompt = getPromptForTool(tool);
                    const prompt = getDecoratedPromptForTool(tool);
                    const hasPrompt = Boolean(basePrompt);
                    const params = tool.parameters?.properties ? Object.keys(tool.parameters.properties) : [];
                    return `
                        <article class="tool-tester-card">
                            <div class="tool-item-header">
                                <div>
                                    <div class="tool-name">${tool.name}</div>
                                    ${tool.description ? `<div class="tool-description">${tool.description}</div>` : ''}
                                </div>
                                <button class="btn btn-secondary btn-sm tool-tester-test-btn" data-tool-id="${tool.namespaced_id}" data-has-prompt="${hasPrompt ? 'true' : 'false'}" ${hasPrompt ? '' : 'disabled'}>
                                    ${hasPrompt ? 'Test' : 'No Example'}
                                </button>
                            </div>
                            ${params.length ? `<div class="tool-params-chips">${params.map((param) => `<span class="tool-param-chip">${param}</span>`).join('')}</div>` : ''}
                            <div class="tool-tester-prompt ${hasPrompt ? '' : 'tool-test-hint-muted'}">
                                ${hasPrompt ? `Prompt: ${escapeHtml(prompt)}` : 'No matching prompt in USAGE-EXAMPLES.md.'}
                            </div>
                        </article>
                    `;
                }).join('')}
            </div>
        </section>
    `).join('');

    toolsListEl.querySelectorAll('.tool-tester-test-btn').forEach((button) => {
        button.addEventListener('click', async (event) => {
            const toolId = event.currentTarget.dataset.toolId;
            const tool = availableTools.find((item) => item.namespaced_id === toolId);
            if (tool) {
                await runToolTest(tool);
            }
        });
    });

    updateActionButtons();
}

function escapeHtml(value) {
    const div = document.createElement('div');
    div.textContent = value;
    return div.innerHTML;
}

async function createNewSession({ announce = false, clearResults: shouldClear = true } = {}) {
    try {
        const llmConfigResponse = await fetch('/api/llm/config');
        if (!llmConfigResponse.ok) {
            if (llmConfigResponse.status === 404) {
                throw new Error('Please configure LLM provider in Settings first.');
            }
            throw new Error(`HTTP ${llmConfigResponse.status}`);
        }

        const llmConfig = await llmConfigResponse.json();
        const serversResponse = await fetch('/api/servers');
        const enabledServers = serversResponse.ok
            ? (await serversResponse.json()).map((server) => server.alias)
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

        if (shouldClear) {
            clearResults();
        }
        if (announce) {
            appendSystemResult(`New test session started (${currentSessionId}).`);
        }
        setStatus('Ready to run MCP tool tests.', 'ready');
        return true;
    } catch (error) {
        console.error('🧪 Failed to create test session', error);
        appendErrorResult(`Failed to create session: ${error.message}`);
        setStatus('Failed to create test session.', 'error');
        return false;
    }
}

async function ensureSession({ forceNew = false } = {}) {
    if (forceNew || !currentSessionId) {
        return createNewSession({ announce: forceNew, clearResults: forceNew });
    }
    return true;
}

async function sendPrompt(prompt) {
    if (!currentSessionId) {
        return { ok: false, error: new Error('Session not initialized') };
    }

    const response = await fetch(`/api/sessions/${currentSessionId}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role: 'user', content: prompt })
    });

    if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
    }

    return response.json();
}

async function runToolTest(tool) {
    const prompt = getDecoratedPromptForTool(tool);
    if (!prompt) {
        appendErrorResult(`No usage example found for ${tool.name}.`);
        return false;
    }

    const ready = await ensureSession();
    if (!ready) {
        return false;
    }

    isProcessing = true;
    updateActionButtons();
    setStatus(`Testing ${tool.name}…`, 'running');

    appendPendingResult(tool, prompt);

    try {
        const data = await sendPrompt(prompt);
        appendResultCard(tool, prompt, data);
        setStatus(`Completed ${tool.name}.`, 'success');
        return true;
    } catch (error) {
        console.error('🧪 Tool test failed', error);
        appendErrorResult(`Failed ${tool.name}: ${error.message}`);
        setStatus(`Failed ${tool.name}.`, 'error');
        return false;
    } finally {
        isProcessing = false;
        updateActionButtons();
    }
}

async function handleTestAllTools() {
    if (isProcessing) return;

    const testableTools = getTestableTools();
    if (!testableTools.length) {
        setStatus('No tools have matching examples in USAGE-EXAMPLES.md.', 'warning');
        return;
    }

    const ready = await ensureSession({ forceNew: true });
    if (!ready) {
        return;
    }

    appendSystemResult(`Running ${testableTools.length} tool tests in a fresh session.`);

    let completed = 0;
    for (const tool of testableTools) {
        const succeeded = await runToolTest(tool);
        if (succeeded) completed += 1;
    }

    setStatus(`Completed ${completed}/${testableTools.length} tool tests.`, completed === testableTools.length ? 'success' : 'warning');
    appendSystemResult(`Finished tool test batch: ${completed}/${testableTools.length} succeeded.`);
}

async function handleRefreshTools() {
    if (isProcessing) return;

    try {
        refreshBtn.disabled = true;
        refreshBtn.textContent = '🔄 Refreshing...';
        const response = await fetch('/api/servers/refresh-tools', { method: 'POST' });
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        await response.json();
        await loadToolsAndPrompts();
    } catch (error) {
        console.error('🧪 Failed to refresh tools', error);
        setStatus(`Failed to refresh tools: ${error.message}`, 'error');
    } finally {
        refreshBtn.disabled = false;
        refreshBtn.textContent = '🔄 Refresh Tools';
        updateActionButtons();
    }
}

function clearResults() {
    resultsEl.innerHTML = '<p class="empty-state">Run a tool test to see prompts, tool executions, and assistant output here.</p>';
    syncResultsOutputFile();
}

function buildResultsOutputText() {
    const sections = ['MCP Tool Tester Results'];
    const statusText = (resultsProgressEl?.textContent || statusEl?.textContent || '').trim();
    if (statusText) {
        sections.push(`Status: ${statusText}`);
    }

    const cards = Array.from(resultsEl.querySelectorAll('.tool-tester-result-card'));
    if (!cards.length) {
        sections.push('');
        sections.push('No tool test results yet.');
        return sections.join('\n');
    }

    const resultSections = cards.map((card) => {
        const meta = (card.querySelector('.tool-tester-result-meta')?.textContent || 'Result').trim();
        const body = (card.querySelector('.tool-tester-result-body')?.textContent || '')
            .replace(/\s+\n/g, '\n')
            .replace(/\n\s+/g, '\n')
            .replace(/\n{3,}/g, '\n\n')
            .trim();

        return [`[${meta}]`, body].filter(Boolean).join('\n');
    });

    sections.push('');
    sections.push(resultSections.join('\n\n'));
    return sections.join('\n');
}

async function syncResultsOutputFile() {
    try {
        await fetch(TOOL_TEST_OUTPUT_ENDPOINT, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content: buildResultsOutputText() })
        });
    } catch (error) {
        console.warn('🧪 Failed to update Tool Tester output.txt', error);
    }
}

function collapsePreviousResults() {
    resultsEl.querySelectorAll('.tool-tester-result-card').forEach((card) => {
        card.classList.add('tool-tester-result-collapsed');
    });
}

function removePendingResult(tool) {
    const selector = tool?.namespaced_id
        ? `.tool-tester-result-pending[data-tool-id="${CSS.escape(tool.namespaced_id)}"]`
        : '.tool-tester-result-pending';
    resultsEl.querySelectorAll(selector).forEach((card) => card.remove());
}

function appendSystemResult(message) {
    prependResult(`
        <article class="tool-tester-result-card tool-tester-result-system">
            <div class="tool-tester-result-meta">System</div>
            <div class="tool-tester-result-body">${escapeHtml(message)}</div>
        </article>
    `);
}

function appendErrorResult(message) {
    prependResult(`
        <article class="tool-tester-result-card tool-tester-result-error">
            <div class="tool-tester-result-meta">Error</div>
            <div class="tool-tester-result-body">${escapeHtml(message)}</div>
        </article>
    `);
}

function appendPendingResult(tool, prompt) {
    removePendingResult(tool);
    prependResult(`
        <article class="tool-tester-result-card tool-tester-result-pending" data-tool-id="${escapeHtml(tool.namespaced_id)}">
            <div class="tool-tester-result-meta">Running ${escapeHtml(tool.name)}</div>
            <div class="tool-tester-result-body">
                <p><strong>Prompt</strong></p>
                <p>${escapeHtml(prompt)}</p>
            </div>
        </article>
    `);
}

function appendResultCard(tool, prompt, data) {
    removePendingResult(tool);
    const toolExecutions = Array.isArray(data.tool_executions) ? data.tool_executions : [];
    const assistantResponse = (data.message?.content || '').trim() || summarizeToolExecutions(toolExecutions);
    const executionsHtml = toolExecutions.length
        ? toolExecutions.map((execution) => {
            const statusClass = execution.success ? 'success' : 'error';
            const args = execution.arguments && Object.keys(execution.arguments).length
                ? JSON.stringify(execution.arguments, null, 2)
                : '{}';
            const result = typeof execution.result === 'string'
                ? execution.result
                : JSON.stringify(execution.result, null, 2);
            return `
                <details class="tool-exec-details ${statusClass}">
                    <summary class="tool-exec-summary">
                        <span class="tool-exec-icon">🔧</span>
                        <span class="tool-exec-name">${escapeHtml(execution.tool)}</span>
                        <span class="tool-exec-status ${statusClass}">${execution.success ? '✓ OK' : '✗ Error'}</span>
                    </summary>
                    <div class="tool-exec-body">
                        <div class="tool-exec-section">
                            <label>Arguments</label>
                            <code>${escapeHtml(args)}</code>
                        </div>
                        <div class="tool-exec-section">
                            <label>Result</label>
                            <code>${escapeHtml(result)}</code>
                        </div>
                    </div>
                </details>
            `;
        }).join('')
        : '<p class="tool-tester-muted">No tool executions were returned for this prompt.</p>';

    prependResult(`
        <article class="tool-tester-result-card">
            <div class="tool-tester-result-meta">${escapeHtml(tool.server_alias)} · ${escapeHtml(tool.name)}</div>
            <div class="tool-tester-result-body">
                <p><strong>Prompt</strong></p>
                <p>${escapeHtml(prompt)}</p>
                <p><strong>Assistant Response</strong></p>
                <div>${escapeHtml(assistantResponse)}</div>
                <div class="tool-tester-executions">${executionsHtml}</div>
            </div>
        </article>
    `);
}

function summarizeToolExecutions(toolExecutions) {
    if (!Array.isArray(toolExecutions) || toolExecutions.length === 0) {
        return '';
    }

    return toolExecutions.map((execution, index) => {
        const label = execution?.tool || `tool ${index + 1}`;
        const status = execution?.success === false ? 'failed' : 'returned';
        const result = typeof execution?.result === 'string'
            ? execution.result.trim()
            : JSON.stringify(execution?.result ?? '', null, 2);

        return result
            ? `${label} ${status}: ${result}`
            : `${label} ${status}.`;
    }).join('\n\n');
}

function prependResult(html) {
    const empty = resultsEl.querySelector('.empty-state');
    if (empty) empty.remove();
    collapsePreviousResults();
    resultsEl.insertAdjacentHTML('afterbegin', html);
    syncResultsOutputFile();
}