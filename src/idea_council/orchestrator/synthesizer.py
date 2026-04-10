
from idea_council.models.session import DebateRound, FinalReport, MarketVerification
from idea_council.orchestrator.debate import _strip_thinking_tags
from idea_council.providers.adapter import ProviderAdapter
from idea_council.roles.prompts import (
    FINAL_SYNTHESIS,
    SYNTHESIZER_EXIT_CHECK,
    SYNTHESIZER_PIVOT,
    SYNTHESIZER_PROPOSAL,
)


def check_exit(
    rounds: list[DebateRound],
    synthesizer: ProviderAdapter,
    max_tokens: int,
) -> str:
    """
    Ask the synthesizer whether the debate has reached diminishing returns.
    Returns "continue" or "done".
    """
    all_responses = []
    for debate_round in rounds:
        all_responses.append(f"--- Round {debate_round.round_number} ({debate_round.type}) ---")
        for response in debate_round.responses:
            all_responses.append(f"{response.role.upper()}:\n{response.raw}")

    user = "\n\n".join(all_responses)

    raw = _strip_thinking_tags(synthesizer.call(
        system=SYNTHESIZER_EXIT_CHECK,
        user=user,
        max_tokens=64,
    ))

    signal = raw.strip().lower().split()[0] if raw.strip() else "continue"

    if signal not in ("continue", "done"):
        signal = "continue"

    return signal


def generate_pivot_prompt(
    seed_idea: str,
    competitor_hits: list[str],
    synthesizer: ProviderAdapter,
    max_tokens: int,
) -> str:
    """
    Ask the synthesizer to frame a pivot question for the council based on
    what competitors already exist.
    """
    competitor_list = "\n".join(f"- {url}" for url in competitor_hits)
    user = (
        f"Original idea:\n\n{seed_idea}\n\n"
        f"Existing competitors or similar projects:\n{competitor_list}"
    )

    return synthesizer.call(
        system=SYNTHESIZER_PIVOT,
        user=user,
        max_tokens=max_tokens,
    )


def _parse_list_section(raw: str, section_name: str) -> list[str]:
    """Extract a bullet list from a named section in the synthesizer response."""
    items = []
    in_section = False

    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith(f"{section_name}:"):
            in_section = True
            continue
        if in_section:
            if stripped.startswith("-"):
                item = stripped.lstrip("- ").strip()
                if item:
                    items.append(item)
            elif stripped and not stripped.startswith("-"):
                # Hit the next section
                break

    return items


def _parse_field(raw: str, field_name: str) -> str:
    """Extract a single-line field from the synthesizer response."""
    for line in raw.splitlines():
        if line.strip().startswith(f"{field_name}:"):
            return line.strip().replace(f"{field_name}:", "").strip()
    return ""


def _parse_score(raw: str, field_name: str) -> int:
    """Extract a numeric score field from the synthesizer response."""
    value = _parse_field(raw, field_name)
    try:
        score = int(value)
        return max(1, min(10, score))
    except ValueError:
        return 5


def produce_final_report(
    seed_idea: str,
    rounds: list[DebateRound],
    role_assignments: dict,
    market: MarketVerification,
    synthesizer: ProviderAdapter,
    max_tokens: int,
) -> dict:
    """
    Ask the synthesizer to produce the final structured verdict.
    Returns a dict of parsed fields to be merged into FinalReport.
    """
    rounds_text = []
    for debate_round in rounds:
        rounds_text.append(f"=== Round {debate_round.round_number} ({debate_round.type}) ===")
        for response in debate_round.responses:
            rounds_text.append(f"{response.role.upper()} ({response.provider}/{response.model}):\n{response.raw}")

    market_section = ""
    if market and not market.skipped and market.competitor_hits:
        competitor_list = "\n".join(f"- {url}" for url in market.competitor_hits)
        market_section = (
            f"\nMarket research (market_openness: {market.market_openness}/10):\n"
            f"{competitor_list}"
        )

    user = (
        f"Idea being evaluated:\n\n{seed_idea}\n\n"
        f"{''.join(rounds_text)}"
        f"{market_section}"
    )

    raw = _strip_thinking_tags(synthesizer.call(
        system=FINAL_SYNTHESIS,
        user=user,
        max_tokens=max_tokens,
    ))

    return {
        "verdict": _parse_field(raw, "VERDICT") or "refine",
        "opportunity_score": _parse_score(raw, "OPPORTUNITY_SCORE"),
        "strongest_argument": _parse_field(raw, "STRONGEST_ARGUMENT"),
        "fatal_flaw": _parse_field(raw, "FATAL_FLAW"),
        "kill_conditions": _parse_list_section(raw, "KILL_CONDITIONS"),
        "what_must_be_true": _parse_list_section(raw, "WHAT_MUST_BE_TRUE"),
        "raw": raw,
    }


def generate_proposal(
    report: FinalReport,
    synthesizer: ProviderAdapter,
    max_tokens: int,
) -> str:
    """
    Ask the synthesizer to produce a project scope and proposal document
    based on the completed session. Returns the proposal as a Markdown string.
    """
    idea = report.pivot_seed if report.pivot_seed else report.seed_idea

    kill_conditions_text = "\n".join(f"- {c}" for c in report.kill_conditions)
    what_must_be_true_text = "\n".join(f"- {c}" for c in report.what_must_be_true)

    market_section = ""
    if report.market and not report.market.skipped:
        market_section = (
            f"Market openness: {report.market.market_openness}/10\n"
            f"Remaining gap: {report.market.remaining_gap or 'none identified'}\n"
            f"Competitor URLs found:\n" +
            "\n".join(f"- {url}" for url in report.market.competitor_hits[:10])
        )

    rounds_text = []
    for debate_round in report.rounds:
        rounds_text.append(f"=== Round {debate_round.round_number} ({debate_round.type}) ===")
        for response in debate_round.responses:
            rounds_text.append(
                f"{response.role.upper()} ({response.provider}/{response.model}):\n{response.raw}"
            )

    user = (
        f"Idea: {idea}\n\n"
        f"Domain: {report.domain}\n"
        f"Verdict: {report.verdict}\n"
        f"Opportunity score: {report.opportunity_score}/10\n"
        f"Strongest argument: {report.strongest_argument}\n"
        f"Fatal flaw: {report.fatal_flaw}\n\n"
        f"Kill conditions:\n{kill_conditions_text}\n\n"
        f"What must be true:\n{what_must_be_true_text}\n\n"
        f"{market_section}\n\n"
        f"Debate rounds:\n{''.join(rounds_text)}"
    )

    return _strip_thinking_tags(synthesizer.call(
        system=SYNTHESIZER_PROPOSAL,
        user=user,
        max_tokens=max_tokens,
    ))
