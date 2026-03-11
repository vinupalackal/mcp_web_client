/**
 * Frontend tests — non-sensitive UI preference storage (TC-FE-PREF-*)
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

describe('UI preference storage', () => {
  beforeEach(() => {
    setupFullDOM();
  });

  test('TC-FE-PREF-01: saving standard config writes only gateway mode preference', async () => {
    global.fetch = jest.fn((url) => {
      if (url === '/api/llm/config') {
        return Promise.resolve({
          ok: true,
          json: async () => ({ provider: 'mock', model: 'mock-model', base_url: 'http://mock', api_key: null, temperature: 1.0, gateway_mode: 'standard' }),
        });
      }
      if (url === '/api/servers') return Promise.resolve({ ok: true, json: async () => [] });
      if (url === '/api/tools') return Promise.resolve({ ok: true, json: async () => [] });
      if (url === '/api/enterprise/token/status') return Promise.resolve({ ok: true, json: async () => ({ token_cached: false }) });
      return Promise.resolve({ ok: true, json: async () => ({}) });
    });

    loadModules();
    await new Promise(r => setTimeout(r, 20));

    document.getElementById('llmProvider').value = 'mock';
    document.getElementById('llmModel').value = 'mock-model';
    document.getElementById('llmBaseUrl').value = 'http://mock';
    document.getElementById('llmTemperature').value = '1.0';
    document.getElementById('llmConfigForm').dispatchEvent(new Event('submit', { bubbles: true }));
    await new Promise(r => setTimeout(r, 20));

    const keysWritten = localStorage.setItem.mock.calls.map(call => call[0]);
    expect(keysWritten).toContain('llmGatewayMode');
    expect(keysWritten).not.toContain('llmConfig');
  });

  test('TC-FE-PREF-02: saving enterprise config writes selected model but not secret fields', async () => {
    global.fetch = jest.fn((url) => {
      if (url === '/api/llm/config') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            gateway_mode: 'enterprise',
            provider: 'enterprise',
            model: 'gpt-4o',
            base_url: 'https://gateway.internal/v1',
            auth_method: 'bearer',
            client_id: 'ent-client',
            client_secret: 'ent-secret',
            token_endpoint_url: 'https://auth.internal/token',
            temperature: 0.2,
          }),
        });
      }
      if (url === '/api/servers') return Promise.resolve({ ok: true, json: async () => [] });
      if (url === '/api/tools') return Promise.resolve({ ok: true, json: async () => [] });
      if (url === '/api/enterprise/token/status') return Promise.resolve({ ok: true, json: async () => ({ token_cached: false }) });
      return Promise.resolve({ ok: true, json: async () => ({}) });
    });

    loadModules();
    await new Promise(r => setTimeout(r, 20));

    document.getElementById('llmGatewayModeEnterprise').checked = true;
    document.getElementById('llmGatewayModeEnterprise').dispatchEvent(new Event('change'));
    document.getElementById('enterpriseModel').value = 'gpt-4o';
    document.getElementById('enterpriseGatewayUrl').value = 'https://gateway.internal/v1';
    document.getElementById('enterpriseClientId').value = 'ent-client';
    document.getElementById('enterpriseClientSecret').value = 'ent-secret';
    document.getElementById('enterpriseTokenEndpoint').value = 'https://auth.internal/token';
    document.getElementById('llmTemperature').value = '0.2';
    document.getElementById('llmConfigForm').dispatchEvent(new Event('submit', { bubbles: true }));
    await new Promise(r => setTimeout(r, 20));

    const keysWritten = localStorage.setItem.mock.calls.map(call => call[0]);
    expect(keysWritten).toContain('llmGatewayMode');
    expect(keysWritten).toContain('enterpriseSelectedModel');
    expect(keysWritten).not.toContain('enterpriseClientSecret');
    expect(keysWritten).not.toContain('enterpriseClientId');
    expect(keysWritten).not.toContain('enterpriseTokenEndpoint');
  });

  test('TC-FE-PREF-03: custom enterprise models persist across reloads', async () => {
    const store = {};
    localStorage.getItem.mockImplementation((key) => store[key] ?? null);
    localStorage.setItem.mockImplementation((key, value) => { store[key] = String(value); });

    global.fetch = jest.fn((url) => {
      if (url === '/api/servers') return Promise.resolve({ ok: true, json: async () => [] });
      if (url === '/api/llm/config') return Promise.resolve({ ok: false, status: 404, json: async () => ({}) });
      if (url === '/api/tools') return Promise.resolve({ ok: true, json: async () => [] });
      if (url === '/api/enterprise/token/status') return Promise.resolve({ ok: true, json: async () => ({ token_cached: false }) });
      return Promise.resolve({ ok: true, json: async () => ({}) });
    });

    loadModules();
    await new Promise(r => setTimeout(r, 20));

    document.getElementById('llmGatewayModeEnterprise').checked = true;
    document.getElementById('llmGatewayModeEnterprise').dispatchEvent(new Event('change'));
    document.getElementById('addEnterpriseModelBtn').click();
    document.getElementById('enterpriseCustomModelId').value = 'gemini-2-pro';
    document.getElementById('enterpriseCustomModelProvider').value = 'Google';
    document.getElementById('enterpriseCustomModelType').value = 'LLM';
    document.getElementById('enterpriseSaveModelBtn').click();

    jest.resetModules();
    setupFullDOM();
    localStorage.getItem.mockImplementation((key) => store[key] ?? null);
    localStorage.setItem.mockImplementation((key, value) => { store[key] = String(value); });
    window.loadToolsSidebar = jest.fn().mockResolvedValue(undefined);
    require('../../backend/static/settings.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));
    await new Promise(r => setTimeout(r, 20));

    const options = Array.from(document.getElementById('enterpriseModel').options).map(option => option.value);
    expect(options).toContain('gemini-2-pro');
  });

  test('TC-FE-PREF-04: settings UI loads server and llm config from backend, not localStorage', async () => {
    localStorage.getItem.mockImplementation((key) => {
      if (key === 'mcpServers') return JSON.stringify([{ server_id: 'local-1', alias: 'local', base_url: 'https://local', auth_type: 'none' }]);
      if (key === 'llmConfig') return JSON.stringify({ provider: 'mock', model: 'local-model', base_url: 'http://local', temperature: 0.5 });
      return null;
    });

    global.fetch = jest.fn((url) => {
      if (url === '/api/servers') return Promise.resolve({ ok: true, json: async () => [{ server_id: 'backend-1', alias: 'backend', base_url: 'https://backend', auth_type: 'none' }] });
      if (url === '/api/llm/config') return Promise.resolve({ ok: true, json: async () => ({ provider: 'openai', model: 'gpt-4o', base_url: 'https://api.openai.com', api_key: 'sk-test', temperature: 0.8 }) });
      if (url === '/api/tools') return Promise.resolve({ ok: true, json: async () => [] });
      if (url === '/api/enterprise/token/status') return Promise.resolve({ ok: true, json: async () => ({ token_cached: false }) });
      return Promise.resolve({ ok: true, json: async () => ({}) });
    });

    loadModules();
    await new Promise(r => setTimeout(r, 20));

    expect(document.getElementById('serversList').innerHTML).toContain('backend');
    expect(document.getElementById('serversList').innerHTML).not.toContain('local');
    expect(document.getElementById('llmModel').value).toBe('gpt-4o');
    expect(document.getElementById('llmModel').value).not.toBe('local-model');
  });

  test('TC-FE-PREF-05: chat history preference persists locally', async () => {
    global.fetch = jest.fn((url) => {
      if (url === '/api/servers') return Promise.resolve({ ok: true, json: async () => [] });
      if (url === '/api/llm/config') return Promise.resolve({ ok: false, status: 404, json: async () => ({}) });
      if (url === '/api/tools') return Promise.resolve({ ok: true, json: async () => [] });
      if (url === '/api/enterprise/token/status') return Promise.resolve({ ok: true, json: async () => ({ token_cached: false }) });
      return Promise.resolve({ ok: true, json: async () => ({}) });
    });

    loadModules();
    await new Promise(r => setTimeout(r, 20));

    const toggle = document.getElementById('includeHistoryToggle');
    toggle.checked = false;
    toggle.dispatchEvent(new Event('change'));

    expect(localStorage.setItem).toHaveBeenCalledWith('includeHistory', 'false');
  });
});
