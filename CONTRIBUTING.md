# Contributing

Thanks for contributing to MCP Client Web.

## Scope

- Keep changes aligned with the existing FastAPI backend and vanilla JavaScript frontend.
- Prefer focused changes that solve one problem well.
- Avoid unrelated refactors in the same change unless they are required to support the fix.

## Development Workflow

1. Work from the repository root.
2. Use the project virtual environment for backend work.
3. Keep backend and frontend behavior consistent when changing shared UX or API flows.
4. Update documentation in `README.md` or `docs/` when behavior or workflows change.

## Testing

Run the smallest relevant test scope first, then broaden if needed.

```bash
# Full suite
make test

# Backend only
make test-backend

# Frontend only
make test-frontend
```

Useful direct commands:

```bash
./venv/bin/python -m pytest -q tests/backend
cd tests/frontend && npm test -- --runInBand
```

## Project Areas

- `backend/main.py` — FastAPI routes and chat orchestration
- `backend/mcp_manager.py` — MCP server initialization, discovery, and tool execution
- `backend/llm_client.py` — provider adapters for OpenAI, Ollama, mock, and enterprise flows
- `backend/prompt_injection.py` — diagnostic prompt construction and classification helpers
- `backend/static/` — browser UI assets
- `tests/backend/` and `tests/frontend/` — automated coverage

## Style Expectations

- Follow the existing code style in the touched files.
- Fix problems at the root cause when possible.
- Preserve public API behavior unless the change intentionally updates it.
- Add or update tests when changing chat flow, tool execution, settings behavior, or UI interactions.

## Pull Request Checklist

- Change is scoped and explained clearly.
- Relevant tests pass.
- Documentation is updated if user-visible behavior changed.
- No secrets, tokens, or private credentials are committed.

## Questions

If requirements are unclear, start with the documents in `docs/` and the main project overview in `README.md`. For prompt-driven diagnostic behavior, see `LLM-PROMPT-INJECTION-STRATEGY.md`.
