/**
 * Jest after-framework setup — runs after Jest globals are available.
 * Resets all mocks before each test.
 */

// Reset mocks before each test (beforeEach is available here)
beforeEach(() => {
  jest.clearAllMocks();

  // Re-set fetch to a default no-op so tests don't accidentally share state
  global.fetch = jest.fn();

  // Re-set confirm to default "user confirms"
  global.confirm = jest.fn(() => true);
  global.alert = jest.fn();

  // Reset localStorage mock behaviour (global._localStorageMock set by setup-pre.js)
  if (global._localStorageMock) {
    global._localStorageMock.getItem.mockImplementation(() => null);
    global._localStorageMock.setItem.mockImplementation(() => {});
    global._localStorageMock.removeItem.mockImplementation(() => {});
    global._localStorageMock.clear.mockImplementation(() => {});
  }
});
