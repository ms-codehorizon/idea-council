import pytest
from tests.conftest import MockAdapter, SAMPLE_DEBATER_RESPONSE, SAMPLE_CRITIC_RESPONSE
from idea_council.models.session import RoleResponse
from idea_council.providers.adapter import ProviderAdapter
from idea_council.orchestrator.debate import (
    _parse_confidence,
    _parse_arguments,
    _parse_position,
    _build_reaction_context,
    run_round,
)


# --- Parser unit tests ---

def test_parse_confidence_extracts_score():
    assert _parse_confidence("CONFIDENCE: 7") == 7


def test_parse_confidence_clamps_to_valid_range():
    assert _parse_confidence("CONFIDENCE: 0") == 1
    assert _parse_confidence("CONFIDENCE: 11") == 10


def test_parse_confidence_defaults_to_five_when_missing():
    assert _parse_confidence("no score here") == 5


def test_parse_arguments_extracts_numbered_lines():
    raw = "ARGUMENTS:\n1. First point\n2. Second point\n3. Third point"
    arguments = _parse_arguments(raw)
    assert len(arguments) == 3
    assert arguments[0] == "First point"
    assert arguments[2] == "Third point"


def test_parse_arguments_returns_empty_list_when_none_found():
    assert _parse_arguments("no numbered lines here") == []


def test_parse_position_extracts_position_line():
    raw = "POSITION: This idea has strong potential.\nother stuff"
    assert _parse_position(raw) == "This idea has strong potential."


def test_parse_position_returns_empty_when_missing():
    assert _parse_position("no position line") == ""


# --- Anonymization tests ---

def test_build_reaction_context_excludes_current_role():
    responses = [
        RoleResponse("optimist", "anthropic", "claude", "pos1", ["arg1"], 7, "raw1"),
        RoleResponse("critic", "ollama", "qwen", "pos2", ["arg2"], 8, "raw2"),
        RoleResponse("devils_advocate", "ollama", "qwen2", "pos3", ["arg3"], 6, "raw3"),
    ]
    context = _build_reaction_context(responses, current_role="optimist")
    assert "raw1" not in context
    assert "raw2" in context
    assert "raw3" in context


def test_build_reaction_context_anonymizes_provider_names():
    responses = [
        RoleResponse("optimist", "anthropic", "claude-sonnet-4-6", "pos1", [], 7, "raw1"),
        RoleResponse("critic", "ollama", "qwen3.5:35b", "pos2", [], 8, "raw2"),
    ]
    context = _build_reaction_context(responses, current_role="optimist")
    assert "anthropic" not in context
    assert "claude-sonnet-4-6" not in context
    assert "ollama" not in context
    assert "qwen3.5:35b" not in context


def test_build_reaction_context_uses_debater_labels():
    responses = [
        RoleResponse("optimist", "anthropic", "claude", "pos1", [], 7, "raw1"),
        RoleResponse("critic", "ollama", "qwen", "pos2", [], 8, "raw2"),
        RoleResponse("devils_advocate", "ollama", "qwen2", "pos3", [], 6, "raw3"),
    ]
    context = _build_reaction_context(responses, current_role="optimist")
    assert "Debater A" in context
    assert "Debater B" in context


# --- run_round integration tests ---

def test_run_round_returns_debate_round_with_responses():
    debaters = {
        "optimist": MockAdapter("anthropic", "claude", SAMPLE_DEBATER_RESPONSE),
        "critic": MockAdapter("ollama", "qwen", SAMPLE_CRITIC_RESPONSE),
    }
    fallback = MockAdapter("anthropic", "claude-haiku", SAMPLE_DEBATER_RESPONSE)
    provider_events = []

    result = run_round(
        round_number=1,
        assignment=debaters,
        seed_idea="A credit score API for gig workers.",
        fallback=fallback,
        max_tokens=512,
        provider_events=provider_events,
        previous_responses=None,
    )

    assert result.round_number == 1
    assert result.type == "independent"
    assert len(result.responses) == 2


def test_run_round_parses_position_and_arguments():
    debaters = {
        "optimist": MockAdapter("anthropic", "claude", SAMPLE_DEBATER_RESPONSE),
        "critic": MockAdapter("ollama", "qwen", SAMPLE_CRITIC_RESPONSE),
    }
    fallback = MockAdapter("anthropic", "claude-haiku", SAMPLE_DEBATER_RESPONSE)
    provider_events = []

    result = run_round(
        round_number=1,
        assignment=debaters,
        seed_idea="A credit score API for gig workers.",
        fallback=fallback,
        max_tokens=512,
        provider_events=provider_events,
    )

    optimist = next(r for r in result.responses if r.role == "optimist")
    assert optimist.position != ""
    assert len(optimist.arguments) > 0
    assert optimist.confidence == 7


def test_run_round_type_is_reaction_on_subsequent_rounds():
    previous = [
        RoleResponse("optimist", "anthropic", "claude", "pos", ["arg"], 7, SAMPLE_DEBATER_RESPONSE),
        RoleResponse("critic", "ollama", "qwen", "pos", ["arg"], 8, SAMPLE_CRITIC_RESPONSE),
    ]
    debaters = {
        "optimist": MockAdapter("anthropic", "claude", SAMPLE_DEBATER_RESPONSE),
        "critic": MockAdapter("ollama", "qwen", SAMPLE_CRITIC_RESPONSE),
    }
    fallback = MockAdapter("anthropic", "claude-haiku", SAMPLE_DEBATER_RESPONSE)

    result = run_round(
        round_number=2,
        assignment=debaters,
        seed_idea="A credit score API for gig workers.",
        fallback=fallback,
        max_tokens=512,
        provider_events=[],
        previous_responses=previous,
    )

    assert result.type == "reaction"


def test_run_round_uses_fallback_when_primary_fails():
    class FailingAdapter(ProviderAdapter):
        def __init__(self):
            super().__init__("failing", "model")

        def call(self, system, user, max_tokens=2048):
            raise ConnectionError("simulated failure")

    debaters = {
        "optimist": FailingAdapter(),
        "critic": MockAdapter("ollama", "qwen", SAMPLE_CRITIC_RESPONSE),
    }
    fallback = MockAdapter("anthropic", "claude-haiku", SAMPLE_DEBATER_RESPONSE)
    provider_events = []

    result = run_round(
        round_number=1,
        assignment=debaters,
        seed_idea="test idea",
        fallback=fallback,
        max_tokens=512,
        provider_events=provider_events,
    )

    assert any("fallback" in event for event in provider_events)
