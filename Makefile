PYTHON ?= $(if $(wildcard venv/bin/python),venv/bin/python,python3)
FRONTEND_DIR := tests/frontend

.PHONY: help test test-backend test-frontend

help:
	@echo "Available targets:"
	@echo "  make test          Run frontend and backend tests"
	@echo "  make test-backend  Run backend pytest suite"
	@echo "  make test-frontend Run frontend Jest suite"

test: test-frontend test-backend

test-backend:
	"$(PYTHON)" -m pytest tests/backend -q

test-frontend:
	cd "$(FRONTEND_DIR)" && npm test -- --runInBand
