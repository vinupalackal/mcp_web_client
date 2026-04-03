"""
Unit tests for backend.main runtime compatibility.
"""

import asyncio
import importlib

from backend.models import ChatMessage


# ---------------------------------------------------------------------------
# _should_batch_tool_results
# ---------------------------------------------------------------------------

def test_should_batch_tool_results_returns_false_at_or_below_threshold(monkeypatch):
    """Tool counts at or below the threshold must NOT use the batch path."""
    main_module = importlib.import_module("backend.main")
    monkeypatch.delenv("MCP_TOOL_BATCH_THRESHOLD", raising=False)

    assert main_module._should_batch_tool_results(0) is False
    assert main_module._should_batch_tool_results(1) is False
    assert main_module._should_batch_tool_results(2) is False
    assert main_module._should_batch_tool_results(3) is False  # exactly at threshold → sequential


def test_should_batch_tool_results_returns_true_above_threshold(monkeypatch):
    """Tool counts above the threshold must use the batch path."""
    main_module = importlib.import_module("backend.main")
    monkeypatch.delenv("MCP_TOOL_BATCH_THRESHOLD", raising=False)

    assert main_module._should_batch_tool_results(4) is True
    assert main_module._should_batch_tool_results(8) is True
    assert main_module._should_batch_tool_results(128) is True


def test_should_batch_tool_results_respects_env_override(monkeypatch):
    """MCP_TOOL_BATCH_THRESHOLD env var must override the default of 3."""
    main_module = importlib.import_module("backend.main")
    monkeypatch.setenv("MCP_TOOL_BATCH_THRESHOLD", "5")

    assert main_module._should_batch_tool_results(5) is False   # at threshold → sequential
    assert main_module._should_batch_tool_results(6) is True    # above threshold → batch
    assert main_module._should_batch_tool_results(3) is False   # below threshold → sequential


# ---------------------------------------------------------------------------
# _stream_split_phase_tool_calls
# ---------------------------------------------------------------------------

def _make_llm_response(tool_names: list[str]) -> dict:
    """Build a minimal LLM response dict with the given tool call names."""
    return {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": f"call_{name}",
                        "type": "function",
                        "function": {"name": name, "arguments": "{}"},
                    }
                    for name in tool_names
                ],
            },
            "finish_reason": "tool_calls" if tool_names else "stop",
        }]
    }


class _FakeChunkClient:
    """LLM client that returns pre-canned responses keyed by chunk index."""

    def __init__(self, chunk_responses: dict[int, list[str]], *, delays: dict[int, float] | None = None):
        self._responses = chunk_responses  # 1-indexed {chunk_idx: [tool_name, ...]}
        self._delays = delays or {}
        self.call_order: list[int] = []
        self._call_count = 0

    async def chat_completion(self, messages, tools):
        self._call_count += 1
        call_idx = self._call_count
        self.call_order.append(call_idx)
        if call_idx in self._delays:
            await asyncio.sleep(self._delays[call_idx])
        return _make_llm_response(self._responses.get(call_idx, []))


async def _collect_stream(gen) -> list[tuple[int, list, int]]:
    """Drain an async generator into a list of (chunk_index, new_calls, skipped)."""
    results = []
    async for item in gen:
        results.append(item)
    return results


def test_stream_split_phase_sequential_yields_once_per_chunk():
    """Sequential mode must yield exactly N items, one per chunk, in order."""
    main_module = importlib.import_module("backend.main")

    client = _FakeChunkClient({1: ["svc__cpu"], 2: ["svc__mem"], 3: ["svc__disk"]})
    tool_chunks = [[{"function": {"name": t, "arguments": {}}}] for t in ["svc__cpu", "svc__mem", "svc__disk"]]

    results = asyncio.run(_collect_stream(
        main_module._stream_split_phase_tool_calls(
            llm_client=client,
            messages_snapshot=[{"role": "user", "content": "check all"}],
            tool_chunks=tool_chunks,
            split_mode="sequential",
            request_mode="targeted_status",
            request_mode_details={"confidence": 0.5},
            extract_tool_calls_from_content=lambda c, t: [],
        )
    ))

    assert len(results) == 3
    chunk_indices = [r[0] for r in results]
    assert chunk_indices == [1, 2, 3]
    all_tool_names = [
        r[1][0]["function"]["name"] for r in results if r[1]
    ]
    assert all_tool_names == ["svc__cpu", "svc__mem", "svc__disk"]


def test_stream_split_phase_concurrent_yields_for_all_chunks():
    """Concurrent mode must yield one item per chunk (order may vary)."""
    main_module = importlib.import_module("backend.main")

    client = _FakeChunkClient({1: ["svc__cpu"], 2: ["svc__mem"]})
    tool_chunks = [
        [{"function": {"name": "svc__cpu", "arguments": {}}}],
        [{"function": {"name": "svc__mem", "arguments": {}}}],
    ]

    results = asyncio.run(_collect_stream(
        main_module._stream_split_phase_tool_calls(
            llm_client=client,
            messages_snapshot=[{"role": "user", "content": "check"}],
            tool_chunks=tool_chunks,
            split_mode="concurrent",
            request_mode="targeted_status",
            request_mode_details={"confidence": 0.5},
            extract_tool_calls_from_content=lambda c, t: [],
        )
    ))

    assert len(results) == 2
    all_tool_names = sorted(r[1][0]["function"]["name"] for r in results if r[1])
    assert all_tool_names == ["svc__cpu", "svc__mem"]


def test_stream_split_phase_incremental_dedup_across_chunks():
    """A tool call that appears in two chunks must be skipped on the second yield."""
    main_module = importlib.import_module("backend.main")

    # Both chunks return the same tool name with the same args.
    client = _FakeChunkClient({1: ["svc__get_uptime"], 2: ["svc__get_uptime"]})
    tool_chunks = [
        [{"function": {"name": "svc__get_uptime", "arguments": {}}}],
        [{"function": {"name": "svc__get_uptime", "arguments": {}}}],
    ]

    results = asyncio.run(_collect_stream(
        main_module._stream_split_phase_tool_calls(
            llm_client=client,
            messages_snapshot=[{"role": "user", "content": "uptime"}],
            tool_chunks=tool_chunks,
            split_mode="sequential",
            request_mode="targeted_status",
            request_mode_details={"confidence": 0.5},
            extract_tool_calls_from_content=lambda c, t: [],
        )
    ))

    assert len(results) == 2
    first_chunk_index, first_new, first_skipped = results[0]
    second_chunk_index, second_new, second_skipped = results[1]

    # First chunk: 1 new call, 0 skipped
    assert len(first_new) == 1
    assert first_skipped == 0

    # Second chunk: 0 new calls, 1 skipped
    assert len(second_new) == 0
    assert second_skipped == 1


def test_stream_split_phase_chunk_failure_yields_empty_call_list():
    """A failing LLM chunk must yield an empty call list rather than raising."""
    main_module = importlib.import_module("backend.main")

    class _ErrorClient:
        _call = 0

        async def chat_completion(self, messages, tools):
            _ErrorClient._call += 1
            if _ErrorClient._call == 1:
                raise RuntimeError("simulated timeout")
            return _make_llm_response(["svc__mem"])

    tool_chunks = [
        [{"function": {"name": "svc__cpu", "arguments": {}}}],
        [{"function": {"name": "svc__mem", "arguments": {}}}],
    ]

    results = asyncio.run(_collect_stream(
        main_module._stream_split_phase_tool_calls(
            llm_client=_ErrorClient(),
            messages_snapshot=[{"role": "user", "content": "check"}],
            tool_chunks=tool_chunks,
            split_mode="sequential",
            request_mode="targeted_status",
            request_mode_details={"confidence": 0.5},
            extract_tool_calls_from_content=lambda c, t: [],
        )
    ))

    assert len(results) == 2
    failed_chunk = next(r for r in results if r[0] == 1)
    good_chunk = next(r for r in results if r[0] == 2)
    assert failed_chunk[1] == []  # empty — no exception propagated
    assert good_chunk[1][0]["function"]["name"] == "svc__mem"


def test_stream_split_phase_early_stop_sequential_stops_after_first_real_tool():
    """Sequential mode with direct_fact early-stop must stop after the first chunk with calls."""
    main_module = importlib.import_module("backend.main")

    dispatched_chunks = []

    class _TrackingClient:
        _call = 0

        async def chat_completion(self, messages, tools):
            _TrackingClient._call += 1
            dispatched_chunks.append(_TrackingClient._call)
            if _TrackingClient._call == 1:
                return _make_llm_response(["svc__uptime"])
            return _make_llm_response(["svc__mem"])

    tool_chunks = [
        [{"function": {"name": "svc__uptime", "arguments": {}}}],
        [{"function": {"name": "svc__mem", "arguments": {}}}],
        [{"function": {"name": "svc__disk", "arguments": {}}}],
    ]

    results = asyncio.run(_collect_stream(
        main_module._stream_split_phase_tool_calls(
            llm_client=_TrackingClient(),
            messages_snapshot=[{"role": "user", "content": "uptime"}],
            tool_chunks=tool_chunks,
            split_mode="sequential",
            request_mode="direct_fact",
            request_mode_details={"confidence": 0.85},
            extract_tool_calls_from_content=lambda c, t: [],
        )
    ))

    # Only one chunk should have been dispatched
    assert dispatched_chunks == [1]
    # Only one yield with one new call
    assert len(results) == 1
    assert results[0][1][0]["function"]["name"] == "svc__uptime"


def test_stream_split_phase_early_stop_concurrent_cancels_pending_tasks():
    """Concurrent mode with direct_fact early-stop must cancel slower chunks once satisfied."""
    main_module = importlib.import_module("backend.main")

    started = []
    cancelled = []

    class _SlowClient:
        _call = 0

        async def chat_completion(self, messages, tools):
            _SlowClient._call += 1
            idx = _SlowClient._call
            started.append(idx)
            try:
                if idx == 1:
                    await asyncio.sleep(0)          # fast
                    return _make_llm_response(["svc__fast_tool"])
                else:
                    await asyncio.sleep(10)         # will be cancelled
                    return _make_llm_response(["svc__slow_tool"])
            except asyncio.CancelledError:
                cancelled.append(idx)
                raise

    tool_chunks = [
        [{"function": {"name": "svc__fast_tool", "arguments": {}}}],
        [{"function": {"name": "svc__slow_tool_a", "arguments": {}}}],
        [{"function": {"name": "svc__slow_tool_b", "arguments": {}}}],
    ]

    results = asyncio.run(_collect_stream(
        main_module._stream_split_phase_tool_calls(
            llm_client=_SlowClient(),
            messages_snapshot=[{"role": "user", "content": "fast check"}],
            tool_chunks=tool_chunks,
            split_mode="concurrent",
            request_mode="direct_fact",
            request_mode_details={"confidence": 0.9},
            extract_tool_calls_from_content=lambda c, t: [],
        )
    ))

    # Generator stopped after first satisfying chunk
    assert len(results) == 1
    assert results[0][1][0]["function"]["name"] == "svc__fast_tool"
    # All 3 chunks were started (concurrent fires all at once)
    assert len(started) == 3
    # Slow chunks were cancelled
    assert set(cancelled) == {2, 3}


# ---------------------------------------------------------------------------
# _run_pipeline_execution
# ---------------------------------------------------------------------------

def _make_simple_stream(batches: list[tuple[int, list[str], int]]):
    """Build an async generator yielding (chunk_index, calls, skipped) from a list."""
    async def _gen():
        for chunk_index, tool_names, skipped in batches:
            calls = [
                {
                    "id": f"call_{name}",
                    "type": "function",
                    "function": {"name": name, "arguments": "{}"},
                }
                for name in tool_names
            ]
            yield chunk_index, calls, skipped
    return _gen()


async def _fake_run_mcp_tool(pc: dict) -> dict:
    """Minimal stand-in for the real _run_one_mcp_tool closure."""
    return {
        **pc,
        "result_content": f"ok:{pc['namespaced_tool_name']}",
        "tool_result": f"ok:{pc['namespaced_tool_name']}",
        "success": True,
        "duration_ms": 1,
    }


def test_run_pipeline_execution_returns_all_parsed_and_results_map():
    """_run_pipeline_execution must return a parsed list and results_map for each tool call."""
    main_module = importlib.import_module("backend.main")

    stream = _make_simple_stream([
        (1, ["svc__cpu", "svc__mem"], 0),
        (2, ["svc__disk"], 0),
    ])

    all_parsed, results_map = asyncio.run(
        main_module._run_pipeline_execution(
            stream=stream,
            run_mcp_tool=_fake_run_mcp_tool,
            tool_concurrency=4,
            num_chunks=2,
        )
    )

    assert len(all_parsed) == 3
    tool_names = [pc["namespaced_tool_name"] for pc in all_parsed]
    assert tool_names == ["svc__cpu", "svc__mem", "svc__disk"]

    assert len(results_map) == 3
    for pc in all_parsed:
        assert pc["tool_id"] in results_map
        assert results_map[pc["tool_id"]]["success"] is True


def test_run_pipeline_execution_defers_mcp_repeated_exec():
    """mcp_repeated_exec must appear in all_parsed but NOT be executed (not in results_map)."""
    main_module = importlib.import_module("backend.main")

    stream = _make_simple_stream([
        (1, ["svc__cpu", "mcp_repeated_exec"], 0),
    ])

    executed_names = []

    async def _tracking_run(pc):
        executed_names.append(pc["namespaced_tool_name"])
        return await _fake_run_mcp_tool(pc)

    all_parsed, results_map = asyncio.run(
        main_module._run_pipeline_execution(
            stream=stream,
            run_mcp_tool=_tracking_run,
            tool_concurrency=4,
            num_chunks=1,
        )
    )

    # mcp_repeated_exec must be in all_parsed
    parsed_names = [pc["namespaced_tool_name"] for pc in all_parsed]
    assert "mcp_repeated_exec" in parsed_names

    # mcp_repeated_exec must NOT have been executed
    assert "mcp_repeated_exec" not in executed_names

    # Its tool_id must NOT appear in results_map
    repeated_exec_pc = next(p for p in all_parsed if p["namespaced_tool_name"] == "mcp_repeated_exec")
    assert repeated_exec_pc["tool_id"] not in results_map

    # The regular tool must have been executed
    assert "svc__cpu" in executed_names


def test_run_pipeline_execution_records_failed_tasks_in_results_map():
    """Tasks that raise must appear in results_map with success=False rather than propagating."""
    main_module = importlib.import_module("backend.main")

    stream = _make_simple_stream([
        (1, ["svc__good", "svc__bad"], 0),
    ])

    async def _flaky_run(pc):
        if pc["namespaced_tool_name"] == "svc__bad":
            raise RuntimeError("MCP connection refused")
        return await _fake_run_mcp_tool(pc)

    all_parsed, results_map = asyncio.run(
        main_module._run_pipeline_execution(
            stream=stream,
            run_mcp_tool=_flaky_run,
            tool_concurrency=4,
            num_chunks=1,
        )
    )

    assert len(all_parsed) == 2
    assert len(results_map) == 2

    good_id = next(p["tool_id"] for p in all_parsed if p["namespaced_tool_name"] == "svc__good")
    bad_id = next(p["tool_id"] for p in all_parsed if p["namespaced_tool_name"] == "svc__bad")

    assert results_map[good_id]["success"] is True
    assert results_map[bad_id]["success"] is False
    assert "MCP connection refused" in results_map[bad_id]["result_content"]


def test_run_pipeline_execution_respects_tool_concurrency_semaphore():
    """Concurrent executions must never exceed tool_concurrency at any moment."""
    main_module = importlib.import_module("backend.main")

    concurrency_high_watermark = 0
    currently_running = 0

    async def _counting_run(pc):
        nonlocal concurrency_high_watermark, currently_running
        currently_running += 1
        concurrency_high_watermark = max(concurrency_high_watermark, currently_running)
        await asyncio.sleep(0)  # yield so other tasks can start
        currently_running -= 1
        return await _fake_run_mcp_tool(pc)

    # 6 tools across 2 chunks, concurrency cap = 2
    stream = _make_simple_stream([
        (1, ["t1", "t2", "t3"], 0),
        (2, ["t4", "t5", "t6"], 0),
    ])

    all_parsed, results_map = asyncio.run(
        main_module._run_pipeline_execution(
            stream=stream,
            run_mcp_tool=_counting_run,
            tool_concurrency=2,
            num_chunks=2,
        )
    )

    assert len(all_parsed) == 6
    assert concurrency_high_watermark <= 2


def test_run_pipeline_execution_empty_stream_returns_empty_outputs():
    """An empty stream must return empty all_parsed and empty results_map without error."""
    main_module = importlib.import_module("backend.main")

    stream = _make_simple_stream([])

    all_parsed, results_map = asyncio.run(
        main_module._run_pipeline_execution(
            stream=stream,
            run_mcp_tool=_fake_run_mcp_tool,
            tool_concurrency=4,
            num_chunks=0,
        )
    )

    assert all_parsed == []
    assert results_map == {}
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


def test_select_one_tool_from_candidate_group_prefers_first_available_match():
    """Direct-route candidate groups should resolve to one preferred tool only."""
    main_module = importlib.import_module("backend.main")

    selected = main_module._select_one_tool_from_candidate_group(
        ["get_system_uptime", "get_uptime"],
        [
            "home_mcp_server__get_uptime",
            "home_mcp_server__get_system_uptime",
            "home_mcp_server__server_info",
        ],
    )

    assert selected == "home_mcp_server__get_system_uptime"


def test_select_direct_tool_route_chooses_one_tool_per_candidate_group():
    """Direct routing should keep one preferred tool from each semantic alternative group."""
    main_module = importlib.import_module("backend.main")

    route = main_module._select_direct_tool_route(
        "uptime?",
        [
            "home_mcp_server__server_info",
            "home_mcp_server__get_uptime",
            "home_mcp_server__get_system_uptime",
        ],
    )

    assert route is not None
    assert route["route_name"] == "uptime"
    assert route["allowed_tool_names"] == [
        "home_mcp_server__get_system_uptime",
        "home_mcp_server__server_info",
    ]


def test_select_direct_tool_route_prefers_one_tool_for_free_memory_group():
    """free_memory route should resolve one preferred tool from its overlapping alternatives."""
    main_module = importlib.import_module("backend.main")

    route = main_module._select_direct_tool_route(
        "How much free memory does the device have?",
        [
            "svc__system_memory_stats",
            "svc__get_memory_info",
            "svc__system_memory_free",
        ],
    )

    assert route is not None
    assert route["route_name"] == "free_memory"
    assert route["allowed_tool_names"] == ["svc__system_memory_free"]


def test_select_direct_tool_route_prefers_one_tool_for_disk_usage_group():
    """disk_usage route should resolve one preferred tool from its overlapping alternatives."""
    main_module = importlib.import_module("backend.main")

    route = main_module._select_direct_tool_route(
        "show disk usage",
        [
            "svc__get_disk_stats",
            "svc__check_disk_space",
            "svc__get_disk_usage",
        ],
    )

    assert route is not None
    assert route["route_name"] == "disk_usage"
    assert route["allowed_tool_names"] == ["svc__get_disk_usage"]


def test_repeated_exec_triage_instruction_requests_explanatory_output_format():
    """Repeated execution synthesis should require the richer triaging output structure."""
    main_module = importlib.import_module("backend.main")

    prompt = main_module._build_repeated_exec_triage_instruction(
        target_tool_name="get_memory_info",
        repeat_count=4,
    )

    assert "respond in triaging output format" in prompt
    assert "Explain the observed behaviour across all 4 runs of `get_memory_info`" in prompt
    assert "## Diagnostic Summary" in prompt
    assert "### Trend Explanation" in prompt
    assert "### Root Cause Assessment" in prompt
    assert "### Recommended Actions" in prompt


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


# ---------------------------------------------------------------------------
# _find_matching_tool_names
# ---------------------------------------------------------------------------

def _main():
    return importlib.import_module("backend.main")


class TestFindMatchingToolNames:

    def test_exact_match_on_full_namespaced_name(self):
        """A candidate that is the full namespaced name resolves directly."""
        m = _main()
        result = m._find_matching_tool_names(
            ["svc__ping"],
            ["svc__ping", "svc__uptime"],
        )
        assert result == ["svc__ping"]

    def test_bare_name_matches_namespaced_tool(self):
        """A bare candidate like 'get_uptime' should match 'home__get_uptime'."""
        m = _main()
        result = m._find_matching_tool_names(
            ["get_uptime"],
            ["home_mcp__get_uptime", "home_mcp__server_info"],
        )
        assert result == ["home_mcp__get_uptime"]

    def test_priority_order_preserved(self):
        """Earlier candidates in the list take priority over later ones."""
        m = _main()
        result = m._find_matching_tool_names(
            ["get_system_uptime", "get_uptime"],
            ["svc__get_uptime", "svc__get_system_uptime"],
        )
        # get_system_uptime should come first since it's listed first in candidates
        assert result[0] == "svc__get_system_uptime"

    def test_no_match_returns_empty_list(self):
        """When no candidate matches, an empty list is returned."""
        m = _main()
        result = m._find_matching_tool_names(
            ["get_memory_info"],
            ["svc__get_uptime", "svc__server_info"],
        )
        assert result == []

    def test_no_duplicates_in_result(self):
        """The same namespaced tool is never returned twice even if multiple candidates match it."""
        m = _main()
        # Both 'get_system_uptime' and the full namespaced name resolve to the same tool
        result = m._find_matching_tool_names(
            ["svc__get_system_uptime", "get_system_uptime"],
            ["svc__get_system_uptime"],
        )
        assert result == ["svc__get_system_uptime"]
        assert len(result) == 1

    def test_multiple_candidates_multiple_results(self):
        """Multiple distinct candidates yield multiple resolved tools."""
        m = _main()
        result = m._find_matching_tool_names(
            ["get_uptime", "server_info"],
            ["svc__get_uptime", "svc__server_info", "svc__cpu_usage"],
        )
        assert "svc__get_uptime" in result
        assert "svc__server_info" in result
        assert "svc__cpu_usage" not in result


# ---------------------------------------------------------------------------
# _select_one_tool_from_candidate_group (extended)
# ---------------------------------------------------------------------------

class TestSelectOneToolFromCandidateGroup:

    def test_returns_none_when_no_match(self):
        """Returns None when none of the candidates are available."""
        m = _main()
        result = m._select_one_tool_from_candidate_group(
            ["get_uptime", "get_system_uptime"],
            ["svc__cpu_usage", "svc__memory_free"],
        )
        assert result is None

    def test_returns_none_for_empty_candidates(self):
        """Empty candidate group always returns None."""
        m = _main()
        assert m._select_one_tool_from_candidate_group([], ["svc__uptime"]) is None

    def test_returns_none_for_empty_available(self):
        """No available tools always returns None."""
        m = _main()
        assert m._select_one_tool_from_candidate_group(["get_uptime"], []) is None

    def test_picks_first_available_when_multiple_match(self):
        """When multiple alternatives exist, picks the highest-priority available one."""
        m = _main()
        # Both tools available; 'get_system_uptime' is listed first → preferred
        result = m._select_one_tool_from_candidate_group(
            ["get_system_uptime", "get_uptime"],
            ["svc__get_system_uptime", "svc__get_uptime"],
        )
        assert result == "svc__get_system_uptime"

    def test_falls_back_to_second_when_first_unavailable(self):
        """Falls back to the next candidate when the preferred one is not available."""
        m = _main()
        result = m._select_one_tool_from_candidate_group(
            ["get_system_uptime", "get_uptime"],
            ["svc__get_uptime"],           # only the fallback is present
        )
        assert result == "svc__get_uptime"


# ---------------------------------------------------------------------------
# _dedupe_llm_tool_catalog
# ---------------------------------------------------------------------------

def _tool(name: str) -> dict:
    return {"type": "function", "function": {"name": name, "description": f"tool {name}"}}


class TestDeduplicateLLMToolCatalog:

    def test_removes_exact_duplicates_keeping_first_occurrence(self):
        m = _main()
        catalog = [_tool("svc__ping"), _tool("svc__ping"), _tool("svc__uptime")]
        result = m._dedupe_llm_tool_catalog(catalog, context_label="test")
        assert [t["function"]["name"] for t in result] == ["svc__ping", "svc__uptime"]

    def test_no_duplicates_returns_original_order(self):
        m = _main()
        catalog = [_tool("a"), _tool("b"), _tool("c")]
        result = m._dedupe_llm_tool_catalog(catalog, context_label="test")
        assert [t["function"]["name"] for t in result] == ["a", "b", "c"]

    def test_empty_catalog_returns_empty(self):
        m = _main()
        assert m._dedupe_llm_tool_catalog([], context_label="test") == []

    def test_tool_without_name_is_kept(self):
        """Entries with no function name are passed through unchanged."""
        m = _main()
        nameless = {"type": "function", "function": {}}
        result = m._dedupe_llm_tool_catalog([nameless, _tool("a")], context_label="test")
        assert result[0] == nameless
        assert result[1]["function"]["name"] == "a"

    def test_three_duplicates_collapses_to_one(self):
        m = _main()
        catalog = [_tool("dup")] * 3 + [_tool("unique")]
        result = m._dedupe_llm_tool_catalog(catalog, context_label="test")
        assert [t["function"]["name"] for t in result] == ["dup", "unique"]


# ---------------------------------------------------------------------------
# _dedupe_llm_tool_catalog_and_chunks
# ---------------------------------------------------------------------------

class TestDeduplicateLLMToolCatalogAndChunks:

    def test_dedupes_flat_catalog_and_all_chunks(self):
        m = _main()
        catalog = [_tool("a"), _tool("a"), _tool("b")]
        chunks = [
            [_tool("a"), _tool("a")],
            [_tool("b"), _tool("b"), _tool("c")],
        ]
        deduped_catalog, deduped_chunks = m._dedupe_llm_tool_catalog_and_chunks(
            catalog, chunks, context_label="test"
        )
        assert [t["function"]["name"] for t in deduped_catalog] == ["a", "b"]
        assert [t["function"]["name"] for t in deduped_chunks[0]] == ["a"]
        assert [t["function"]["name"] for t in deduped_chunks[1]] == ["b", "c"]

    def test_returns_same_length_chunk_list(self):
        m = _main()
        catalog = [_tool("x")]
        chunks = [[_tool("x")], [_tool("y")], [_tool("z")]]
        _, deduped_chunks = m._dedupe_llm_tool_catalog_and_chunks(
            catalog, chunks, context_label="test"
        )
        assert len(deduped_chunks) == 3

    def test_empty_inputs_return_empty_outputs(self):
        m = _main()
        catalog, chunks = m._dedupe_llm_tool_catalog_and_chunks([], [], context_label="test")
        assert catalog == []
        assert chunks == []


# ---------------------------------------------------------------------------
# _rechunk_llm_tool_catalog
# ---------------------------------------------------------------------------

class TestRechunkLLMToolCatalog:

    def test_single_chunk_when_tools_fit(self):
        m = _main()
        catalog = [_tool(f"t{i}") for i in range(5)]
        chunks = m._rechunk_llm_tool_catalog(
            catalog, effective_limit=10, include_virtual_repeated=False
        )
        assert len(chunks) == 1
        assert len(chunks[0]) == 5

    def test_splits_into_multiple_chunks(self):
        m = _main()
        catalog = [_tool(f"t{i}") for i in range(6)]
        chunks = m._rechunk_llm_tool_catalog(
            catalog, effective_limit=3, include_virtual_repeated=False
        )
        assert len(chunks) == 2
        assert len(chunks[0]) == 3
        assert len(chunks[1]) == 3

    def test_virtual_repeated_appended_to_every_chunk(self):
        """When include_virtual_repeated=True, mcp_repeated_exec appears in every chunk."""
        m = _main()
        real_tools = [_tool(f"t{i}") for i in range(4)]
        virtual = {"type": "function", "function": {"name": "mcp_repeated_exec"}}
        catalog = real_tools + [virtual]
        chunks = m._rechunk_llm_tool_catalog(
            catalog, effective_limit=3, include_virtual_repeated=True
        )
        # effective_chunk_size = 3 - 1 = 2 real tools per chunk → 2 chunks
        assert len(chunks) == 2
        for chunk in chunks:
            names = [t["function"]["name"] for t in chunk]
            assert "mcp_repeated_exec" in names

    def test_virtual_excluded_when_flag_false(self):
        """include_virtual_repeated=False only removes the reserved slot from chunk-size;
        the virtual tool is still appended to each chunk from the input catalog.
        Use False when the caller has already stripped mcp_repeated_exec from the catalog."""
        m = _main()
        # When catalog has NO virtual tool and flag is False, chunks are clean.
        catalog = [_tool("a"), _tool("b")]
        chunks = m._rechunk_llm_tool_catalog(
            catalog, effective_limit=5, include_virtual_repeated=False
        )
        for chunk in chunks:
            names = [t["function"]["name"] for t in chunk]
            assert "mcp_repeated_exec" not in names

    def test_empty_catalog_returns_single_empty_chunk(self):
        m = _main()
        chunks = m._rechunk_llm_tool_catalog(
            [], effective_limit=10, include_virtual_repeated=False
        )
        assert chunks == [[]]

    def test_odd_remainder_handled(self):
        """A catalog that doesn't divide evenly should produce a smaller last chunk."""
        m = _main()
        catalog = [_tool(f"t{i}") for i in range(7)]
        chunks = m._rechunk_llm_tool_catalog(
            catalog, effective_limit=3, include_virtual_repeated=False
        )
        total_tools = sum(len(c) for c in chunks)
        assert total_tools == 7
        # Last chunk may be smaller
        assert len(chunks[-1]) <= 3


# ---------------------------------------------------------------------------
# _narrow_tools_by_domain
# ---------------------------------------------------------------------------

class TestNarrowToolsByDomain:

    def test_no_domains_returns_full_catalog(self):
        m = _main()
        catalog = [_tool("svc__get_uptime"), _tool("svc__audio_play")]
        result = m._narrow_tools_by_domain(catalog, [])
        assert result == catalog

    def test_filters_to_matching_domain_keywords(self):
        m = _main()
        catalog = [
            _tool("svc__get_uptime"),
            _tool("svc__memory_free"),
            _tool("svc__audio_play"),
        ]
        result = m._narrow_tools_by_domain(catalog, ["memory"])
        names = [t["function"]["name"] for t in result]
        assert "svc__memory_free" in names
        assert "svc__get_uptime" not in names
        assert "svc__audio_play" not in names

    def test_virtual_mcp_repeated_exec_always_preserved(self):
        """mcp_repeated_exec must survive domain narrowing regardless of domain keywords."""
        m = _main()
        virtual = {"type": "function", "function": {"name": "mcp_repeated_exec"}}
        catalog = [_tool("svc__audio_play"), virtual]
        result = m._narrow_tools_by_domain(catalog, ["memory"])
        names = [t["function"]["name"] for t in result]
        assert "mcp_repeated_exec" in names

    def test_falls_back_to_full_catalog_when_no_tools_match(self):
        """Safety net: if narrowing would remove everything, the full catalog is returned."""
        m = _main()
        catalog = [_tool("svc__audio_play"), _tool("svc__video_stream")]
        result = m._narrow_tools_by_domain(catalog, ["memory"])
        assert result == catalog

    def test_unknown_domain_returns_full_catalog(self):
        """An unrecognised domain key (no keywords) should not narrow anything."""
        m = _main()
        catalog = [_tool("svc__x"), _tool("svc__y")]
        result = m._narrow_tools_by_domain(catalog, ["does_not_exist_domain"])
        assert result == catalog

    def test_multiple_domains_union_keywords(self):
        """Multiple domains contribute their keywords as a union."""
        m = _main()
        catalog = [
            _tool("svc__memory_free"),
            _tool("svc__get_uptime"),
            _tool("svc__audio_play"),
        ]
        result = m._narrow_tools_by_domain(catalog, ["memory", "uptime"])
        names = [t["function"]["name"] for t in result]
        assert "svc__memory_free" in names
        assert "svc__get_uptime" in names
        assert "svc__audio_play" not in names


# ---------------------------------------------------------------------------
# _select_direct_tool_route (edge cases)
# ---------------------------------------------------------------------------

class TestSelectDirectToolRouteEdgeCases:

    def test_returns_none_for_diagnostic_keyword(self):
        """Diagnostic keywords like 'diagnose' must suppress direct routing."""
        m = _main()
        route = m._select_direct_tool_route(
            "diagnose why the device is slow",
            ["svc__get_uptime", "svc__server_info"],
        )
        assert route is None

    def test_returns_none_when_no_tools_available(self):
        """Route resolves to None if no matching tools are in the available list."""
        m = _main()
        route = m._select_direct_tool_route(
            "how long has this been running?",
            [],
        )
        assert route is None

    def test_returns_none_for_empty_message(self):
        """Empty or whitespace-only messages must not match any route."""
        m = _main()
        assert m._select_direct_tool_route("", ["svc__get_uptime"]) is None
        assert m._select_direct_tool_route("   ", ["svc__get_uptime"]) is None

    def test_cpu_route_excludes_unrelated_tools(self):
        """CPU route should only expose tools that matched the candidate groups."""
        m = _main()
        route = m._select_direct_tool_route(
            "show cpu usage",
            ["svc__get_cpu_usage", "svc__get_uptime", "svc__memory_free"],
        )
        assert route is not None
        assert route["route_name"] == "cpu_usage"
        uptime_in_allowed = any("uptime" in n for n in route["allowed_tool_names"])
        assert not uptime_in_allowed

    def test_wan_ip_route_resolves(self):
        """WAN IP route matches IP-address queries."""
        m = _main()
        route = m._select_direct_tool_route(
            "what is the wan ip address?",
            ["svc__get_wan_ip_config", "svc__get_wan_connection_status"],
        )
        assert route is not None
        assert route["route_name"] == "wan_ip"

    def test_kernel_logs_route_resolves(self):
        """Kernel/dmesg log queries should match the kernel_logs route."""
        m = _main()
        route = m._select_direct_tool_route(
            "show dmesg logs",
            ["svc__get_kernel_logs"],
        )
        assert route is not None
        assert route["route_name"] == "kernel_logs"
