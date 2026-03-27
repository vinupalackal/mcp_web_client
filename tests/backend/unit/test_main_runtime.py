"""
Unit tests for backend.main runtime compatibility.
"""

import asyncio
import importlib

from backend.models import ChatMessage


def test_backend_main_imports_without_runtime_annotation_errors():
    """TC-MAIN-01: backend.main imports cleanly across supported Python versions."""
    main_module = importlib.import_module("backend.main")

    assert hasattr(main_module, "app")
    assert main_module.llm_config_storage is None


def test_request_mode_classifier_prefers_direct_fact_for_single_metric_lookup():
    """Direct factual lookups should route to direct_fact when signals are strong."""
    main_module = importlib.import_module("backend.main")

    details = main_module._classify_request_mode_details(
        "How much free memory does the device have?",
        existing_messages=[],
        direct_tool_route={"route_name": "free_memory"},
        conversation_summary=None,
    )

    assert details["mode"] == "direct_fact"
    assert "memory" in details["domains"]
    assert details["confidence"] >= 0.45


def test_request_mode_classifier_prefers_full_diagnostic_for_why_question():
    """Root-cause style questions should route to the full diagnostic path."""
    main_module = importlib.import_module("backend.main")

    details = main_module._classify_request_mode_details(
        "Why is the device slow after reboot?",
        existing_messages=[],
        direct_tool_route=None,
        conversation_summary=None,
    )

    assert details["mode"] == "full_diagnostic"
    assert details["scores"]["full_diagnostic"] > details["scores"]["targeted_status"]


def test_request_mode_classifier_uses_follow_up_context_when_summary_exists():
    """Short follow-up turns should route to follow_up when prior context is present."""
    main_module = importlib.import_module("backend.main")

    details = main_module._classify_request_mode_details(
        "What about now?",
        existing_messages=[ChatMessage(role="user", content="check memory")],
        direct_tool_route=None,
        conversation_summary="Recent user requests: check memory on device 69.254.90.124",
    )

    assert details["mode"] == "follow_up"
    assert details["scores"]["follow_up"] >= 4


def test_request_mode_classifier_falls_back_to_targeted_status_when_ambiguous():
    """Ambiguous asks should fall back to targeted_status when confidence is weak."""
    main_module = importlib.import_module("backend.main")

    details = main_module._classify_request_mode_details(
        "memory",
        existing_messages=[],
        direct_tool_route=None,
        conversation_summary=None,
    )

    assert details["mode"] == "targeted_status"


def test_request_mode_classifier_treats_multi_step_command_as_targeted_status():
    """Command-style asks with workflow steps should avoid direct_fact routing."""
    main_module = importlib.import_module("backend.main")

    details = main_module._classify_request_mode_details(
        "ping then summarize",
        existing_messages=[],
        direct_tool_route=None,
        conversation_summary=None,
    )

    assert details["mode"] == "targeted_status"
    assert details["scores"]["targeted_status"] > details["scores"]["direct_fact"]


def test_tiny_llm_mode_classifier_is_only_used_for_ambiguous_non_direct_requests(monkeypatch):
    """Feature-flagged LLM classifier should only run for ambiguous heuristic outcomes."""
    main_module = importlib.import_module("backend.main")
    monkeypatch.setenv("MCP_ENABLE_LLM_MODE_CLASSIFIER", "true")

    ambiguous_details = {
        "mode": "targeted_status",
        "confidence": 0.33,
        "score_gap": 1,
    }
    confident_details = {
        "mode": "direct_fact",
        "confidence": 0.91,
        "score_gap": 6,
    }

    openai_config = main_module.LLMConfig(provider="openai", model="gpt-4o-mini", base_url="https://api.openai.com")
    mock_config = main_module.LLMConfig(provider="mock", model="mock", base_url="http://localhost")

    assert main_module._should_consult_llm_mode_classifier(
        ambiguous_details,
        direct_tool_route=None,
        llm_config=openai_config,
    ) is True
    assert main_module._should_consult_llm_mode_classifier(
        confident_details,
        direct_tool_route=None,
        llm_config=openai_config,
    ) is False
    assert main_module._should_consult_llm_mode_classifier(
        ambiguous_details,
        direct_tool_route={"route_name": "free_memory"},
        llm_config=openai_config,
    ) is False
    assert main_module._should_consult_llm_mode_classifier(
        ambiguous_details,
        direct_tool_route=None,
        llm_config=mock_config,
    ) is False


def test_split_phase_early_stop_only_applies_to_high_confidence_direct_fact(monkeypatch):
    """Direct-fact split pre-collection should only short-circuit when routing confidence is strong."""
    main_module = importlib.import_module("backend.main")

    monkeypatch.delenv("MCP_SPLIT_PHASE_DIRECT_FACT_EARLY_STOP_MIN_CONFIDENCE", raising=False)

    assert main_module._should_enable_split_phase_early_stop(
        request_mode="direct_fact",
        request_mode_details={"confidence": 0.81},
    ) is True
    assert main_module._should_enable_split_phase_early_stop(
        request_mode="direct_fact",
        request_mode_details={"confidence": 0.5},
    ) is False
    assert main_module._should_enable_split_phase_early_stop(
        request_mode="targeted_status",
        request_mode_details={"confidence": 0.99},
    ) is False


def test_collect_split_phase_tool_calls_cancels_pending_chunks_for_direct_fact():
    """Concurrent split pre-collection should cancel slow chunks once a direct-fact tool call is found."""
    main_module = importlib.import_module("backend.main")

    started_tools = []
    finished_tools = []
    cancelled_tools = []

    class _FakeClient:
        async def chat_completion(self, messages, tools):
            tool_name = tools[0]["function"]["name"]
            started_tools.append(tool_name)
            try:
                if tool_name == "svc__get_uptime":
                    await asyncio.sleep(0)
                    finished_tools.append(tool_name)
                    return {
                        "choices": [{
                            "message": {
                                "role": "assistant",
                                "content": "",
                                "tool_calls": [{
                                    "id": "call_uptime",
                                    "type": "function",
                                    "function": {
                                        "name": "svc__get_uptime",
                                        "arguments": "{}",
                                    },
                                }],
                            },
                            "finish_reason": "tool_calls",
                        }]
                    }

                await asyncio.sleep(1)
                finished_tools.append(tool_name)
                return {
                    "choices": [{
                        "message": {"role": "assistant", "content": "", "tool_calls": []},
                        "finish_reason": "stop",
                    }]
                }
            except asyncio.CancelledError:
                cancelled_tools.append(tool_name)
                raise

    tool_chunks = [
        [{"type": "function", "function": {"name": "svc__slow_cpu", "arguments": {}}}],
        [{"type": "function", "function": {"name": "svc__slow_memory", "arguments": {}}}],
        [{"type": "function", "function": {"name": "svc__get_uptime", "arguments": {}}}],
    ]

    tool_calls = asyncio.run(
        main_module._collect_split_phase_tool_calls(
            llm_client=_FakeClient(),
            messages_snapshot=[{"role": "user", "content": "How long has the device been up?"}],
            tool_chunks=tool_chunks,
            split_mode="concurrent",
            request_mode="direct_fact",
            request_mode_details={"confidence": 0.8},
            extract_tool_calls_from_content=lambda content, turn_number: [],
        )
    )

    assert started_tools == ["svc__slow_cpu", "svc__slow_memory", "svc__get_uptime"]
    assert tool_calls == [{
        "id": "call_uptime",
        "type": "function",
        "function": {
            "name": "svc__get_uptime",
            "arguments": "{}",
        },
    }]
    assert finished_tools == ["svc__get_uptime"]
    assert set(cancelled_tools) == {"svc__slow_cpu", "svc__slow_memory"}


def test_parse_llm_mode_classifier_response_accepts_fenced_json():
    """Tiny classifier parser should recover strict JSON from fenced content."""
    main_module = importlib.import_module("backend.main")

    parsed = main_module._parse_llm_mode_classifier_response(
        """```json
        {"mode": "follow_up", "confidence": 0.82, "reasoning": "references prior context"}
        ```"""
    )

    assert parsed == {
        "mode": "follow_up",
        "confidence": 0.82,
        "reasoning": "references prior context",
    }


def test_tiny_llm_mode_classifier_returns_parsed_result(monkeypatch):
    """Tiny classifier helper should reuse LLM plumbing and parse JSON output."""
    main_module = importlib.import_module("backend.main")

    class _FakeClient:
        async def chat_completion(self, messages, tools):
            assert tools == []
            assert messages[0]["role"] == "system"
            return {
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": '{"mode": "full_diagnostic", "confidence": 0.74, "reasoning": "asks for root cause"}',
                    }
                }]
            }

    monkeypatch.setattr(
        main_module.LLMClientFactory,
        "create",
        staticmethod(lambda config, enterprise_access_token=None: _FakeClient()),
    )

    result = asyncio.run(
        main_module._classify_request_mode_with_llm(
            llm_config=main_module.LLMConfig(
                provider="openai",
                model="gpt-4o-mini",
                base_url="https://api.openai.com",
                api_key="sk-test",
            ),
            enterprise_access_token=None,
            message_content="Why is the device slow?",
            conversation_summary="Recent user requests: check CPU on device lab-router.",
            direct_tool_route=None,
            heuristic_details={
                "mode": "targeted_status",
                "confidence": 0.31,
                "score_gap": 1,
                "domains": ["cpu"],
                "scores": {
                    "direct_fact": 1,
                    "targeted_status": 3,
                    "full_diagnostic": 3,
                    "follow_up": 0,
                },
            },
        )
    )

    assert result is not None
    assert result["mode"] == "full_diagnostic"
    assert result["confidence"] == 0.74
