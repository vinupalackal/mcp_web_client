/**
 * Frontend tests — localStorage persistence (TC-FE-LS-*)
 *
 * These tests verify that MCP server configs and LLM configs survive
 * module reloads via localStorage, and that sync functions behave correctly.
 */

const { setupFullDOM } = require('./helpers/dom_setup');

function loadModules() {
  jest.resetModules();
  jest.spyOn(console, 'log').mockImplementation(() => {});
  jest.spyOn(console, 'error').mockImplementation(() => {});
  window.loadToolsSidebar = jest.fn().mockResolvedValue(undefined);
  require('../../backend/static/settings.js');
  require('../../backend/static/app.js');
  document.dispatchEvent(new Event('DOMContentLoaded'));
}

describe('localStorage — MCP server persistence (TC-FE-LS-01 to 04)', () => {

  beforeEach(() => {
    setupFullDOM();
  });

  test('TC-FE-LS-01: adding server saves to mcpServers key', async () => {
    let storedServers = [];

    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        server_id: 'id-1', alias: 'my_server',
        base_url: 'https://mcp.example.com', auth_type: 'none'
      }),
    });

    localStorage.getItem.mockReturnValue('[]');
    localStorage.setItem.mockImplementation((key, val) => {
      if (key === 'mcpServers') storedServers = JSON.parse(val);
    });

    loadModules();

    document.getElementById('serverAlias').value = 'my_server';
    document.getElementById('serverUrl').value = 'https://mcp.example.com';
    document.getElementById('authType').value = 'none';

    const form = document.getElementById('addServerForm');
    form.dispatchEvent(new Event('submit', { bubbles: true }));
    await new Promise(r => setTimeout(r, 20));

    expect(storedServers.length).toBeGreaterThan(0);
    expect(storedServers[0].alias).toBe('my_server');
  });

  test('TC-FE-LS-02: deleting server removes from mcpServers', async () => {
    const existing = [
      { server_id: 's1', alias: 'one', base_url: 'https://one.com', auth_type: 'none' },
      { server_id: 's2', alias: 'two', base_url: 'https://two.com', auth_type: 'none' },
    ];

    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    global.confirm.mockReturnValue(true);
    localStorage.getItem.mockReturnValue(JSON.stringify(existing));

    let lastSaved = null;
    localStorage.setItem.mockImplementation((key, val) => {
      if (key === 'mcpServers') lastSaved = JSON.parse(val);
    });

    loadModules();
    await window.deleteServer('s1');
    await new Promise(r => setTimeout(r, 10));

    expect(lastSaved).not.toBeNull();
    expect(lastSaved.find(s => s.server_id === 's1')).toBeUndefined();
    expect(lastSaved.find(s => s.server_id === 's2')).toBeTruthy();
  });

  test('TC-FE-LS-03: multiple servers stored as array', async () => {
    const storedItems = [];

    global.fetch = jest.fn().mockImplementation((url, opts) => {
      const body = opts?.body ? JSON.parse(opts.body) : {};
      return Promise.resolve({
        ok: true,
        json: async () => ({
          server_id: `id-${Date.now()}`,
          alias: body.alias,
          base_url: body.base_url,
          auth_type: body.auth_type || 'none',
        }),
      });
    });

    localStorage.getItem.mockImplementation((key) => {
      if (key === 'mcpServers') return JSON.stringify(storedItems.flat());
      return null;
    });
    localStorage.setItem.mockImplementation((key, val) => {
      if (key === 'mcpServers') {
        storedItems.splice(0, storedItems.length, JSON.parse(val));
      }
    });

    loadModules();

    for (const alias of ['srv_a', 'srv_b']) {
      document.getElementById('serverAlias').value = alias;
      document.getElementById('serverUrl').value = `https://${alias}.com`;
      document.getElementById('authType').value = 'none';
      const form = document.getElementById('addServerForm');
      form.dispatchEvent(new Event('submit', { bubbles: true }));
      await new Promise(r => setTimeout(r, 10));
    }

    // Each save call should include the new server
    expect(localStorage.setItem).toHaveBeenCalledWith('mcpServers', expect.any(String));
  });

  test('TC-FE-LS-04: servers list persists across module reload', () => {
    const servers = [
      { server_id: 'p1', alias: 'persisted', base_url: 'https://p.com', auth_type: 'none' }
    ];
    localStorage.getItem.mockImplementation((key) =>
      key === 'mcpServers' ? JSON.stringify(servers) : null
    );

    // First load
    loadModules();

    // Reset and reload
    jest.resetModules();
    jest.spyOn(console, 'log').mockImplementation(() => {});
    window.loadToolsSidebar = jest.fn().mockResolvedValue(undefined);
    require('../../backend/static/settings.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));

    // localStorage.getItem should have been called to restore servers
    const getCalls = localStorage.getItem.mock.calls.map(c => c[0]);
    expect(getCalls).toContain('mcpServers');
  });
});


describe('localStorage — LLM config persistence (TC-FE-LS-05 to 08)', () => {

  beforeEach(() => {
    setupFullDOM();
  });

  test('TC-FE-LS-05: saving LLM config stores to llmConfig key', async () => {
    const serverResponse = {
      provider: 'mock', model: 'mock-model',
      base_url: 'http://mock', api_key: null, temperature: 1.0
    };
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => serverResponse,
    });
    let savedConfig = null;
    localStorage.setItem.mockImplementation((key, val) => {
      if (key === 'llmConfig') savedConfig = JSON.parse(val);
    });
    localStorage.getItem.mockReturnValue(null);

    loadModules();
    await new Promise(r => setTimeout(r, 10)); // wait for DOMContentLoaded async

    document.getElementById('llmProvider').value = 'mock';
    document.getElementById('llmModel').value = 'mock-model';
    document.getElementById('llmBaseUrl').value = 'http://mock';
    document.getElementById('llmApiKey').value = '';
    document.getElementById('llmTemperature').value = '1.0';

    const form = document.getElementById('llmConfigForm');
    form.dispatchEvent(new Event('submit', { bubbles: true }));
    await new Promise(r => setTimeout(r, 10));

    expect(savedConfig).not.toBeNull();
    expect(savedConfig.provider).toBe('mock');
    expect(savedConfig.model).toBe('mock-model');
  });

  test('TC-FE-LS-06: re-saving LLM config overwrites previous value', async () => {
    let currentConfig = JSON.stringify({ provider: 'mock', model: 'old-model', base_url: 'http://old', temperature: 0.5 });
    localStorage.getItem.mockImplementation((key) =>
      key === 'llmConfig' ? currentConfig : null
    );
    localStorage.setItem.mockImplementation((key, val) => {
      if (key === 'llmConfig') currentConfig = val;
    });

    loadModules();
    await new Promise(r => setTimeout(r, 10));

    // Return the new config as server response
    const newServerResponse = {
      provider: 'openai', model: 'gpt-4o',
      base_url: 'https://api.openai.com', api_key: 'sk-new', temperature: 0.9
    };
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => newServerResponse,
    });

    document.getElementById('llmProvider').value = 'openai';
    document.getElementById('llmModel').value = 'gpt-4o';
    document.getElementById('llmBaseUrl').value = 'https://api.openai.com';
    document.getElementById('llmApiKey').value = 'sk-new';
    document.getElementById('llmTemperature').value = '0.9';

    const form = document.getElementById('llmConfigForm');
    form.dispatchEvent(new Event('submit', { bubbles: true }));
    await new Promise(r => setTimeout(r, 10));

    const parsed = JSON.parse(currentConfig);
    expect(parsed.provider).toBe('openai');
    expect(parsed.model).toBe('gpt-4o');
  });

  test('TC-FE-LS-07: createNewSession reads llmConfig from localStorage', async () => {
    const config = { provider: 'mock', model: 'mock', base_url: 'http://mock', temperature: 1.0 };
    localStorage.getItem.mockImplementation((key) => {
      if (key === 'llmConfig') return JSON.stringify(config);
      if (key === 'mcpServers') return '[]';
      return null;
    });

    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ session_id: 'new-sess', created_at: new Date().toISOString() }),
    });

    loadModules();
    document.getElementById('newChatBtn').click();
    await new Promise(r => setTimeout(r, 20));

    const sessionCalls = global.fetch.mock.calls.filter(
      ([url]) => url && url.includes('/api/sessions')
    );
    expect(sessionCalls.length).toBeGreaterThan(0);
    const body = JSON.parse(sessionCalls[0][1].body);
    expect(body.llm_config).toBeDefined();
    expect(body.llm_config.provider).toBe('mock');
  });

  test('TC-FE-LS-08: missing llmConfig blocks session creation', async () => {
    localStorage.getItem.mockReturnValue(null);
    global.fetch = jest.fn();

    loadModules();
    document.getElementById('newChatBtn').click();
    await new Promise(r => setTimeout(r, 20));

    const sessionCalls = global.fetch.mock.calls.filter(
      ([url]) => url && url.includes('/api/sessions')
    );
    expect(sessionCalls).toHaveLength(0);
  });
});


describe('localStorage — syncServersToBackend (TC-FE-LS-09 to 12)', () => {

  beforeEach(() => {
    setupFullDOM();
    loadModules();
  });

  test('TC-FE-LS-09: empty server list skips POST to /api/servers', async () => {
    localStorage.getItem.mockReturnValue('[]');
    global.fetch = jest.fn();

    await window.syncServersToBackend();

    const serverPosts = global.fetch.mock.calls.filter(
      ([url, opts]) => url && url.includes('/api/servers') && opts?.method === 'POST'
    );
    expect(serverPosts).toHaveLength(0);
  });

  test('TC-FE-LS-10: each server POSTed to /api/servers', async () => {
    const servers = [
      { server_id: 'x1', alias: 'a', base_url: 'https://a.com', auth_type: 'none' },
      { server_id: 'x2', alias: 'b', base_url: 'https://b.com', auth_type: 'none' },
    ];
    localStorage.getItem.mockReturnValue(JSON.stringify(servers));
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => ({}) });

    await window.syncServersToBackend();

    const serverPosts = global.fetch.mock.calls.filter(
      ([url, opts]) => url && url.includes('/api/servers') && opts?.method === 'POST'
    );
    expect(serverPosts).toHaveLength(2);
  });

  test('TC-FE-LS-11: 409 Conflict treated as success (no error thrown)', async () => {
    const servers = [
      { server_id: 'dup', alias: 'dup', base_url: 'https://dup.com', auth_type: 'none' }
    ];
    localStorage.getItem.mockReturnValue(JSON.stringify(servers));
    global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 409, json: async () => ({}) });

    await expect(window.syncServersToBackend()).resolves.not.toThrow();
  });

  test('TC-FE-LS-12: network error during sync does not crash the app', async () => {
    const servers = [
      { server_id: 'x', alias: 'x', base_url: 'https://x.com', auth_type: 'none' }
    ];
    localStorage.getItem.mockReturnValue(JSON.stringify(servers));
    global.fetch = jest.fn().mockRejectedValue(new Error('Network error'));

    await expect(window.syncServersToBackend()).resolves.not.toThrow();
  });
});


describe('localStorage — syncLLMConfigToBackend (TC-FE-LS-13 to 14)', () => {

  beforeEach(() => {
    setupFullDOM();
    loadModules();
  });

  test('TC-FE-LS-13: null LLM config skips POST', async () => {
    localStorage.getItem.mockReturnValue(null);
    global.fetch = jest.fn();

    await window.syncLLMConfigToBackend();

    const llmPosts = global.fetch.mock.calls.filter(
      ([url]) => url && url.includes('/api/llm/config')
    );
    expect(llmPosts).toHaveLength(0);
  });

  test('TC-FE-LS-14: valid LLM config POSTed to /api/llm/config', async () => {
    const config = { provider: 'mock', model: 'mock', base_url: 'http://mock', temperature: 1.0 };
    localStorage.getItem.mockImplementation((key) =>
      key === 'llmConfig' ? JSON.stringify(config) : null
    );
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => ({}) });

    await window.syncLLMConfigToBackend();

    const llmPosts = global.fetch.mock.calls.filter(
      ([url, opts]) => url && url.includes('/api/llm/config') && opts?.method === 'POST'
    );
    expect(llmPosts).toHaveLength(1);
  });
});
