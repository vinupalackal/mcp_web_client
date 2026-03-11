/**
 * Frontend integration tests — cross-module interaction (TC-FE-INT-*)
 *
 * These tests verify that app.js and settings.js work together correctly,
 * that settings changes are reflected in the chat UI, and that page-load
 * sync behaviour is correct.
 */

const { setupFullDOM } = require('./helpers/dom_setup');

function loadAll() {
  jest.resetModules();
  jest.spyOn(console, 'log').mockImplementation(() => {});
  jest.spyOn(console, 'error').mockImplementation(() => {});
  window.loadToolsSidebar = jest.fn().mockResolvedValue(undefined);
  require('../../backend/static/settings.js');
  require('../../backend/static/app.js');
  document.dispatchEvent(new Event('DOMContentLoaded'));
}

describe('Frontend integration — TC-FE-INT-01 to 05', () => {

  beforeEach(() => {
    setupFullDOM();
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => [],
    });
    localStorage.getItem.mockReturnValue(null);
  });

  // -------------------------------------------------------------------------
  // TC-FE-INT-01: Closing settings refreshes the tools sidebar
  // -------------------------------------------------------------------------
  test('TC-FE-INT-01: closing settings modal refreshes the tool sidebar', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => [],
    });

    loadAll();

    // After loadAll, window.loadToolsSidebar is set by app.js.
    // Spy on it after module load.
    const originalFn = window.loadToolsSidebar;
    const spy = jest.fn().mockImplementation(originalFn);
    window.loadToolsSidebar = spy;

    // Open modal then close it — closing should call loadToolsSidebar
    document.getElementById('settingsBtn').click();
    document.getElementById('closeSettings').click();
    await new Promise(r => setTimeout(r, 10));

    expect(spy).toHaveBeenCalled();
  });

  // -------------------------------------------------------------------------
  // TC-FE-INT-02: Clicking Refresh Tools syncs backend and updates both
  //               the tools list in settings AND the sidebar
  // -------------------------------------------------------------------------
  test('TC-FE-INT-02: refresh tools updates settings list AND calls loadToolsSidebar', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ tools: [], total_tools: 0, servers_refreshed: 0 }),
    });
    localStorage.getItem.mockReturnValue('[]');

    loadAll();

    // Spy on window.loadToolsSidebar AFTER app.js has set it
    const originalFn = window.loadToolsSidebar;
    const spy = jest.fn().mockImplementation(originalFn);
    window.loadToolsSidebar = spy;

    document.getElementById('refreshToolsBtn').click();
    await new Promise(r => setTimeout(r, 30));

    expect(spy).toHaveBeenCalled();
  });

  // -------------------------------------------------------------------------
  // TC-FE-INT-03: First message auto-creates a session when currentSessionId is null
  // -------------------------------------------------------------------------
  test('TC-FE-INT-03: first message auto-creates a session', async () => {
    const config = { provider: 'mock', model: 'mock', base_url: 'http://mock', temperature: 1.0 };
    localStorage.getItem.mockImplementation((key) => {
      if (key === 'llmConfig') return JSON.stringify(config);
      if (key === 'mcpServers') return '[]';
      return null;
    });

    const fetchCalls = [];
    global.fetch = jest.fn().mockImplementation((url, opts) => {
      fetchCalls.push({ url, opts });
      if (url.includes('/api/sessions') && opts?.method === 'POST' && !url.includes('/messages')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ session_id: 'auto-sess', created_at: new Date().toISOString() }),
        });
      }
      if (url.includes('/messages')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            session_id: 'auto-sess',
            message: { role: 'assistant', content: 'hi' },
            tool_executions: [],
          }),
        });
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    });

    window.loadToolsSidebar = jest.fn().mockResolvedValue(undefined);

    loadAll();

    const input = document.getElementById('messageInput');
    const sendBtn = document.getElementById('sendBtn');
    input.value = 'hello auto';
    input.dispatchEvent(new Event('input'));
    sendBtn.click();

    await new Promise(r => setTimeout(r, 50));

    const sessionCreations = fetchCalls.filter(
      c => c.url && c.url.includes('/api/sessions') && !c.url.includes('/messages')
        && c.opts?.method === 'POST'
    );
    expect(sessionCreations.length).toBeGreaterThanOrEqual(1);
  });

  // -------------------------------------------------------------------------
  // TC-FE-INT-04: Missing LLM config prevents message send
  // -------------------------------------------------------------------------
  test('TC-FE-INT-04: missing llm config prevents message from being sent', async () => {
    localStorage.getItem.mockReturnValue(null); // no llmConfig
    global.fetch = jest.fn();
    window.loadToolsSidebar = jest.fn().mockResolvedValue(undefined);

    loadAll();

    const input = document.getElementById('messageInput');
    const sendBtn = document.getElementById('sendBtn');
    input.value = 'test';
    input.dispatchEvent(new Event('input'));
    sendBtn.click();

    await new Promise(r => setTimeout(r, 30));

    // No POST to /api/sessions should have been made
    const sessionCalls = global.fetch.mock.calls.filter(
      ([url, opts]) => url && url.includes('/api/sessions') && opts?.method === 'POST'
    );
    expect(sessionCalls).toHaveLength(0);

    // Error message shown in chat
    expect(document.getElementById('chatMessages').innerHTML).toContain('Settings');
  });

  // -------------------------------------------------------------------------
  // TC-FE-INT-05: DOMContentLoaded triggers both server and LLM config syncs
  // -------------------------------------------------------------------------
  test('TC-FE-INT-05: page load syncs servers and LLM config to backend', async () => {
    const servers = [
      { server_id: 'x', alias: 'x', base_url: 'https://x.com', auth_type: 'none' }
    ];
    const config = { provider: 'mock', model: 'mock', base_url: 'http://mock', temperature: 1.0 };

    localStorage.getItem.mockImplementation((key) => {
      if (key === 'mcpServers') return JSON.stringify(servers);
      if (key === 'llmConfig') return JSON.stringify(config);
      return null;
    });

    const syncedUrls = [];
    global.fetch = jest.fn().mockImplementation((url, opts) => {
      syncedUrls.push({ url, method: opts?.method });
      return Promise.resolve({ ok: true, json: async () => ({}) });
    });

    window.loadToolsSidebar = jest.fn().mockResolvedValue(undefined);
    loadAll();

    // Wait for async initialization
    await new Promise(r => setTimeout(r, 30));

    const serverSync = syncedUrls.filter(
      c => c.url && c.url.includes('/api/servers') && c.method === 'POST'
    );
    const llmSync = syncedUrls.filter(
      c => c.url && c.url.includes('/api/llm/config') && c.method === 'POST'
    );

    expect(serverSync.length).toBeGreaterThanOrEqual(1);
    expect(llmSync.length).toBeGreaterThanOrEqual(1);
  });
});
