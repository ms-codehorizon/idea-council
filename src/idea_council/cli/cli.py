import typer
from typing import Optional
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich import box

from idea_council.orchestrator.council import run_session
from idea_council.orchestrator.synthesizer import generate_proposal
from idea_council.config.settings import load_settings
from idea_council.providers.registry import build_synthesizer

app = typer.Typer(
    help="idea-council: multi-provider LLM debate for early product ideation"
)
console = Console()


def _print_header():
    console.print(
        Panel.fit(
            "[bold cyan]idea-council[/bold cyan]\n[dim]multi-provider LLM debate council[/dim]",
            border_style="cyan",
        )
    )


def _print_round(round_number: int, round_type: str, responses: list, verbose: bool):
    if not verbose:
        return
    console.print(f"\n[bold]Round {round_number}[/bold] [dim]({round_type})[/dim]")
    for response in responses:
        color = {
            "optimist": "green",
            "critic": "red",
            "devils_advocate": "yellow",
            "domain_expert": "blue",
        }.get(response.role, "white")

        console.print(
            Panel(
                f"[bold]{response.position}[/bold]\n\n"
                + "\n".join(f"• {arg}" for arg in response.arguments)
                + f"\n\n[dim]Confidence: {response.confidence}/10[/dim]",
                title=f"[{color}]{response.role.replace('_', ' ').title()}[/{color}] "
                f"[dim]({response.provider}/{response.model})[/dim]",
                border_style=color,
                box=box.ROUNDED,
            )
        )


def _truncate_to_lines(text: str, max_lines: int = 2, max_chars: int = 120) -> str:
    """Return at most max_lines lines of text, truncating with … if needed."""
    lines = text.strip().splitlines()
    # Strip markdown headers and blank lines for a cleaner preview
    clean = [ln for ln in lines if ln.strip() and not ln.strip().startswith("#")]
    preview = " ".join(clean[:max_lines])
    if len(preview) > max_chars:
        preview = preview[:max_chars].rstrip() + "…"
    elif len(clean) > max_lines:
        preview += "…"
    return preview


def _print_assignments(
    role_assignments: dict,
    progress,
    title: str = "Council lineup",
    reframe_seed: str = None,
):
    progress.stop()
    role_colors = {
        "optimist": "green",
        "critic": "red",
        "devils_advocate": "yellow",
        "domain_expert": "blue",
    }
    console.print(f"\n[bold]{title}:[/bold]")
    for role, info in role_assignments.items():
        if role == "synthesizer":
            continue
        color = role_colors.get(role, "white")
        label = role.replace("_", " ").title()
        console.print(
            f"  [{color}]{label:<18}[/{color}] {info['provider']}/{info['model']}"
        )
    if "synthesizer" in role_assignments:
        info = role_assignments["synthesizer"]
        console.print(f"  [dim]{'—' * 30}[/dim]")
        console.print(
            f"  [dim]{'Synthesizer (judge)':<18}[/dim] {info['provider']}/{info['model']}"
        )
    if reframe_seed:
        preview = _truncate_to_lines(reframe_seed)
        console.print(f"\n  [dim]Reframe question:[/dim] {preview}")
    console.print("")
    progress.start()


def _market_openness_label(openness: int) -> str:
    if openness >= 7:
        return "open space"
    elif openness >= 4:
        return "moderate competition"
    else:
        return "crowded"


def _opportunity_label(score: int) -> str:
    if score >= 7:
        return "strong"
    elif score >= 4:
        return "moderate"
    else:
        return "weak"


def _print_market(market):
    if not market or market.skipped:
        console.print(
            "\n[dim]Market verification: skipped (no search sources configured)[/dim]"
        )
        return

    openness = market.market_openness
    if openness is None:
        console.print("\n[dim]Market verification: no results found[/dim]")
        return

    color = "green" if openness >= 7 else "yellow" if openness >= 4 else "red"
    label = _market_openness_label(openness)
    console.print(
        f"\n[bold]Market Openness:[/bold] [{color}]{openness}/10 ({label})[/{color}]"
    )

    if market.github_hits:
        console.print(f"  [dim]GitHub ({len(market.github_hits)} repos):[/dim]")
        for url in market.github_hits[:5]:
            console.print(f"    [blue]{url}[/blue]")

    if market.web_hits:
        console.print(f"  [dim]Web ({len(market.web_hits)} results):[/dim]")
        for url in market.web_hits[:5]:
            console.print(f"    [blue]{url}[/blue]")

    if market.remaining_gap and 4 <= openness <= 6:
        console.print(
            f"\n  [bold green]Gap identified:[/bold green] {market.remaining_gap}"
        )


def _print_final_report(report):
    verdict_colors = {"pursue": "green", "refine": "yellow", "abandon": "red"}
    verdict_color = verdict_colors.get(report.verdict, "white")

    opp_label = _opportunity_label(report.opportunity_score)
    console.print(
        Panel(
            f"[bold]Idea:[/bold]\n{report.seed_idea}\n\n"
            f"[bold {verdict_color}]Verdict: {report.verdict.upper()}[/bold {verdict_color}]\n\n"
            f"[bold]Opportunity Score:[/bold] {report.opportunity_score}/10 ({opp_label})\n\n"
            f"[bold]Strongest Argument:[/bold]\n{report.strongest_argument}\n\n"
            f"[bold]Fatal Flaw:[/bold]\n{report.fatal_flaw}\n\n"
            f"[bold]Kill Conditions:[/bold]\n"
            + "\n".join(f"• {c}" for c in report.kill_conditions)
            + "\n\n[bold]What Must Be True:[/bold]\n"
            + "\n".join(f"• {c}" for c in report.what_must_be_true),
            title="[bold]Final Report[/bold]",
            border_style=verdict_color,
            box=box.DOUBLE,
        )
    )

    if report.reframe_triggered:
        console.print(
            "[yellow]Note: A reframe round was triggered due to market saturation.[/yellow]"
        )

    if report.provider_events:
        console.print("\n[dim]Provider events:[/dim]")
        for event in report.provider_events:
            console.print(f"  [dim]{event}[/dim]")


@app.command()
def main(
    domain: str = typer.Option(
        ..., "--domain", help="Domain or theme for ideation (e.g. 'developer tools')"
    ),
    seed: Optional[str] = typer.Option(
        None, "--seed", help="Optional seed idea to debate instead of generating one"
    ),
    exclude: Optional[str] = typer.Option(
        None, "--exclude", help="Comma-separated list of existing projects to exclude"
    ),
    context: Optional[str] = typer.Option(
        None, "--context", help="Personal background to guide idea generation"
    ),
    rounds: int = typer.Option(
        3, "--rounds", help="Maximum number of debate rounds (default: 3)"
    ),
    verbose: bool = typer.Option(
        False, "--verbose", help="Show all round responses before the final report"
    ),
):
    _print_header()

    exclusions = []
    if exclude:
        exclusions = [e.strip() for e in exclude.split(",") if e.strip()]

    console.print(f"\n[bold]Domain:[/bold] {domain}")
    if exclusions:
        console.print(f"[bold]Excluding:[/bold] {', '.join(exclusions)}")
    if context:
        console.print(f"[bold]Context:[/bold] {context}")

    if not seed:
        console.print("\n[bold]How would you like to start?[/bold]")
        console.print("  [cyan][1][/cyan] Mode A — council generates the seed idea")
        console.print("  [cyan][2][/cyan] Mode B — provide your own seed idea")
        while True:
            mode_choice = input("\nEnter choice (1/2): ").strip()
            if mode_choice == "1":
                console.print(
                    "\n[dim]Council will generate a seed idea for the domain.[/dim]"
                )
                break
            elif mode_choice == "2":
                while True:
                    seed = input("Enter your seed idea: ").strip()
                    if seed:
                        break
                    console.print("Please enter a seed idea.")
                break
            else:
                console.print("Please enter 1 or 2.")

    if seed:
        console.print(f"[bold]Seed:[/bold] {seed}")

    console.print("")

    progress = Progress(
        SpinnerColumn(finished_text="[green]✓[/green]"),
        TextColumn("{task.description}"),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    )

    def ask_user_with_pause(
        score: int, competitor_hits: list, seed_idea: str = ""
    ) -> str:
        progress.stop()
        if seed_idea:
            console.print(f"\n[bold]Idea being evaluated:[/bold]\n{seed_idea}")
        console.print(
            f"\n[bold]Market Openness:[/bold] {score}/10 — moderate competition found."
        )
        console.print("\nTop hits:")
        for url in competitor_hits[:5]:
            console.print(f"  [blue]{url}[/blue]")
        console.print("\nHow would you like to proceed?")
        console.print("  [1] Proceed  — synthesize this idea as-is")
        console.print("  [2] Reframe  — council finds the gap in the market")
        console.print("  [3] Abandon  — exit session")

        while True:
            choice = input("\nEnter choice (1/2/3): ").strip()
            if choice == "1":
                result = "proceed"
                break
            elif choice == "2":
                result = "reframe"
                break
            elif choice == "3":
                result = "abandon"
                break
            else:
                console.print("Please enter 1, 2, or 3.")

        progress.start()
        return result

    role_colors = {
        "optimist": "green",
        "critic": "red",
        "devils_advocate": "yellow",
        "domain_expert": "blue",
    }
    debater_tasks = {}
    debater_info = {}  # role -> {"label": str, "pm": str, "color": str}
    current_phase = {"text": ""}  # mutable container so closures can read/write it

    def on_debater_start(role: str, provider: str, model: str):
        color = role_colors.get(role, "white")
        label = role.replace("_", " ").title()
        debater_info[role] = {
            "label": label,
            "pm": f"{provider}/{model}",
            "color": color,
        }
        task_id = progress.add_task(
            f"  [{color}]{label:<18}[/{color}] [dim]{provider}/{model}[/dim]",
            total=None,
        )
        debater_tasks[role] = task_id

    def on_debater_done(role: str, provider: str, model: str):
        if role in debater_tasks:
            color = role_colors.get(role, "white")
            label = role.replace("_", " ").title()
            progress.update(
                debater_tasks[role],
                description=f"  [{color}]{label:<18}[/{color}] [dim]{provider}/{model}[/dim]",
                total=1,
                completed=1,
            )

    try:
        with progress:
            task = progress.add_task("Starting session...", total=None)

            def on_progress(msg: str):
                if debater_tasks:
                    # Print a permanent record of the round that just finished
                    # before removing the live spinner rows.
                    console.print(
                        f"[green]✓[/green] [bold]{current_phase['text']}[/bold]"
                    )
                    for info in debater_info.values():
                        color = info["color"]
                        console.print(
                            f"  [green]✓[/green] [{color}]{info['label']:<18}[/{color}]"
                            f" [dim]{info['pm']}[/dim]"
                        )
                    for task_id in list(debater_tasks.values()):
                        progress.remove_task(task_id)
                    debater_tasks.clear()
                    debater_info.clear()
                progress.update(task, description=f"[bold]{msg}[/bold]")
                current_phase["text"] = msg

            def on_reframe_prompt_ready(prompt: str):
                progress.stop()
                console.print(
                    f"  [dim]Reframe question:[/dim] {_truncate_to_lines(prompt)}\n"
                )
                progress.start()

            def on_seed_ready(generated_seed: str) -> str:
                progress.stop()
                console.print("\n[bold]Council selected this seed idea:[/bold]")
                console.print(
                    Panel(
                        generated_seed,
                        border_style="cyan",
                        box=box.ROUNDED,
                    )
                )
                console.print("  [cyan][1][/cyan] Pursue this idea")
                console.print("  [cyan][2][/cyan] Enter your own seed idea instead")
                while True:
                    choice = input("\nEnter choice (1/2): ").strip()
                    if choice == "1":
                        console.print("")
                        progress.start()
                        return generated_seed
                    elif choice == "2":
                        while True:
                            custom = input("Enter your seed idea: ").strip()
                            if custom:
                                break
                            console.print("Please enter a seed idea.")
                        console.print(f"\n[bold]Seed:[/bold] {custom}\n")
                        progress.start()
                        return custom
                    else:
                        console.print("Please enter 1 or 2.")

            report, filepath = run_session(
                domain=domain,
                seed=seed,
                exclusions=exclusions,
                user_context=context,
                max_rounds=rounds,
                verbose=False,
                ask_user_fn=ask_user_with_pause,
                on_progress=on_progress,
                on_roles_assigned=lambda assignments: _print_assignments(
                    assignments, progress
                ),
                on_reframe_started=lambda assignments: _print_assignments(
                    assignments, progress, title="Reframe council (roles rotated)"
                ),
                on_reframe_prompt_ready=on_reframe_prompt_ready,
                on_debater_start=on_debater_start,
                on_debater_done=on_debater_done,
                on_seed_ready=on_seed_ready,
            )
    except ValueError as e:
        console.print(f"[red]Configuration error:[/red] {e}")
        raise typer.Exit(1)
    except RuntimeError as e:
        console.print(f"[red]Session error:[/red] {e}")
        raise typer.Exit(1)

    # Print round output if verbose
    if verbose:
        for debate_round in report.rounds:
            _print_round(
                debate_round.round_number,
                debate_round.type,
                debate_round.responses,
                verbose=True,
            )

    # Print market verification results
    _print_market(report.market)

    # Print final report
    _print_final_report(report)

    console.print(f"\n[dim]Report saved to {filepath}[/dim]")

    if report.verdict == "abandon":
        raise typer.Exit(0)

    # Generate proposal if verdict is pursue (auto) or refine (ask user)
    should_generate = False
    if report.verdict == "pursue":
        should_generate = True
    elif report.verdict == "refine":
        console.print(
            "\n[yellow]The council recommends refining this idea before building.[/yellow]"
        )
        answer = input("Generate a project proposal anyway? [y/N]: ").strip().lower()
        should_generate = answer == "y"

    if should_generate:
        console.print("\n[dim]Generating project proposal...[/dim]")
        try:
            settings = load_settings()
            synth = build_synthesizer(settings)
            proposal_text = generate_proposal(
                report=report,
                synthesizer=synth,
                max_tokens=settings.max_tokens_per_call,
            )
            import os
            from datetime import datetime, UTC

            proposals_dir = "proposals"
            os.makedirs(proposals_dir, exist_ok=True)
            timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            slug = domain.lower().replace(" ", "_")[:40]
            proposal_path = os.path.join(proposals_dir, f"{timestamp}_{slug}.md")
            with open(proposal_path, "w") as f:
                f.write(f"# Project Proposal — {domain.title()}\n\n")
                f.write(
                    f"*Generated by idea-council · session {report.session_id} · {timestamp}*\n\n"
                )
                f.write("---\n\n")
                f.write(proposal_text)
            console.print(f"[green]Proposal saved to {proposal_path}[/green]")
        except Exception as e:
            console.print(f"[red]Proposal generation failed:[/red] {e}")
