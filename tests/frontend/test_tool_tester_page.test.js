/**
 * Frontend tests — Dedicated Tool Tester page (tool-tester.js)
 *
 * Strategy:
 *  - Set up jsdom DOM matching the tool-tester.html structure
 *  - Mock fetch globally for each test scenario
 *  - Load tool-tester.js via require() so module-level code runs
 *  - Simulate interactions and assert DOM/side-effect outcomes
 */

// ─── Helpers ────────────────────────────────────────────────────────────────

function setupToolTesterDOM() {
  document.body.innerHTML = `
    <div class="tool-tester-page">
      <header class="app-header tool-tester-header">
        <div class="header-left"><h1 class="app-title">MCP Tool Tester</h1></div>
        <div class="header-center">
          <div class="live-clock">
            <span id="clockDate"></span>
            <span class="clock-sep">|</span>
            <span id="clockTime"></span>
          </div>
        </div>
        <div class="header-right">
          <a href="/" class="btn btn-secondary">💬 Back to Chat</a>
          <button id="toolTesterDarkModeBtn" class="btn btn-secondary">🌙</button>
        </div>
      </header>

      <main class="tool-tester-main">
        <section class="tool-tester-hero">
          <div>
            <h2>Test MCP tools</h2>
          </div>
          <div class="tool-tester-hero-actions">
            <button id="toolTesterRefreshBtn" class="btn btn-secondary">🔄 Refresh Tools</button>
            <button id="toolTesterTestAllBtn" class="btn btn-primary" disabled>🧪 Test All</button>
          </div>
        </section>

        <section class="tool-tester-toolbar-card">
          <div class="tool-tester-toolbar-row">
            <input type="text" id="toolTesterSearchInput" class="tool-search-input">
            <button id="toolTesterNewSessionBtn" class="btn btn-secondary">➕ New Test Session</button>
          </div>
          <div class="tool-tester-toolbar-row">
            <select id="toolTesterDeviceIdentifierType" class="tool-search-input">
              <option value="">No device identifier</option>
              <option value="ip" selected>IP address</option>
              <option value="mac">MAC address</option>
            </select>
            <input type="text" id="toolTesterDeviceIdentifierValue" class="tool-search-input">
          </div>
          <div id="toolTesterStatus">Loading tools and prompt examples…</div>
        </section>

        <section class="tool-tester-layout">
          <section class="tool-tester-tools-panel">
            <div class="tool-tester-panel-header">
              <h3>Available Tools <span id="toolTesterCountBadge" style="display:none;"></span></h3>
              <div class="tool-tester-panel-header-actions">
                <button id="toolTesterToggleToolsPanelBtn" class="btn btn-secondary btn-sm tool-tester-panel-toggle" aria-expanded="true" aria-controls="toolTesterToolsList">Collapse</button>
              </div>
            </div>
            <div id="toolTesterToolsList" class="tool-tester-tools-list">
              <p class="empty-state">Loading tools…</p>
            </div>
          </section>

          <section class="tool-tester-results-panel">
            <div class="tool-tester-panel-header">
              <h3>Test Results</h3>
              <div class="tool-tester-panel-header-actions">
                <button id="toolTesterClearResultsBtn" class="btn btn-secondary btn-sm">Clear</button>
                <button id="toolTesterToggleResultsPanelBtn" class="btn btn-secondary btn-sm tool-tester-panel-toggle" aria-expanded="true" aria-controls="toolTesterResults">Collapse</button>
              </div>
            </div>
            <div id="toolTesterResults" class="tool-tester-results">
              <p class="empty-state">Run a tool test to see results here.</p>
            </div>
            <div id="toolTesterResultsProgress" data-tone="neutral">Loading tools and prompt examples…</div>
          </section>
        </section>
      </main>
    </div>
  `;
}

const MOCK_TOOLS = [
  {
    namespaced_id: 'openwrt__server_info',
    name: 'server_info',
    server_alias: 'openwrt',
    description: 'Returns server information',
    parameters: { properties: {} },
  },
  {
    namespaced_id: 'openwrt__get_uptime',
    name: 'get_uptime',
    server_alias: 'openwrt',
    description: 'Returns device uptime',
    parameters: { properties: { format: { type: 'string' } } },
  },
  {
    namespaced_id: 'openwrt__no_example_tool',
    name: 'no_example_tool',
    server_alias: 'openwrt',
    description: 'No usage example for this tool',
    parameters: { properties: {} },
  },
];

const MOCK_PROMPTS = [
  { tool_name: 'server_info', prompt: 'What version is the MCP server and what capabilities does it support?' },
  { tool_name: 'get_uptime', prompt: 'How long has this device been running without a reboot?' },
];

const MOCK_SESSION = { session_id: 'test-session-id-42' };

const MOCK_LLM_CONFIG = {
  provider: 'openai',
  model: 'gpt-4o-mini',
  api_key: 'sk-test',
};

const MOCK_SERVERS = [
  { alias: 'openwrt', base_url: 'http://localhost:3000', enabled: true },
];

function buildFetchMock({ sessionOk = true, messageOk = true, toolsOk = true, promptsOk = true } = {}) {
  return jest.fn((url, options) => {
    if (url === '/api/tools' && !options) {
      return Promise.resolve({
        ok: toolsOk,
        status: toolsOk ? 200 : 500,
        json: () => Promise.resolve(MOCK_TOOLS),
      });
    }

    if (url === '/api/tools/test-prompts' && !options) {
      return Promise.resolve({
        ok: promptsOk,
        status: promptsOk ? 200 : 500,
        json: () => Promise.resolve(MOCK_PROMPTS),
      });
    }

    if (url === '/api/llm/config' && !options) {
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(MOCK_LLM_CONFIG),
      });
    }

    if (url === '/api/servers' && !options) {
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(MOCK_SERVERS),
      });
    }

    if (url === '/api/sessions' && options?.method === 'POST') {
      return Promise.resolve({
        ok: sessionOk,
        status: sessionOk ? 201 : 500,
        json: () => Promise.resolve(MOCK_SESSION),
      });
    }

    if (url?.startsWith('/api/sessions/') && url.endsWith('/messages') && options?.method === 'POST') {
      if (!messageOk) {
        return Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({}) });
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({
          message: { content: 'Server version 1.0.0, capabilities: tools' },
          tool_executions: [
            { tool: 'server_info', success: true, arguments: {}, result: 'Server v1.0' },
          ],
        }),
      });
    }

    if (url === '/api/servers/refresh-tools' && options?.method === 'POST') {
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) });
    }

    if (url === '/api/tools/test-results-output' && options?.method === 'POST') {
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ file_path: 'data/output.txt', bytes_written: 128, updated_at: '2026-03-18T10:15:00Z' }),
      });
    }

    return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) });
  });
}

// ─── Suite helpers ───────────────────────────────────────────────────────────

function loadModule() {
  jest.resetModules();
  // tool-tester.js binds event listeners on DOMContentLoaded;
  // since jsdom fires DOMContentLoaded synchronously when document is already
  // loaded, we trigger it manually after require().
  require('../../backend/static/tool-tester');
  document.dispatchEvent(new Event('DOMContentLoaded', { bubbles: true, cancelable: true }));
}

async function flushPromises(ticks = 20) {
  for (let i = 0; i < ticks; i++) {
    // eslint-disable-next-line no-await-in-loop
    await Promise.resolve();
  }
}

// ─── Tests ───────────────────────────────────────────────────────────────────

describe('Tool Tester Page — DOM structure', () => {
  beforeEach(() => {
    setupToolTesterDOM();
  });

  test('core DOM elements exist after setup', () => {
    expect(document.getElementById('toolTesterToolsList')).not.toBeNull();
    expect(document.getElementById('toolTesterResults')).not.toBeNull();
    expect(document.getElementById('toolTesterStatus')).not.toBeNull();
    expect(document.getElementById('toolTesterResultsProgress')).not.toBeNull();
    expect(document.getElementById('toolTesterToggleToolsPanelBtn')).not.toBeNull();
    expect(document.getElementById('toolTesterToggleResultsPanelBtn')).not.toBeNull();
    expect(document.getElementById('toolTesterTestAllBtn')).not.toBeNull();
    expect(document.getElementById('toolTesterRefreshBtn')).not.toBeNull();
    expect(document.getElementById('toolTesterNewSessionBtn')).not.toBeNull();
    expect(document.getElementById('toolTesterClearResultsBtn')).not.toBeNull();
    expect(document.getElementById('toolTesterSearchInput')).not.toBeNull();
    expect(document.getElementById('toolTesterDeviceIdentifierType')).not.toBeNull();
    expect(document.getElementById('toolTesterDeviceIdentifierValue')).not.toBeNull();
  });

  test('results progress is rendered below the results list', () => {
    const results = document.getElementById('toolTesterResults');
    const progress = document.getElementById('toolTesterResultsProgress');

    expect(results.nextElementSibling).toBe(progress);
  });

  test('Test All button is initially disabled', () => {
    const btn = document.getElementById('toolTesterTestAllBtn');
    expect(btn.disabled).toBe(true);
  });
});

describe('Tool Tester Page — response fallback', () => {
  beforeEach(() => {
    setupToolTesterDOM();
    global.fetch = jest.fn((url, options) => {
      if (url === '/api/tools/test-prompts') {
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(MOCK_PROMPTS) });
      }
      if (url === '/api/tools') {
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(MOCK_TOOLS) });
      }
      if (url === '/api/llm/config' && !options) {
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(MOCK_LLM_CONFIG) });
      }
      if (url === '/api/servers' && !options) {
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(MOCK_SERVERS) });
      }
      if (url === '/api/sessions' && options?.method === 'POST') {
        return Promise.resolve({ ok: true, status: 201, json: () => Promise.resolve(MOCK_SESSION) });
      }
      if (url?.startsWith('/api/sessions/') && url.endsWith('/messages') && options?.method === 'POST') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve({
            message: { content: '' },
            tool_executions: [
              { tool: 'server_info', success: true, arguments: {}, result: 'Server v1.0' },
            ],
          }),
        });
      }
      if (url === '/api/servers/refresh-tools' && options?.method === 'POST') {
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) });
      }
      return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) });
    });
    loadModule();
  });

  afterEach(() => {
    jest.resetAllMocks();
  });

  test('blank assistant response falls back to tool execution result', async () => {
    await flushPromises(30);

    const testBtn = document.querySelector('.tool-tester-test-btn');
    testBtn.click();

    await flushPromises(30);

    const results = document.getElementById('toolTesterResults').textContent;
    expect(results).toContain('server_info returned: Server v1.0');
  });
});

describe('Tool Tester Page — tool loading', () => {
  beforeEach(() => {
    setupToolTesterDOM();
    global.fetch = buildFetchMock();
    loadModule();
  });

  afterEach(() => {
    jest.resetAllMocks();
  });

  test('tools with examples render Test button; tools without render "No Example"', async () => {
    await flushPromises(30);

    const toolsList = document.getElementById('toolTesterToolsList');
    const testBtns = toolsList.querySelectorAll('.tool-tester-test-btn');

    expect(testBtns.length).toBeGreaterThanOrEqual(3);

    const enabledBtns = Array.from(testBtns).filter((b) => !b.disabled);
    const disabledBtns = Array.from(testBtns).filter((b) => b.disabled);

    // server_info + get_uptime have prompts; no_example_tool does not
    expect(enabledBtns.length).toBe(2);
    expect(disabledBtns.length).toBeGreaterThanOrEqual(1);

    const disabledText = Array.from(disabledBtns).map((b) => b.textContent.trim());
    expect(disabledText.some((t) => t.includes('No Example'))).toBe(true);
  });

  test('Test All button shows testable count and is enabled', async () => {
    await flushPromises(30);

    const testAllBtn = document.getElementById('toolTesterTestAllBtn');
    expect(testAllBtn.disabled).toBe(false);
    // Should include the count of tools with examples (2)
    expect(testAllBtn.textContent).toContain('2');
  });

  test('status area reflects tools-loaded state', async () => {
    await flushPromises(30);

    const status = document.getElementById('toolTesterStatus');
    expect(status.textContent.toLowerCase()).toMatch(/ready|tools/);
  });

  test('results progress mirrors the current status', async () => {
    await flushPromises(30);

    const progress = document.getElementById('toolTesterResultsProgress');
    expect(progress.textContent.toLowerCase()).toMatch(/ready|tools/);
  });

  test('count badge shows total number of tools', async () => {
    await flushPromises(30);

    const badge = document.getElementById('toolTesterCountBadge');
    expect(badge.style.display).not.toBe('none');
    expect(badge.textContent).toBe(String(MOCK_TOOLS.length));
  });

  test('tool names and descriptions appear in tools list', async () => {
    await flushPromises(30);

    const toolsList = document.getElementById('toolTesterToolsList');
    const html = toolsList.innerHTML;

    expect(html).toContain('server_info');
    expect(html).toContain('get_uptime');
    expect(html).toContain('no_example_tool');
  });

  test('prompt text shown under tools that have an example', async () => {
    await flushPromises(30);

    const toolsList = document.getElementById('toolTesterToolsList');
    expect(toolsList.innerHTML).toContain('What version is the MCP server');
    expect(toolsList.innerHTML).toContain('How long has this device been running');
  });

  test('device identifier defaults to IP address', async () => {
    await flushPromises(30);

    const typeSelect = document.getElementById('toolTesterDeviceIdentifierType');
    expect(typeSelect.value).toBe('ip');
  });

  test('prompt text includes selected device IP address', async () => {
    await flushPromises(30);

    const typeSelect = document.getElementById('toolTesterDeviceIdentifierType');
    const valueInput = document.getElementById('toolTesterDeviceIdentifierValue');
    typeSelect.value = 'ip';
    typeSelect.dispatchEvent(new Event('change', { bubbles: true }));
    valueInput.value = '192.168.1.10';
    valueInput.dispatchEvent(new Event('input', { bubbles: true }));
    await flushPromises(5);

    const toolsList = document.getElementById('toolTesterToolsList');
    expect(toolsList.innerHTML).toContain('IP address 192.168.1.10');
  });

  test('prompt text includes device information value even without type selected', async () => {
    await flushPromises(30);

    const typeSelect = document.getElementById('toolTesterDeviceIdentifierType');
    const valueInput = document.getElementById('toolTesterDeviceIdentifierValue');
    typeSelect.value = '';
    typeSelect.dispatchEvent(new Event('change', { bubbles: true }));
    valueInput.value = 'router-lab-01';
    valueInput.dispatchEvent(new Event('input', { bubbles: true }));
    await flushPromises(5);

    const toolsList = document.getElementById('toolTesterToolsList');
    expect(toolsList.innerHTML).toContain('device information router-lab-01');
  });

  test('device information value is cached for the browser session', async () => {
    await flushPromises(30);

    const valueInput = document.getElementById('toolTesterDeviceIdentifierValue');
    valueInput.value = '10.0.0.25';
    valueInput.dispatchEvent(new Event('input', { bubbles: true }));

    expect(sessionStorage.setItem).toHaveBeenCalledWith(
      'toolTesterDeviceIdentifier',
      JSON.stringify({ type: 'ip', value: '10.0.0.25' })
    );
  });

  test('tools panel can be collapsed and expanded', async () => {
    await flushPromises(30);

    const toggleBtn = document.getElementById('toolTesterToggleToolsPanelBtn');
    const toolsList = document.getElementById('toolTesterToolsList');

    toggleBtn.click();
    expect(toolsList.hidden).toBe(true);
    expect(toggleBtn.textContent).toContain('Expand');
    expect(toggleBtn.getAttribute('aria-expanded')).toBe('false');

    toggleBtn.click();
    expect(toolsList.hidden).toBe(false);
    expect(toggleBtn.textContent).toContain('Collapse');
    expect(toggleBtn.getAttribute('aria-expanded')).toBe('true');
  });

  test('results panel can be collapsed and expanded', async () => {
    await flushPromises(30);

    const toggleBtn = document.getElementById('toolTesterToggleResultsPanelBtn');
    const results = document.getElementById('toolTesterResults');
    const progress = document.getElementById('toolTesterResultsProgress');

    toggleBtn.click();
    expect(results.hidden).toBe(true);
    expect(progress.hidden).toBe(true);
    expect(toggleBtn.textContent).toContain('Expand');
    expect(toggleBtn.getAttribute('aria-expanded')).toBe('false');

    toggleBtn.click();
    expect(results.hidden).toBe(false);
    expect(progress.hidden).toBe(false);
    expect(toggleBtn.textContent).toContain('Collapse');
    expect(toggleBtn.getAttribute('aria-expanded')).toBe('true');
  });
});

describe('Tool Tester Page — search/filter', () => {
  beforeEach(() => {
    setupToolTesterDOM();
    global.fetch = buildFetchMock();
    loadModule();
  });

  afterEach(() => {
    jest.resetAllMocks();
  });

  test('search narrows visible tools', async () => {
    await flushPromises(30);

    const searchInput = document.getElementById('toolTesterSearchInput');
    searchInput.value = 'uptime';
    searchInput.dispatchEvent(new Event('input', { bubbles: true }));
    await flushPromises(5);

    const toolsList = document.getElementById('toolTesterToolsList');
    expect(toolsList.innerHTML).toContain('get_uptime');
    expect(toolsList.innerHTML).not.toContain('server_info');
  });

  test('empty search reveals all tools again', async () => {
    await flushPromises(30);

    const searchInput = document.getElementById('toolTesterSearchInput');
    searchInput.value = 'uptime';
    searchInput.dispatchEvent(new Event('input', { bubbles: true }));
    await flushPromises(5);

    searchInput.value = '';
    searchInput.dispatchEvent(new Event('input', { bubbles: true }));
    await flushPromises(5);

    const toolsList = document.getElementById('toolTesterToolsList');
    expect(toolsList.innerHTML).toContain('server_info');
    expect(toolsList.innerHTML).toContain('get_uptime');
  });
});

describe('Tool Tester Page — individual tool test', () => {
  beforeEach(() => {
    setupToolTesterDOM();
    global.fetch = buildFetchMock();
    loadModule();
  });

  afterEach(() => {
    jest.resetAllMocks();
  });

  test('clicking Test creates a session and submits prompt to chat API', async () => {
    await flushPromises(30);

    const toolsList = document.getElementById('toolTesterToolsList');
    const testBtns = toolsList.querySelectorAll('.tool-tester-test-btn:not([disabled])');
    expect(testBtns.length).toBeGreaterThan(0);

    testBtns[0].click();
    await flushPromises(30);

    const calls = global.fetch.mock.calls;
    const sessionCall = calls.find(([url, opts]) => url === '/api/sessions' && opts?.method === 'POST');
    const messageCall = calls.find(([url, opts]) => url?.includes('/messages') && opts?.method === 'POST');

    expect(sessionCall).toBeDefined();
    expect(messageCall).toBeDefined();
  });

  test('selected MAC address is included in submitted chat prompt', async () => {
    await flushPromises(30);

    const typeSelect = document.getElementById('toolTesterDeviceIdentifierType');
    const valueInput = document.getElementById('toolTesterDeviceIdentifierValue');
    typeSelect.value = 'mac';
    typeSelect.dispatchEvent(new Event('change', { bubbles: true }));
    valueInput.value = 'AA:BB:CC:DD:EE:FF';
    valueInput.dispatchEvent(new Event('input', { bubbles: true }));

    const toolsList = document.getElementById('toolTesterToolsList');
    const testBtns = toolsList.querySelectorAll('.tool-tester-test-btn:not([disabled])');
    testBtns[0].click();
    await flushPromises(30);

    const messageCall = global.fetch.mock.calls.find(([url, opts]) => url?.includes('/messages') && opts?.method === 'POST');
    expect(messageCall).toBeDefined();

    const [, options] = messageCall;
    const payload = JSON.parse(options.body);
    expect(payload.content).toContain('MAC address AA:BB:CC:DD:EE:FF');
  });

  test('device information value is included in submitted chat prompt without type selected', async () => {
    await flushPromises(30);

    const typeSelect = document.getElementById('toolTesterDeviceIdentifierType');
    const valueInput = document.getElementById('toolTesterDeviceIdentifierValue');
    typeSelect.value = '';
    typeSelect.dispatchEvent(new Event('change', { bubbles: true }));
    valueInput.value = '192.168.50.5';
    valueInput.dispatchEvent(new Event('input', { bubbles: true }));

    const toolsList = document.getElementById('toolTesterToolsList');
    const testBtns = toolsList.querySelectorAll('.tool-tester-test-btn:not([disabled])');
    testBtns[0].click();
    await flushPromises(30);

    const messageCall = global.fetch.mock.calls.find(([url, opts]) => url?.includes('/messages') && opts?.method === 'POST');
    expect(messageCall).toBeDefined();

    const [, options] = messageCall;
    const payload = JSON.parse(options.body);
    expect(payload.content).toContain('device information 192.168.50.5');
  });

  test('result card appears in results panel after test', async () => {
    await flushPromises(30);

    const toolsList = document.getElementById('toolTesterToolsList');
    const testBtns = toolsList.querySelectorAll('.tool-tester-test-btn:not([disabled])');
    testBtns[0].click();
    await flushPromises(30);

    const results = document.getElementById('toolTesterResults');
    const cards = results.querySelectorAll('.tool-tester-result-card');
    expect(cards.length).toBeGreaterThanOrEqual(1);
  });

  test('result card contains assistant response text', async () => {
    await flushPromises(30);

    const toolsList = document.getElementById('toolTesterToolsList');
    const testBtns = toolsList.querySelectorAll('.tool-tester-test-btn:not([disabled])');
    testBtns[0].click();
    await flushPromises(30);

    const results = document.getElementById('toolTesterResults');
    expect(results.innerHTML).toContain('Server version 1.0.0');
  });

  test('successful result card shows green SUCCESS status', async () => {
    await flushPromises(30);

    const toolsList = document.getElementById('toolTesterToolsList');
    const testBtns = toolsList.querySelectorAll('.tool-tester-test-btn:not([disabled])');
    testBtns[0].click();
    await flushPromises(30);

    const results = document.getElementById('toolTesterResults');
    const statusBadge = results.querySelector('.tool-tester-result-status.success');

    expect(statusBadge).not.toBeNull();
    expect(statusBadge.textContent).toContain('SUCCESS');
  });

  test('tool test execution syncs results to output.txt', async () => {
    await flushPromises(30);

    const toolsList = document.getElementById('toolTesterToolsList');
    const testBtns = toolsList.querySelectorAll('.tool-tester-test-btn:not([disabled])');
    testBtns[0].click();
    await flushPromises(30);

    const outputCalls = global.fetch.mock.calls.filter(([url, opts]) => url === '/api/tools/test-results-output' && opts?.method === 'POST');
    expect(outputCalls.length).toBeGreaterThan(0);

    const lastPayload = JSON.parse(outputCalls[outputCalls.length - 1][1].body);
    expect(lastPayload.content).toContain('MCP Tool Tester Results');
    expect(lastPayload.content).toContain('Server version 1.0.0');
  });

  test('previous results collapse when a new test starts', async () => {
    await flushPromises(30);

    const toolsList = document.getElementById('toolTesterToolsList');
    const testBtns = toolsList.querySelectorAll('.tool-tester-test-btn:not([disabled])');

    testBtns[0].click();
    await flushPromises(30);
    testBtns[1].click();
    await flushPromises(10);

    const results = document.getElementById('toolTesterResults');
    const cards = results.querySelectorAll('.tool-tester-result-card');
    expect(cards.length).toBeGreaterThanOrEqual(2);
    expect(cards[0].classList.contains('tool-tester-result-collapsed')).toBe(true);
    expect(cards[1].classList.contains('tool-tester-result-collapsed')).toBe(false);
  });

  test('collapsed result can be expanded again manually', async () => {
    await flushPromises(30);

    const toolsList = document.getElementById('toolTesterToolsList');
    const testBtns = toolsList.querySelectorAll('.tool-tester-test-btn:not([disabled])');

    testBtns[0].click();
    await flushPromises(30);
    testBtns[1].click();
    await flushPromises(10);

    const results = document.getElementById('toolTesterResults');
    const cards = results.querySelectorAll('.tool-tester-result-card');
    const olderCard = cards[0];
    const expandBtn = olderCard.querySelector('.tool-tester-result-toggle');

    expect(olderCard.classList.contains('tool-tester-result-collapsed')).toBe(true);
    expect(expandBtn.textContent).toContain('Expand');

    expandBtn.click();
    await flushPromises(2);

    expect(olderCard.classList.contains('tool-tester-result-collapsed')).toBe(false);
    expect(expandBtn.textContent).toContain('Minimize');
    expect(expandBtn.getAttribute('aria-expanded')).toBe('true');
  });

  test('tool cards can be minimized and expanded', async () => {
    await flushPromises(30);

    const toolCard = document.querySelector('.tool-tester-card');
    const toggleBtn = toolCard.querySelector('.tool-tester-tool-toggle');

    toggleBtn.click();
    expect(toolCard.classList.contains('tool-tester-card-collapsed')).toBe(true);
    expect(toggleBtn.textContent).toContain('Expand');
    expect(toggleBtn.getAttribute('aria-expanded')).toBe('false');

    toggleBtn.click();
    expect(toolCard.classList.contains('tool-tester-card-collapsed')).toBe(false);
    expect(toggleBtn.textContent).toContain('Minimize');
    expect(toggleBtn.getAttribute('aria-expanded')).toBe('true');
  });

  test('tool execution details appear in result card', async () => {
    await flushPromises(30);

    const toolsList = document.getElementById('toolTesterToolsList');
    const testBtns = toolsList.querySelectorAll('.tool-tester-test-btn:not([disabled])');
    testBtns[0].click();
    await flushPromises(30);

    const results = document.getElementById('toolTesterResults');
    const execDetails = results.querySelectorAll('.tool-exec-details');
    expect(execDetails.length).toBeGreaterThanOrEqual(1);
  });
});

describe('Tool Tester Page — clear results', () => {
  beforeEach(() => {
    setupToolTesterDOM();
    global.fetch = buildFetchMock();
    loadModule();
  });

  afterEach(() => {
    jest.resetAllMocks();
  });

  test('Clear button restores empty state message', async () => {
    await flushPromises(30);

    const toolsList = document.getElementById('toolTesterToolsList');
    const testBtns = toolsList.querySelectorAll('.tool-tester-test-btn:not([disabled])');
    testBtns[0].click();
    await flushPromises(30);

    const clearBtn = document.getElementById('toolTesterClearResultsBtn');
    clearBtn.click();
    await flushPromises(10);

    const results = document.getElementById('toolTesterResults');
    expect(results.innerHTML).toContain('empty-state');

    const outputCalls = global.fetch.mock.calls.filter(([url, opts]) => url === '/api/tools/test-results-output' && opts?.method === 'POST');
    const lastPayload = JSON.parse(outputCalls[outputCalls.length - 1][1].body);
    expect(lastPayload.content).toContain('No tool test results yet.');
  });
});

describe('Tool Tester Page — new session button', () => {
  beforeEach(() => {
    setupToolTesterDOM();
    global.fetch = buildFetchMock();
    loadModule();
  });

  afterEach(() => {
    jest.resetAllMocks();
  });

  test('clicking New Test Session calls sessions API', async () => {
    await flushPromises(30);

    const newSessionBtn = document.getElementById('toolTesterNewSessionBtn');
    newSessionBtn.click();
    await flushPromises(30);

    const calls = global.fetch.mock.calls;
    const sessionCalls = calls.filter(([url, opts]) => url === '/api/sessions' && opts?.method === 'POST');
    expect(sessionCalls.length).toBeGreaterThanOrEqual(1);
  });
});

describe('Tool Tester Page — error handling', () => {
  afterEach(() => {
    jest.resetAllMocks();
  });

  test('shows error state when tools API fails', async () => {
    setupToolTesterDOM();
    global.fetch = buildFetchMock({ toolsOk: false });
    loadModule();

    await flushPromises(30);

    const toolsList = document.getElementById('toolTesterToolsList');
    expect(toolsList.innerHTML.toLowerCase()).toMatch(/fail|error/);
  });

  test('Test All disabled when prompts fail to load', async () => {
    setupToolTesterDOM();
    global.fetch = buildFetchMock({ promptsOk: false });
    loadModule();

    await flushPromises(30);

    const testAllBtn = document.getElementById('toolTesterTestAllBtn');
    // With no prompts, no testable tools → button should stay disabled
    expect(testAllBtn.disabled).toBe(true);
  });

  test('failed query run shows red FAILED status in results', async () => {
    setupToolTesterDOM();
    global.fetch = buildFetchMock({ messageOk: false });
    loadModule();

    await flushPromises(30);

    const testBtn = document.querySelector('.tool-tester-test-btn:not([disabled])');
    testBtn.click();
    await flushPromises(30);

    const results = document.getElementById('toolTesterResults');
    const statusBadge = results.querySelector('.tool-tester-result-status.failure');

    expect(statusBadge).not.toBeNull();
    expect(statusBadge.textContent).toContain('FAILED');
  });
});

describe('Tool Tester Page — dark mode toggle', () => {
  beforeEach(() => {
    setupToolTesterDOM();
    global.fetch = buildFetchMock();
    loadModule();
  });

  afterEach(() => {
    jest.resetAllMocks();
  });

  test('theme button cycles through light, dark, and teal', async () => {
    await flushPromises(10);

    const btn = document.getElementById('toolTesterDarkModeBtn');
    expect(document.documentElement.getAttribute('data-theme')).toBe('light');

    btn.click();
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');

    btn.click();
    expect(document.documentElement.getAttribute('data-theme')).toBe('teal');

    btn.click();
    expect(document.documentElement.getAttribute('data-theme')).toBe('light');
  });

  test('theme is saved to localStorage on toggle', async () => {
    await flushPromises(10);

    const btn = document.getElementById('toolTesterDarkModeBtn');
    btn.click();
    // Verify setItem was called with the correct arguments
    expect(localStorage.setItem).toHaveBeenCalledWith('theme', 'dark');

    btn.click();
    expect(localStorage.setItem).toHaveBeenCalledWith('theme', 'teal');

    btn.click();
    expect(localStorage.setItem).toHaveBeenCalledWith('theme', 'light');
  });
});
