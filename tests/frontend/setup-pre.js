/**
 * Pre-framework setup — runs BEFORE the test framework (Jest globals) are injected.
 * Only set up global variables here — no beforeEach/afterEach/describe/test.
 */

// ── fetch mock ───────────────────────────────────────────────────────────────
global.fetch = jest.fn();

// ── localStorage mock ────────────────────────────────────────────────────────
const localStorageMock = (() => {
  let store = {};
  return {
    getItem: jest.fn((key) => store[key] ?? null),
    setItem: jest.fn((key, value) => { store[key] = String(value); }),
    removeItem: jest.fn((key) => { delete store[key]; }),
    clear: jest.fn(() => { store = {}; }),
    get length() { return Object.keys(store).length; },
  };
})();

Object.defineProperty(global, 'localStorage', {
  value: localStorageMock,
  writable: true,
});

// Expose the mock so setup.js can reference it in beforeEach
global._localStorageMock = localStorageMock;

// ── window.confirm / alert ───────────────────────────────────────────────────
global.confirm = jest.fn(() => true);
global.alert = jest.fn();
