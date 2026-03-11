"""
Unit tests for backend.main runtime compatibility.
"""

import importlib


def test_backend_main_imports_without_runtime_annotation_errors():
    """TC-MAIN-01: backend.main imports cleanly across supported Python versions."""
    main_module = importlib.import_module("backend.main")

    assert hasattr(main_module, "app")
    assert main_module.llm_config_storage is None
