/**
 * DOM setup helper — creates the full HTML skeleton needed by app.js and settings.js.
 * Call setupFullDOM() before require()-ing any frontend script.
 */

function setupChatDOM() {
  document.body.innerHTML = `
    <div id="chatMessages"></div>
    <textarea id="messageInput"></textarea>
    <button id="sendBtn" disabled></button>
    <button id="newChatBtn"></button>
    <div id="toolsSidebarContent"></div>
    <button id="refreshToolsSidebarBtn"></button>
  `;
}

function setupSettingsDOM() {
  document.body.innerHTML = `
    <div id="settingsModal">
      <div class="modal-body">
        <button id="closeSettings"></button>

        <!-- Tabs -->
        <button class="tab-button active" data-tab="servers">Servers</button>
        <button class="tab-button" data-tab="llm">LLM</button>
        <button class="tab-button" data-tab="tools">Tools</button>

        <!-- Tab content -->
        <div id="serversTab" class="tab-content active"></div>
        <div id="llmTab" class="tab-content"></div>
        <div id="toolsTab" class="tab-content"></div>

        <!-- Server form -->
        <form id="addServerForm">
          <input id="serverAlias" />
          <input id="serverUrl" />
          <select id="authType">
            <option value="none">none</option>
            <option value="bearer">bearer</option>
            <option value="api_key">api_key</option>
          </select>
          <div id="bearerTokenGroup" style="display:none">
            <input id="bearerToken" />
          </div>
          <div id="apiKeyGroup" style="display:none">
            <input id="apiKey" />
          </div>
          <button type="submit">Add</button>
        </form>
        <div id="serversList"></div>

        <!-- LLM form -->
        <form id="llmConfigForm">
          <select id="llmProvider">
            <option value="openai">openai</option>
            <option value="ollama">ollama</option>
            <option value="mock">mock</option>
          </select>
          <input id="llmModel" />
          <input id="llmBaseUrl" />
          <div id="llmApiKeyGroup">
            <input id="llmApiKey" type="password" />
          </div>
          <input id="llmTemperature" type="number" value="0.7" />
          <button type="submit">Save</button>
        </form>

        <!-- Tools tab -->
        <div id="toolsList"></div>
        <button id="refreshToolsBtn">Refresh Tools</button>
      </div>
    </div>
    <button id="settingsBtn"></button>
  `;
}

function setupFullDOM() {
  document.body.innerHTML = `
    <!-- Chat elements -->
    <div id="chatMessages"></div>
    <textarea id="messageInput"></textarea>
    <button id="sendBtn" disabled></button>
    <button id="newChatBtn"></button>
    <div id="toolsSidebarContent"></div>
    <button id="refreshToolsSidebarBtn"></button>

    <!-- Settings elements -->
    <div id="settingsModal">
      <div class="modal-body">
        <button id="closeSettings"></button>
        <button class="tab-button active" data-tab="servers">Servers</button>
        <button class="tab-button" data-tab="llm">LLM</button>
        <button class="tab-button" data-tab="tools">Tools</button>
        <div id="serversTab" class="tab-content active"></div>
        <div id="llmTab" class="tab-content"></div>
        <div id="toolsTab" class="tab-content"></div>
        <form id="addServerForm">
          <input id="serverAlias" />
          <input id="serverUrl" />
          <select id="authType">
            <option value="none">none</option>
            <option value="bearer">bearer</option>
            <option value="api_key">api_key</option>
          </select>
          <div id="bearerTokenGroup" style="display:none"><input id="bearerToken" /></div>
          <div id="apiKeyGroup" style="display:none"><input id="apiKey" /></div>
          <button type="submit">Add</button>
        </form>
        <div id="serversList"></div>
        <form id="llmConfigForm">
          <select id="llmProvider">
            <option value="openai">openai</option>
            <option value="ollama">ollama</option>
            <option value="mock">mock</option>
          </select>
          <input id="llmModel" />
          <input id="llmBaseUrl" />
          <div id="llmApiKeyGroup"><input id="llmApiKey" type="password" /></div>
          <input id="llmTemperature" type="number" value="0.7" />
          <button type="submit">Save</button>
        </form>
        <div id="toolsList"></div>
        <button id="refreshToolsBtn">Refresh Tools</button>
      </div>
    </div>
    <button id="settingsBtn"></button>
  `;
}

module.exports = { setupChatDOM, setupSettingsDOM, setupFullDOM };
