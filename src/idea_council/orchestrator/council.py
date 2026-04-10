import json
import uuid
import os
from datetime import datetime, UTC

from idea_council.config.settings import load_settings
from idea_council.models.session import FinalReport
from idea_council.providers.registry import build_debaters, build_fallback, build_synthesizer
from idea_council.orchestrator.rotation import assign_roles, describe_assignments
from idea_council.orchestrator.seed import generate_seeds
from idea_council.orchestrator.debate import run_round
from idea_council.orchestrator.market import run_market_verification
from idea_council.orchestrator.synthesizer import (
    check_exit,
    generate_pivot_prompt,
    produce_final_report,
)


def _default_ask_user(score: int, competitor_hits: list[str], seed_idea: str = "") -> str:
    """
    Prompts the user to choose what to do when market_openness is 4-6.
    Returns "proceed", "reframe", or "abandon".
    """
    if seed_idea:
        print(f"\nIdea being evaluated:\n{seed_idea}")
    print(f"\nMarket openness: {score}/10 — moderate competition found.")
    print("\nTop hits:")
    for url in competitor_hits[:5]:
        print(f"  - {url}")
    print("\nHow would you like to proceed?")
    print("  [1] Proceed  — synthesize this idea as-is")
    print("  [2] Reframe  — council finds the gap in the market")
    print("  [3] Abandon  — exit session")

    while True:
        choice = input("\nEnter choice (1/2/3): ").strip()
        if choice == "1":
            return "proceed"
        elif choice == "2":
            return "reframe"
        elif choice == "3":
            return "abandon"
        else:
            print("Please enter 1, 2, or 3.")


def _save_report(report: FinalReport, output_dir: str, domain: str) -> str:
    """Saves the final report as JSON and returns the file path."""
    os.makedirs(output_dir, exist_ok=True)

    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    slug = domain.lower().replace(" ", "_")[:40]
    filename = f"{timestamp}_{slug}.json"
    filepath = os.path.join(output_dir, filename)

    report_dict = {
        "session_id": report.session_id,
        "domain": report.domain,
        "seed_idea": report.seed_idea,
        "seed_mode": report.seed_mode,
        "exclusions": report.exclusions,
        "user_context": report.user_context,
        "role_assignments": report.role_assignments,
        "rejected_seeds": report.rejected_seeds,
        "rounds_completed": report.rounds_completed,
        "exit_reason": report.exit_reason,
        "pivot_triggered": report.pivot_triggered,
        "pivot_seed": report.pivot_seed,
        "user_choice": report.user_choice,
        "verdict": report.verdict,
        "opportunity_score": report.opportunity_score,
        "strongest_argument": report.strongest_argument,
        "fatal_flaw": report.fatal_flaw,
        "kill_conditions": report.kill_conditions,
        "what_must_be_true": report.what_must_be_true,
        "market": {
            "search_queries": report.market.search_queries,
            "github_hits": report.market.github_hits,
            "web_hits": report.market.web_hits,
            "competitor_hits": report.market.competitor_hits,
            "market_openness": report.market.market_openness,
            "remaining_gap": report.market.remaining_gap,
            "skipped": report.market.skipped,
        } if report.market else None,
        "provider_events": report.provider_events,
        "rounds": [
            {
                "round_number": r.round_number,
                "type": r.type,
                "synthesizer_signal": r.synthesizer_signal,
                "responses": [
                    {
                        "role": resp.role,
                        "provider": resp.provider,
                        "model": resp.model,
                        "position": resp.position,
                        "arguments": resp.arguments,
                        "confidence": resp.confidence,
                    }
                    for resp in r.responses
                ],
            }
            for r in report.rounds
        ],
    }

    with open(filepath, "w") as f:
        json.dump(report_dict, f, indent=2)

    return filepath


def run_session(
    domain: str,
    seed: str = None,
    exclusions: list[str] = None,
    user_context: str = None,
    max_rounds: int = 3,
    verbose: bool = False,
    ask_user_fn=None,
    on_progress=None,
    on_roles_assigned=None,
    on_reframe_started=None,
    on_debater_start=None,
    on_debater_done=None,
    on_seed_ready=None,
) -> tuple[FinalReport, str]:
    """
    Runs a full idea-council session.

    Returns the FinalReport and the path to the saved JSON file.

    ask_user_fn is called when market_openness is 4-6 and receives
    (score, competitor_hits, seed_idea). It should return "proceed", "reframe", or "abandon".
    Defaults to an interactive terminal prompt.

    on_progress is called with a status string at each phase boundary.
    The CLI uses this to drive a live spinner display.
    Defaults to a no-op so tests stay silent.
    """
    if ask_user_fn is None:
        ask_user_fn = _default_ask_user

    def _noop_one(*args):
        pass

    def _noop_role(*args):
        pass

    if on_progress is None:
        on_progress = _noop_one
    if on_roles_assigned is None:
        on_roles_assigned = _noop_one
    if on_reframe_started is None:
        on_reframe_started = _noop_one
    if on_debater_start is None:
        on_debater_start = _noop_role
    if on_debater_done is None:
        on_debater_done = _noop_role
    if on_seed_ready is None:
        def on_seed_ready(s):
            return s

    if exclusions is None:
        exclusions = []

    settings = load_settings()
    provider_events = []

    # Step 1: Build providers and assign roles
    on_progress("Checking available providers...")
    debaters = build_debaters(settings)
    synthesizer = build_synthesizer(settings)
    fallback = build_fallback(settings)

    if len(debaters) < 2:
        raise RuntimeError(
            f"At least 2 debaters are required. Only {len(debaters)} available. "
            "Check your provider configuration."
        )

    assignment = assign_roles(debaters)
    role_assignments = describe_assignments(assignment)
    role_assignments["synthesizer"] = {"provider": synthesizer.provider, "model": synthesizer.model}
    on_roles_assigned(role_assignments)

    # Step 2: Seed
    if seed:
        chosen_seed = seed
        rejected_seeds = []
        seed_mode = "user_provided"
        on_progress("Using provided seed idea...")
    else:
        on_progress(f"Generating seed ideas from {len(debaters)} providers...")
        chosen_seed, rejected_seeds = generate_seeds(
            debaters=debaters,
            synthesizer=synthesizer,
            domain=domain,
            exclusions=exclusions,
            max_tokens=settings.max_tokens_per_call,
        )
        seed_mode = "generated"
        on_progress("Seed idea ready. Waiting for confirmation...")
        confirmed_seed = on_seed_ready(chosen_seed)
        if confirmed_seed != chosen_seed:
            chosen_seed = confirmed_seed
            seed_mode = "user_provided"
        on_progress("Seed confirmed. Starting debate...")

    # Step 3: Debate rounds
    rounds = []
    exit_reason = "max_rounds_reached"
    previous_responses = None

    for round_number in range(1, max_rounds + 1):
        round_type = "independent analysis" if round_number == 1 else "reaction"
        on_progress(f"Round {round_number} — {round_type} ({len(assignment)} debaters)...")

        debate_round = run_round(
            round_number=round_number,
            assignment=assignment,
            seed_idea=chosen_seed,
            fallback=fallback,
            max_tokens=settings.max_tokens_per_call,
            provider_events=provider_events,
            previous_responses=previous_responses,
            on_debater_start=on_debater_start,
            on_debater_done=on_debater_done,
            user_context=user_context,
            exclusions=exclusions,
        )

        # Check exit condition only after reaction rounds (not after round 1)
        # and only if there are more rounds allowed. Round 1 is independent
        # analysis — nobody has reacted yet, so "done" would always be premature.
        if round_number > 1 and round_number < max_rounds:
            on_progress(f"Round {round_number} complete. Checking if debate should continue...")
            signal = check_exit(
                rounds=rounds + [debate_round],
                synthesizer=synthesizer,
                max_tokens=settings.max_tokens_per_call,
            )
            debate_round.synthesizer_signal = signal
            on_progress(f"Round {round_number} complete. Synthesizer: {signal}")
        elif round_number == 1:
            debate_round.synthesizer_signal = "not_checked"
            on_progress(f"Round {round_number} complete. Moving to reaction round...")
        else:
            debate_round.synthesizer_signal = "not_checked"
            on_progress(f"Round {round_number} complete. Max rounds reached.")

        rounds.append(debate_round)
        previous_responses = debate_round.responses

        if debate_round.synthesizer_signal == "done":
            exit_reason = "synthesizer_done"
            break

    # Step 4: Market verification
    on_progress("Running market verification...")
    market = run_market_verification(
        seed_idea=chosen_seed,
        synthesizer=synthesizer,
        github_enabled=settings.github_search_enabled,
        github_max_results=settings.github_search_max_results,
        tavily_api_key=settings.tavily_api_key,
        max_tokens=settings.max_tokens_per_call,
    )

    if market.skipped:
        on_progress("Market verification skipped (no search sources configured).")
    else:
        on_progress(f"Market verification complete. Market openness: {market.market_openness}/10")

    # Step 5: Act on market_openness
    user_choice = None
    pivot_triggered = False
    pivot_seed = None

    if market and not market.skipped and market.market_openness is not None:
        score = market.market_openness

        if score <= 3:
            # Auto-reframe: market is crowded, council finds the gap
            pivot_triggered = True
            on_reframe_started(role_assignments)
            pivot_prompt = generate_pivot_prompt(
                seed_idea=chosen_seed,
                competitor_hits=market.competitor_hits,
                synthesizer=synthesizer,
                max_tokens=settings.max_tokens_per_call,
            )
            pivot_round = run_round(
                round_number=len(rounds) + 1,
                assignment=assignment,
                seed_idea=pivot_prompt,
                fallback=fallback,
                max_tokens=settings.max_tokens_per_call,
                provider_events=provider_events,
                previous_responses=previous_responses,
                on_debater_start=on_debater_start,
                on_debater_done=on_debater_done,
                user_context=user_context,
                exclusions=exclusions,
            )
            pivot_round.synthesizer_signal = "not_checked"
            rounds.append(pivot_round)
            pivot_seed = pivot_prompt

        elif score <= 6:
            # Ask user what to do — moderate competition
            user_choice = ask_user_fn(score, market.competitor_hits, chosen_seed)

            if user_choice == "abandon":
                # Save a partial report and exit
                partial_report = FinalReport(
                    session_id=str(uuid.uuid4()),
                    domain=domain,
                    seed_idea=chosen_seed,
                    seed_mode=seed_mode,
                    exclusions=exclusions or None,
                    user_context=user_context,
                    role_assignments=role_assignments,
                    rejected_seeds=rejected_seeds,
                    rounds=rounds,
                    rounds_completed=len(rounds),
                    exit_reason=exit_reason,
                    verdict="abandon",
                    opportunity_score=0,
                    strongest_argument="",
                    fatal_flaw="",
                    kill_conditions=[],
                    what_must_be_true=[],
                    market=market,
                    pivot_triggered=False,
                    pivot_seed=None,
                    user_choice="abandon",
                    provider_events=provider_events,
                )
                filepath = _save_report(partial_report, settings.output_dir, domain)
                return partial_report, filepath

            elif user_choice == "reframe":
                pivot_triggered = True
                on_reframe_started(role_assignments)
                pivot_prompt = generate_pivot_prompt(
                    seed_idea=chosen_seed,
                    competitor_hits=market.competitor_hits,
                    synthesizer=synthesizer,
                    max_tokens=settings.max_tokens_per_call,
                )
                pivot_round = run_round(
                    round_number=len(rounds) + 1,
                    assignment=assignment,
                    seed_idea=pivot_prompt,
                    fallback=fallback,
                    max_tokens=settings.max_tokens_per_call,
                    provider_events=provider_events,
                    previous_responses=previous_responses,
                    on_debater_start=on_debater_start,
                    on_debater_done=on_debater_done,
                    user_context=user_context,
                    exclusions=exclusions,
                )
                pivot_round.synthesizer_signal = "not_checked"
                rounds.append(pivot_round)
                pivot_seed = pivot_prompt

    # Step 6: Final synthesis
    on_progress("Producing final report...")
    synthesis = produce_final_report(
        seed_idea=pivot_seed or chosen_seed,
        rounds=rounds,
        role_assignments=role_assignments,
        market=market,
        synthesizer=synthesizer,
        max_tokens=settings.max_tokens_per_call,
    )

    report = FinalReport(
        session_id=str(uuid.uuid4()),
        domain=domain,
        seed_idea=chosen_seed,
        seed_mode=seed_mode,
        exclusions=exclusions or None,
        user_context=user_context,
        role_assignments=role_assignments,
        rejected_seeds=rejected_seeds,
        rounds=rounds,
        rounds_completed=len(rounds),
        exit_reason=exit_reason,
        verdict=synthesis["verdict"],
        opportunity_score=synthesis["opportunity_score"],
        strongest_argument=synthesis["strongest_argument"],
        fatal_flaw=synthesis["fatal_flaw"],
        kill_conditions=synthesis["kill_conditions"],
        what_must_be_true=synthesis["what_must_be_true"],
        market=market,
        pivot_triggered=pivot_triggered,
        pivot_seed=pivot_seed,
        user_choice=user_choice,
        provider_events=provider_events,
    )

    filepath = _save_report(report, settings.output_dir, domain)
    return report, filepath
