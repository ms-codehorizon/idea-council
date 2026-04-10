import pytest
from unittest.mock import patch, MagicMock
from tests.conftest import (
    MockAdapter,
    SAMPLE_DEBATER_RESPONSE,
    SAMPLE_CRITIC_RESPONSE,
    SAMPLE_EXIT_DONE,
    SAMPLE_FINAL_SYNTHESIS,
    SAMPLE_MARKET_INTERPRETATION,
)
from idea_council.orchestrator.council import run_session
from idea_council.models.session import MarketVerification


MOCK_SETTINGS_VALUES = {
    "anthropic_api_key": "test-key",
    "anthropic_model": "claude-sonnet-4-6",
    "anthropic_fallback_model": "claude-haiku-4-5",
    "ollama_base_url": "http://localhost:11434",
    "ollama_models": [],
    "openai_api_key": "",
    "openai_model": "gpt-4o",
    "google_api_key": "",
    "google_model": "gemini-2.0-flash",
    "github_search_enabled": False,
    "github_search_max_results": 5,
    "tavily_api_key": "",
    "max_tokens_per_call": 512,
    "output_dir": "/tmp/idea-council-test-output",
    "log_level": "INFO",
}


def make_mock_settings():
    settings = MagicMock()
    for key, value in MOCK_SETTINGS_VALUES.items():
        setattr(settings, key, value)
    return settings


def make_debater_pool():
    """Returns two debaters with realistic canned responses."""
    return [
        MockAdapter("anthropic", "claude-sonnet-4-6", SAMPLE_DEBATER_RESPONSE),
        MockAdapter("ollama", "qwen3.5:35b", SAMPLE_CRITIC_RESPONSE),
    ]


def make_synthesizer(response: str = None):
    """Synthesizer that returns done on exit check and final synthesis on report."""
    if response:
        return MockAdapter("anthropic", "claude-sonnet-4-6", response)

    call_counter = {"count": 0}

    class SmartSynthesizer(MockAdapter):
        def call(self, system, user, max_tokens=2048):
            call_counter["count"] += 1
            # First call is seed selection, second is exit check, last is final report
            if "continue" in system.lower() or "done" in system.lower() or max_tokens == 64:
                return SAMPLE_EXIT_DONE
            if "VERDICT" in SAMPLE_FINAL_SYNTHESIS and "synthesis" in system.lower():
                return SAMPLE_FINAL_SYNTHESIS
            return SAMPLE_DEBATER_RESPONSE

    return SmartSynthesizer("anthropic", "claude-sonnet-4-6", SAMPLE_FINAL_SYNTHESIS)


def make_skipped_market():
    return MarketVerification(
        search_queries=[],
        github_hits=[],
        web_hits=[],
        competitor_hits=[],
        market_openness=None,
        remaining_gap=None,
        skipped=True,
    )


@patch("idea_council.orchestrator.council.run_market_verification")
@patch("idea_council.orchestrator.council.build_fallback")
@patch("idea_council.orchestrator.council.build_synthesizer")
@patch("idea_council.orchestrator.council.build_debaters")
@patch("idea_council.orchestrator.council.load_settings")
def test_run_session_mode_b_skips_seed_phase(
    mock_load_settings,
    mock_build_debaters,
    mock_build_synthesizer,
    mock_build_fallback,
    mock_run_market,
):
    mock_load_settings.return_value = make_mock_settings()
    mock_build_debaters.return_value = make_debater_pool()
    mock_build_synthesizer.return_value = MockAdapter("anthropic", "claude", SAMPLE_FINAL_SYNTHESIS)
    mock_build_fallback.return_value = MockAdapter("anthropic", "claude-haiku", SAMPLE_DEBATER_RESPONSE)
    mock_run_market.return_value = make_skipped_market()

    report, filepath = run_session(
        domain="fintech",
        seed="A credit score API for gig workers.",
        max_rounds=1,
    )

    assert report.seed_mode == "user_provided"
    assert report.seed_idea == "A credit score API for gig workers."
    assert report.rejected_seeds == []


@patch("idea_council.orchestrator.council.run_market_verification")
@patch("idea_council.orchestrator.council.build_fallback")
@patch("idea_council.orchestrator.council.build_synthesizer")
@patch("idea_council.orchestrator.council.build_debaters")
@patch("idea_council.orchestrator.council.load_settings")
def test_run_session_mode_a_generates_seed(
    mock_load_settings,
    mock_build_debaters,
    mock_build_synthesizer,
    mock_build_fallback,
    mock_run_market,
):
    mock_load_settings.return_value = make_mock_settings()
    mock_build_debaters.return_value = make_debater_pool()
    mock_build_synthesizer.return_value = MockAdapter("anthropic", "claude", SAMPLE_FINAL_SYNTHESIS)
    mock_build_fallback.return_value = MockAdapter("anthropic", "claude-haiku", SAMPLE_DEBATER_RESPONSE)
    mock_run_market.return_value = make_skipped_market()

    report, filepath = run_session(
        domain="fintech",
        max_rounds=1,
    )

    assert report.seed_mode == "generated"
    assert report.seed_idea != ""


@patch("idea_council.orchestrator.council.run_market_verification")
@patch("idea_council.orchestrator.council.build_fallback")
@patch("idea_council.orchestrator.council.build_synthesizer")
@patch("idea_council.orchestrator.council.build_debaters")
@patch("idea_council.orchestrator.council.load_settings")
def test_run_session_user_choice_abandon_exits_early(
    mock_load_settings,
    mock_build_debaters,
    mock_build_synthesizer,
    mock_build_fallback,
    mock_run_market,
):
    mock_load_settings.return_value = make_mock_settings()
    mock_build_debaters.return_value = make_debater_pool()
    mock_build_synthesizer.return_value = MockAdapter("anthropic", "claude", SAMPLE_FINAL_SYNTHESIS)
    mock_build_fallback.return_value = MockAdapter("anthropic", "claude-haiku", SAMPLE_DEBATER_RESPONSE)
    mock_run_market.return_value = MarketVerification(
        search_queries=["query"],
        github_hits=["https://github.com/example/repo"],
        web_hits=[],
        competitor_hits=["https://github.com/example/repo"],
        market_openness=5,
        remaining_gap=None,
        skipped=False,
    )

    report, filepath = run_session(
        domain="fintech",
        seed="test idea",
        max_rounds=1,
        ask_user_fn=lambda score, hits, seed: "abandon",
    )

    assert report.verdict == "abandon"
    assert report.user_choice == "abandon"


@patch("idea_council.orchestrator.council.run_market_verification")
@patch("idea_council.orchestrator.council.build_fallback")
@patch("idea_council.orchestrator.council.build_synthesizer")
@patch("idea_council.orchestrator.council.build_debaters")
@patch("idea_council.orchestrator.council.load_settings")
def test_run_session_high_score_triggers_auto_pivot(
    mock_load_settings,
    mock_build_debaters,
    mock_build_synthesizer,
    mock_build_fallback,
    mock_run_market,
):
    mock_load_settings.return_value = make_mock_settings()
    mock_build_debaters.return_value = make_debater_pool()
    mock_build_synthesizer.return_value = MockAdapter("anthropic", "claude", SAMPLE_FINAL_SYNTHESIS)
    mock_build_fallback.return_value = MockAdapter("anthropic", "claude-haiku", SAMPLE_DEBATER_RESPONSE)
    mock_run_market.return_value = MarketVerification(
        search_queries=["query"],
        github_hits=["https://github.com/example/repo"],
        web_hits=[],
        competitor_hits=["https://github.com/example/repo"],
        market_openness=2,
        remaining_gap=None,
        skipped=False,
    )

    report, filepath = run_session(
        domain="fintech",
        seed="test idea",
        max_rounds=1,
    )

    assert report.pivot_triggered is True
    assert report.pivot_seed is not None


@patch("idea_council.orchestrator.council.run_market_verification")
@patch("idea_council.orchestrator.council.build_fallback")
@patch("idea_council.orchestrator.council.build_synthesizer")
@patch("idea_council.orchestrator.council.build_debaters")
@patch("idea_council.orchestrator.council.load_settings")
def test_run_session_saves_report_to_disk(
    mock_load_settings,
    mock_build_debaters,
    mock_build_synthesizer,
    mock_build_fallback,
    mock_run_market,
    tmp_path,
):
    settings = make_mock_settings()
    settings.output_dir = str(tmp_path)

    mock_load_settings.return_value = settings
    mock_build_debaters.return_value = make_debater_pool()
    mock_build_synthesizer.return_value = MockAdapter("anthropic", "claude", SAMPLE_FINAL_SYNTHESIS)
    mock_build_fallback.return_value = MockAdapter("anthropic", "claude-haiku", SAMPLE_DEBATER_RESPONSE)
    mock_run_market.return_value = make_skipped_market()

    report, filepath = run_session(
        domain="fintech",
        seed="test idea",
        max_rounds=1,
    )

    import os
    assert os.path.exists(filepath)
    assert filepath.endswith(".json")


@patch("idea_council.orchestrator.council.load_settings")
@patch("idea_council.orchestrator.council.build_debaters")
def test_run_session_raises_if_fewer_than_two_debaters(
    mock_build_debaters,
    mock_load_settings,
):
    mock_load_settings.return_value = make_mock_settings()
    mock_build_debaters.return_value = [
        MockAdapter("anthropic", "claude", SAMPLE_DEBATER_RESPONSE)
    ]

    with pytest.raises(RuntimeError, match="At least 2 debaters"):
        run_session(domain="fintech", seed="test idea", max_rounds=1)
