/**
 * DOM setup helper — creates the full HTML skeleton needed by app.js and settings.js.
 * Call setupFullDOM() before require()-ing any frontend script.
 */

function setupChatDOM() {
  document.body.innerHTML = `
    <div id="chatMessages"></div>
    <textarea id="messageInput"></textarea>
    <button id="sendBtn" disabled></button>
    <button id="darkModeBtn"></button>
    <button id="settingsBtn"></button>
    <button id="newChatBtn"></button>
    <aside id="toolsSidebar" class="tools-sidebar">
      <div class="sidebar-top-section">
        <div class="tools-sidebar-header sidebar-primary-header">
          <h3>Workspace</h3>
          <div class="sidebar-header-actions">
            <button id="collapseSidebarBtn"></button>
          </div>
        </div>
        <div class="sidebar-top-scroll sidebar-tools-panel">
          <div class="tools-sidebar-header">
            <h3>Available Tools <span id="toolsCountBadge" style="display:none;"></span></h3>
            <div class="sidebar-header-actions">
              <button id="refreshToolsSidebarBtn"></button>
            </div>
          </div>
          <div class="tools-search-bar">
            <input id="toolsSearchInput" />
          </div>
          <div id="toolsSidebarContent"></div>
        </div>
      </div>
      <div class="sidebar-bottom-section">
        <div class="sidebar-bottom-scroll">
          <section class="sidebar-block sidebar-footer-panel sidebar-action-block" id="sidebarActionBlock" hidden>
            <div id="sidebarActionsContent" hidden></div>
          </section>
          <section class="sidebar-block sidebar-footer-panel sidebar-info-block" id="sidebarInfoBlock" hidden>
            <div id="sidebarInfoContent" hidden>
              <div class="sidebar-info-grid">
                <article class="sidebar-info-card">
                  <span class="sidebar-info-label">Release Version</span>
                  <strong class="sidebar-info-value">0.2.0-jsonrpc</strong>
                </article>
              </div>
              <details class="sidebar-expandable" open>
                <summary>Platforms</summary>
                <p>macOS and Linux</p>
              </details>
            </div>
          </section>
          <section class="sidebar-block sidebar-footer-panel sidebar-guide-block" id="sidebarGuideBlock" hidden>
            <div id="sidebarGuideContent" hidden></div>
          </section>
        </div>
        <div class="sidebar-footer-nav">
          <button id="actionsToggleBtn" aria-expanded="false"></button>
          <button id="infoToggleBtn" aria-expanded="false"></button>
          <button id="guideToggleBtn" aria-expanded="false"></button>
        </div>
      </div>
    </aside>
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
        <button class="tab-button" data-tab="milvus">Milvus</button>
        <button class="tab-button" data-tab="tools">Tools</button>

        <!-- Tab content -->
        <div id="serversTab" class="tab-content active"></div>
        <div id="llmTab" class="tab-content"></div>
        <div id="milvusTab" class="tab-content"></div>
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
        <button id="refreshServerHealthBtn">Check Health</button>
        <label>
          <input id="autoRefreshHealthToggle" type="checkbox" />
          Auto refresh
        </label>
        <div id="serversList"></div>

        <!-- LLM form -->
        <form id="llmConfigForm">
          <input type="radio" id="llmGatewayModeStandard" name="llmGatewayMode" value="standard" checked />
          <input type="radio" id="llmGatewayModeEnterprise" name="llmGatewayMode" value="enterprise" />
          <div id="standardLlmPanel">
          <select id="llmProvider">
            <option value="openai">openai</option>
            <option value="ollama">ollama</option>
            <option value="mock">mock</option>
          </select>
          <input id="llmModel" />
          <input id="llmBaseUrl" />
          <input id="llmTimeoutMs" type="number" value="180000" />
          <div id="llmApiKeyGroup">
            <input id="llmApiKey" type="password" />
          </div>
          </div>
          <div id="enterpriseLlmPanel" style="display:none">
            <span id="enterpriseProviderBadge"></span>
            <select id="enterpriseModel"></select>
            <button type="button" id="addEnterpriseModelBtn">Add Model</button>
            <div id="enterpriseModelForm" style="display:none">
              <input id="enterpriseCustomModelId" />
              <input id="enterpriseCustomModelProvider" />
              <select id="enterpriseCustomModelType">
                <option value="LLM">LLM</option>
                <option value="Embedding">Embedding</option>
              </select>
              <button type="button" id="enterpriseSaveModelBtn">Save Model</button>
              <button type="button" id="enterpriseCancelModelBtn">Cancel</button>
            </div>
            <div id="enterpriseModelsList"></div>
            <input id="enterpriseGatewayUrl" />
            <select id="enterpriseAuthMethod"><option value="bearer">bearer</option></select>
            <input id="enterpriseLlmTimeoutMs" type="number" value="180000" />
            <input id="enterpriseClientId" />
            <input id="enterpriseClientSecret" type="password" />
            <input id="enterpriseTokenEndpoint" />
            <div id="enterpriseTokenStatus"></div>
            <button type="button" id="fetchEnterpriseTokenBtn">Fetch Token</button>
          </div>
          <input id="llmTemperature" type="number" value="0.7" />
          <input id="tinyModeClassifierOverrideToggle" type="checkbox" />
          <div id="tinyModeClassifierOptionsGroup" style="display:none">
            <input id="tinyModeClassifierEnabledToggle" type="checkbox" />
            <input id="tinyModeClassifierMinConfidence" type="number" value="0.60" />
            <input id="tinyModeClassifierMinScoreGap" type="number" value="3" />
            <input id="tinyModeClassifierAcceptConfidence" type="number" value="0.55" />
            <input id="tinyModeClassifierMaxTokens" type="number" value="96" />
          </div>
          <input id="includeHistoryToggle" type="checkbox" checked />
          <button type="submit">Save</button>
        </form>

        <form id="milvusConfigForm">
          <input id="milvusEnabledToggle" type="checkbox" />
          <input id="milvusUri" />
          <input id="milvusCollectionPrefix" value="mcp_client" />
          <input id="milvusRepoId" />
          <input id="milvusCollectionGeneration" value="v1" />
          <input id="milvusMaxResults" type="number" value="5" />
          <input id="milvusRetrievalTimeoutS" type="number" value="5.0" />
          <input id="milvusDegradedModeToggle" type="checkbox" checked />
          <input id="milvusConversationMemoryEnabledToggle" type="checkbox" />
          <input id="milvusConversationRetentionDays" type="number" value="7" />
          <input id="milvusToolCacheEnabledToggle" type="checkbox" />
          <input id="milvusToolCacheTtlS" type="number" value="3600" />
          <input id="milvusToolCacheAllowlist" />
          <input id="milvusExpiryCleanupEnabledToggle" type="checkbox" checked />
          <input id="milvusExpiryCleanupIntervalS" type="number" value="300" />
          <button type="submit">Save Milvus</button>
        </form>

        <!-- Tools tab -->
        <div id="toolsList"></div>
        <button id="refreshToolsBtn">Refresh Tools</button>
      </div>
    </div>
    <button id="settingsBtn"></button>
    <button id="darkModeBtn"></button>
  `;
}

function setupFullDOM() {
  document.body.innerHTML = `
    <!-- Chat elements -->
    <div id="chatMessages"></div>
    <textarea id="messageInput"></textarea>
    <button id="sendBtn" disabled></button>
    <aside id="toolsSidebar" class="tools-sidebar">
      <div class="sidebar-top-section">
        <div class="tools-sidebar-header sidebar-primary-header">
          <h3>Workspace</h3>
          <div class="sidebar-header-actions">
            <button id="collapseSidebarBtn"></button>
          </div>
        </div>
        <div class="sidebar-top-scroll sidebar-tools-panel">
          <div class="tools-sidebar-header">
            <h3>Available Tools <span id="toolsCountBadge" style="display:none;"></span></h3>
            <div class="sidebar-header-actions">
              <button id="refreshToolsSidebarBtn"></button>
            </div>
          </div>
          <div class="tools-search-bar">
            <input id="toolsSearchInput" />
          </div>
          <div id="toolsSidebarContent"></div>
        </div>
      </div>
      <div class="sidebar-bottom-section">
        <div class="sidebar-bottom-scroll">
          <section class="sidebar-block sidebar-footer-panel sidebar-action-block" id="sidebarActionBlock" hidden>
            <div id="sidebarActionsContent" hidden></div>
          </section>
          <section class="sidebar-block sidebar-footer-panel sidebar-info-block" id="sidebarInfoBlock" hidden>
            <div id="sidebarInfoContent" hidden>
              <div class="sidebar-info-grid">
                <article class="sidebar-info-card">
                  <span class="sidebar-info-label">Release Version</span>
                  <strong class="sidebar-info-value">0.2.0-jsonrpc</strong>
                </article>
              </div>
              <details class="sidebar-expandable" open>
                <summary>Platforms</summary>
                <p>macOS and Linux</p>
              </details>
            </div>
          </section>
          <section class="sidebar-block sidebar-footer-panel sidebar-guide-block" id="sidebarGuideBlock" hidden>
            <div id="sidebarGuideContent" hidden></div>
          </section>
        </div>
        <div class="sidebar-footer-nav">
          <button id="actionsToggleBtn" aria-expanded="false"></button>
          <button id="infoToggleBtn" aria-expanded="false"></button>
          <button id="guideToggleBtn" aria-expanded="false"></button>
        </div>
      </div>
    </aside>

    <!-- Settings elements -->
    <div id="settingsModal">
      <div class="modal-body">
        <button id="closeSettings"></button>
        <button class="tab-button active" data-tab="servers">Servers</button>
        <button class="tab-button" data-tab="llm">LLM</button>
        <button class="tab-button" data-tab="milvus">Milvus</button>
        <button class="tab-button" data-tab="tools">Tools</button>
        <div id="serversTab" class="tab-content active"></div>
        <div id="llmTab" class="tab-content"></div>
        <div id="milvusTab" class="tab-content"></div>
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
        <button id="refreshServerHealthBtn">Check Health</button>
        <label>
          <input id="autoRefreshHealthToggle" type="checkbox" />
          Auto refresh
        </label>
        <div id="serversList"></div>
        <form id="llmConfigForm">
          <input type="radio" id="llmGatewayModeStandard" name="llmGatewayMode" value="standard" checked />
          <input type="radio" id="llmGatewayModeEnterprise" name="llmGatewayMode" value="enterprise" />
          <div id="standardLlmPanel">
          <select id="llmProvider">
            <option value="openai">openai</option>
            <option value="ollama">ollama</option>
            <option value="mock">mock</option>
          </select>
          <input id="llmModel" />
          <input id="llmBaseUrl" />
          <input id="llmTimeoutMs" type="number" value="180000" />
          <div id="llmApiKeyGroup"><input id="llmApiKey" type="password" /></div>
          </div>
          <div id="enterpriseLlmPanel" style="display:none">
            <span id="enterpriseProviderBadge"></span>
            <select id="enterpriseModel"></select>
            <button type="button" id="addEnterpriseModelBtn">Add Model</button>
            <div id="enterpriseModelForm" style="display:none">
              <input id="enterpriseCustomModelId" />
              <input id="enterpriseCustomModelProvider" />
              <select id="enterpriseCustomModelType">
                <option value="LLM">LLM</option>
                <option value="Embedding">Embedding</option>
              </select>
              <button type="button" id="enterpriseSaveModelBtn">Save Model</button>
              <button type="button" id="enterpriseCancelModelBtn">Cancel</button>
            </div>
            <div id="enterpriseModelsList"></div>
            <input id="enterpriseGatewayUrl" />
            <select id="enterpriseAuthMethod"><option value="bearer">bearer</option></select>
            <input id="enterpriseLlmTimeoutMs" type="number" value="180000" />
            <input id="enterpriseClientId" />
            <input id="enterpriseClientSecret" type="password" />
            <input id="enterpriseTokenEndpoint" />
            <div id="enterpriseTokenStatus"></div>
            <button type="button" id="fetchEnterpriseTokenBtn">Fetch Token</button>
          </div>
          <input id="llmTemperature" type="number" value="0.7" />
          <input id="tinyModeClassifierOverrideToggle" type="checkbox" />
          <div id="tinyModeClassifierOptionsGroup" style="display:none">
            <input id="tinyModeClassifierEnabledToggle" type="checkbox" />
            <input id="tinyModeClassifierMinConfidence" type="number" value="0.60" />
            <input id="tinyModeClassifierMinScoreGap" type="number" value="3" />
            <input id="tinyModeClassifierAcceptConfidence" type="number" value="0.55" />
            <input id="tinyModeClassifierMaxTokens" type="number" value="96" />
          </div>
          <input id="includeHistoryToggle" type="checkbox" checked />
          <button type="submit">Save</button>
        </form>
        <form id="milvusConfigForm">
          <input id="milvusEnabledToggle" type="checkbox" />
          <input id="milvusUri" />
          <input id="milvusCollectionPrefix" value="mcp_client" />
          <input id="milvusRepoId" />
          <input id="milvusCollectionGeneration" value="v1" />
          <input id="milvusMaxResults" type="number" value="5" />
          <input id="milvusRetrievalTimeoutS" type="number" value="5.0" />
          <input id="milvusDegradedModeToggle" type="checkbox" checked />
          <input id="milvusConversationMemoryEnabledToggle" type="checkbox" />
          <input id="milvusConversationRetentionDays" type="number" value="7" />
          <input id="milvusToolCacheEnabledToggle" type="checkbox" />
          <input id="milvusToolCacheTtlS" type="number" value="3600" />
          <input id="milvusToolCacheAllowlist" />
          <input id="milvusExpiryCleanupEnabledToggle" type="checkbox" checked />
          <input id="milvusExpiryCleanupIntervalS" type="number" value="300" />
          <button type="submit">Save Milvus</button>
        </form>
        <div id="toolsList"></div>
        <button id="refreshToolsBtn">Refresh Tools</button>
      </div>
    </div>
    <button id="darkModeBtn"></button>
    <button id="settingsBtn"></button>
    <button id="newChatBtn"></button>    <button id="settingsBtn"></button>
    <button id="newChatBtn"></button>  `;
}

module.exports = { setupChatDOM, setupSettingsDOM, setupFullDOM };
