from tests.conftest import MockAdapter, SAMPLE_FINAL_SYNTHESIS, SAMPLE_EXIT_DONE, SAMPLE_EXIT_CONTINUE
from idea_council.models.session import DebateRound, RoleResponse, MarketVerification
from idea_council.orchestrator.synthesizer import (
    check_exit,
    produce_final_report,
    _parse_field,
    _parse_list_section,
    _parse_score,
)


def make_round(round_number: int, signal: str = "continue") -> DebateRound:
    responses = [
        RoleResponse("optimist", "anthropic", "claude", "Strong potential", ["arg1", "arg2"], 7, "raw optimist"),
        RoleResponse("critic", "ollama", "qwen", "Key assumption is wrong", ["arg1", "arg2"], 8, "raw critic"),
    ]
    return DebateRound(
        round_number=round_number,
        type="independent" if round_number == 1 else "reaction",
        responses=responses,
        synthesizer_signal=signal,
    )


# --- Parser unit tests ---

def test_parse_field_extracts_verdict():
    result = _parse_field(SAMPLE_FINAL_SYNTHESIS, "VERDICT")
    assert result == "pivot"


def test_parse_score_extracts_opportunity_score():
    result = _parse_score(SAMPLE_FINAL_SYNTHESIS, "OPPORTUNITY_SCORE")
    assert result == 6


def test_parse_list_section_extracts_kill_conditions():
    result = _parse_list_section(SAMPLE_FINAL_SYNTHESIS, "KILL_CONDITIONS")
    assert len(result) == 2
    assert "Gig platforms refuse data sharing agreements" in result


def test_parse_list_section_extracts_what_must_be_true():
    result = _parse_list_section(SAMPLE_FINAL_SYNTHESIS, "WHAT_MUST_BE_TRUE")
    assert len(result) == 2
    assert any("data partnership" in item for item in result)


# --- check_exit tests ---

def test_check_exit_returns_done_when_synthesizer_says_done():
    synthesizer = MockAdapter("anthropic", "claude", SAMPLE_EXIT_DONE)
    rounds = [make_round(1)]
    signal = check_exit(rounds, synthesizer, max_tokens=64)
    assert signal == "done"


def test_check_exit_returns_continue_when_synthesizer_says_continue():
    synthesizer = MockAdapter("anthropic", "claude", SAMPLE_EXIT_CONTINUE)
    rounds = [make_round(1)]
    signal = check_exit(rounds, synthesizer, max_tokens=64)
    assert signal == "continue"


def test_check_exit_defaults_to_continue_on_unexpected_response():
    synthesizer = MockAdapter("anthropic", "claude", "maybe")
    rounds = [make_round(1)]
    signal = check_exit(rounds, synthesizer, max_tokens=64)
    assert signal == "continue"


# --- produce_final_report tests ---

def test_produce_final_report_returns_parsed_fields():
    synthesizer = MockAdapter("anthropic", "claude", SAMPLE_FINAL_SYNTHESIS)
    rounds = [make_round(1)]
    market = MarketVerification(
        search_queries=[],
        github_hits=[],
        web_hits=[],
        competitor_hits=[],
        market_openness=None,
        remaining_gap=None,
        skipped=True,
    )

    result = produce_final_report(
        seed_idea="A credit score API for gig workers.",
        rounds=rounds,
        role_assignments={"optimist": {"provider": "anthropic", "model": "claude"}},
        market=market,
        synthesizer=synthesizer,
        max_tokens=512,
    )

    assert result["verdict"] == "pivot"
    assert result["opportunity_score"] == 6
    assert result["strongest_argument"] != ""
    assert result["fatal_flaw"] != ""
    assert len(result["kill_conditions"]) == 2
    assert len(result["what_must_be_true"]) == 2


def test_produce_final_report_calls_synthesizer_once():
    synthesizer = MockAdapter("anthropic", "claude", SAMPLE_FINAL_SYNTHESIS)
    rounds = [make_round(1)]
    market = MarketVerification([], [], [], [], None, None, True)

    produce_final_report(
        seed_idea="test idea",
        rounds=rounds,
        role_assignments={},
        market=market,
        synthesizer=synthesizer,
        max_tokens=512,
    )

    assert synthesizer.call_count == 1
