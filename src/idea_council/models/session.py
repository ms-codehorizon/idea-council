from dataclasses import dataclass
from typing import Optional


@dataclass
class RoleResponse:
    role: str
    provider: str
    model: str
    position: str
    arguments: list[str]
    confidence: int  # 1-10
    raw: str


@dataclass
class DebateRound:
    round_number: int
    type: str  # "independent" or "reaction"
    responses: list[RoleResponse]
    synthesizer_signal: str  # "continue", "done", or "not_checked"


@dataclass
class MarketVerification:
    search_queries: list[str]
    github_hits: list[str]
    web_hits: list[str]
    competitor_hits: list[str]  # deduplicated union of github + web hits
    market_openness: Optional[int]  # 1-10, higher = more open space, null if search was skipped
    remaining_gap: Optional[str]  # gap identified by synthesizer, if any
    skipped: bool


@dataclass
class FinalReport:
    session_id: str
    domain: str
    seed_idea: str
    seed_mode: str  # "generated" or "user_provided"
    exclusions: Optional[list[str]]
    user_context: Optional[str]
    role_assignments: dict  # role -> {"provider": str, "model": str}
    rejected_seeds: list[str]
    rounds: list[DebateRound]
    rounds_completed: int
    exit_reason: str  # "synthesizer_done" or "max_rounds_reached"
    verdict: str  # "pursue", "pivot", or "abandon"
    opportunity_score: int  # 1-10
    strongest_argument: str
    fatal_flaw: str
    kill_conditions: list[str]
    what_must_be_true: list[str]
    market: Optional[MarketVerification]
    pivot_triggered: bool
    pivot_seed: Optional[str]
    user_choice: Optional[str]  # "proceed", "pivot", or "abandon" — set when score 5-7
    provider_events: list[str]  # fallback, skip, and repair events
