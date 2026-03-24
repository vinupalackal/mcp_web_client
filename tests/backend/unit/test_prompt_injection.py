"""Unit tests for diagnostic prompt injection helpers."""

from backend.prompt_injection import (
    build_classification_prompt,
    build_layer2_injection_prompt,
    build_system_prompt,
    classify_issue_from_text,
    infer_platform_profile,
    parse_issue_classification,
)


def test_infer_platform_profile_defaults_broadband():
    assert infer_platform_profile(["svc__process_status", "svc__device_version"]) == "Broadband"


def test_infer_platform_profile_detects_video_tooling():
    assert infer_platform_profile(["svc__audio_status", "svc__rdkshell_get_clients"]) == "Video"


def test_classify_issue_from_text_network_keywords():
    assert classify_issue_from_text("The box has no internet and DNS fails") == "Network / Connectivity"


def test_parse_issue_classification_reads_explicit_line():
    content = "I'll investigate now.\nIssue classified as: Crash / Coredump\nProceeding with tools."
    assert parse_issue_classification(content) == "Crash / Coredump"


def test_build_system_prompt_includes_strategy_sections():
    prompt = build_system_prompt(
        available_tool_names=[
            "svc__network_dns_check",
            "svc__wan_status",
            "svc__process_status",
        ],
        current_user_message="Internet is down on the WAN side",
    )

    assert "Platform profile: Broadband" in prompt
    assert "Available tools: svc__network_dns_check, svc__wan_status, svc__process_status" in prompt
    assert "Issue classified as: Network / Connectivity" in prompt
    assert "parallel tool calls" in prompt.lower()
    assert "## Diagnostic Summary" in prompt


def test_build_classification_prompt_requires_single_line_output():
    prompt = build_classification_prompt(
        available_tool_names=["svc__network_dns_check"],
        current_user_message="DNS is failing",
    )

    assert "Respond with exactly one line" in prompt
    assert "Do not call tools" in prompt
    assert "Latest user request: DNS is failing" in prompt


def test_build_layer2_injection_prompt_contains_issue_branch_steps():
    prompt = build_layer2_injection_prompt(
        classification="Network / Connectivity",
        available_tool_names=["svc__network_dns_check", "svc__wan_status"],
    )

    assert prompt is not None
    assert "Issue classified as: Network / Connectivity." in prompt
    assert "svc__network_dns_check" in prompt
    assert "svc__wan_status" in prompt