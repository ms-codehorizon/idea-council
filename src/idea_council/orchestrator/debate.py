import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from idea_council.models.session import DebateRound, RoleResponse
from idea_council.providers.adapter import ProviderAdapter
from idea_council.roles import prompts


def _strip_thinking_tags(text: str) -> str:
    """
    Remove <think>...</think> blocks that reasoning models (qwen3.5, deepseek-r1)
    emit before their actual response. Without stripping, the parser finds no
    POSITION: line and the response fails to parse.
    """
    stripped = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    return stripped.strip()


ROLE_SYSTEM_PROMPTS = {
    "optimist": prompts.OPTIMIST,
    "critic": prompts.CRITIC,
    "devils_advocate": prompts.DEVILS_ADVOCATE,
    "domain_expert": prompts.DOMAIN_EXPERT,
}


def _parse_confidence(raw: str) -> int:
    """Extract the confidence score from a debater response. Defaults to 5 if not found."""
    match = re.search(r"CONFIDENCE:\s*(\d+)", raw)
    if match:
        value = int(match.group(1))
        return max(1, min(10, value))
    return 5


def _parse_arguments(raw: str) -> list[str]:
    """Extract numbered arguments from a debater response."""
    arguments = []
    for line in raw.splitlines():
        line = line.strip()
        if re.match(r"^\d+\.", line):
            argument = re.sub(r"^\d+\.\s*", "", line)
            if argument:
                arguments.append(argument)
    return arguments


def _parse_position(raw: str) -> str:
    """Extract the POSITION line from a debater response."""
    for line in raw.splitlines():
        if line.strip().startswith("POSITION:"):
            return line.strip().replace("POSITION:", "").strip()
    return ""


def _call_debater(
    role: str,
    adapter: ProviderAdapter,
    fallback: ProviderAdapter,
    system: str,
    user: str,
    max_tokens: int,
    provider_events: list[str],
    is_reaction: bool = False,
) -> RoleResponse:
    """
    Calls a debater adapter. If the call fails, tries the fallback adapter once.
    If the fallback also fails, stores the error in provider_events and returns
    an empty RoleResponse so the debate can continue.
    """
    raw = ""
    used_adapter = adapter

    try:
        raw = _strip_thinking_tags(adapter.call(system=system, user=user, max_tokens=max_tokens))
    except Exception as e:
        event = f"[fallback] {adapter.provider}/{adapter.model} failed ({e}), retrying with {fallback.provider}/{fallback.model}"
        provider_events.append(event)
        print(event)
        try:
            raw = _strip_thinking_tags(fallback.call(system=system, user=user, max_tokens=max_tokens))
            used_adapter = fallback
        except Exception as e2:
            event = f"[skip] {adapter.provider}/{adapter.model} fallback also failed ({e2})"
            provider_events.append(event)
            print(event)
            return RoleResponse(
                role=role,
                provider=adapter.provider,
                model=adapter.model,
                position="",
                arguments=[],
                confidence=0,
                raw="",
            )

    # Attempt to parse structured fields. If parsing fails, store the raw
    # response and record a repair event.
    position = _parse_position(raw)
    arguments = _parse_arguments(raw)
    confidence = _parse_confidence(raw)

    if not position or (not arguments and not is_reaction):
        repair_prompt = (
            f"The following response did not follow the required format. "
            f"Please rewrite it in the correct format.\n\nOriginal response:\n{raw}"
        )
        event = f"[repair] {used_adapter.provider}/{used_adapter.model} response for role '{role}' did not parse — retrying with repair prompt"
        provider_events.append(event)
        try:
            raw = used_adapter.call(system=system, user=repair_prompt, max_tokens=max_tokens)
            position = _parse_position(raw)
            arguments = _parse_arguments(raw)
            confidence = _parse_confidence(raw)
        except Exception:
            event = f"[repair-failed] {used_adapter.provider}/{used_adapter.model} repair also failed — storing raw response"
            provider_events.append(event)

    return RoleResponse(
        role=role,
        provider=used_adapter.provider,
        model=used_adapter.model,
        position=position,
        arguments=arguments,
        confidence=confidence,
        raw=raw,
    )


def _build_reaction_context(round_responses: list[RoleResponse], current_role: str) -> str:
    """
    Builds the anonymized context for a reaction round.
    Other debaters are labeled Debater A, B, C — not by provider or model name.
    Only role labels are preserved.
    """
    other_responses = [r for r in round_responses if r.role != current_role]

    labels = ["Debater A", "Debater B", "Debater C"]
    lines = []

    for label, response in zip(labels, other_responses):
        lines.append(f"{label} ({response.role}):\n{response.raw}")

    return "\n\n---\n\n".join(lines)


def run_round(
    round_number: int,
    assignment: dict,
    seed_idea: str,
    fallback: ProviderAdapter,
    max_tokens: int,
    provider_events: list[str],
    previous_responses: list[RoleResponse] = None,
    on_debater_start=None,
    on_debater_done=None,
    user_context: str = None,
    exclusions: list[str] = None,
) -> DebateRound:
    """
    Runs one debate round. Round 1 is independent analysis. Round 2+ adds
    the reaction instructions and anonymized context from the previous round.
    """
    def _noop_role(*args):
        pass

    if on_debater_start is None:
        on_debater_start = _noop_role
    if on_debater_done is None:
        on_debater_done = _noop_role

    is_first_round = previous_responses is None
    round_type = "independent" if is_first_round else "reaction"

    # Build an optional preamble from user_context and exclusions so every
    # debater in every round sees them — including when --seed is provided.
    preamble_parts = []
    if user_context:
        preamble_parts.append(f"Builder context: {user_context}")
    if exclusions:
        excl_list = "\n".join(f"- {e}" for e in exclusions)
        preamble_parts.append(f"Existing projects to avoid:\n{excl_list}")
    preamble = "\n\n".join(preamble_parts) + "\n\n" if preamble_parts else ""

    futures = {}

    with ThreadPoolExecutor() as executor:
        for role, adapter in assignment.items():
            system = ROLE_SYSTEM_PROMPTS[role]

            if is_first_round:
                user = preamble + f"Here is the idea to evaluate:\n\n{seed_idea}"
            else:
                context = _build_reaction_context(previous_responses, role)
                own_previous = next((r for r in previous_responses if r.role == role), None)
                own_previous_text = own_previous.raw if own_previous else ""

                user = (
                    preamble +
                    f"Here is the idea being evaluated:\n\n{seed_idea}\n\n"
                    f"Your previous response:\n\n{own_previous_text}\n\n"
                    f"Other council members' responses:\n\n{context}\n\n"
                    f"{prompts.REACTION_INSTRUCTIONS}"
                )

            on_debater_start(role, adapter.provider, adapter.model)
            future = executor.submit(
                _call_debater,
                role,
                adapter,
                fallback,
                system,
                user,
                max_tokens,
                provider_events,
                not is_first_round,  # is_reaction
            )
            futures[future] = role

        responses = []
        for future in as_completed(futures):
            response = future.result()
            responses.append(response)
            on_debater_done(response.role, response.provider, response.model)

    # Sort so output is consistent across runs
    role_order = list(assignment.keys())
    responses.sort(key=lambda r: role_order.index(r.role) if r.role in role_order else 99)

    return DebateRound(
        round_number=round_number,
        type=round_type,
        responses=responses,
        synthesizer_signal="not_checked",  # will be updated by the caller
    )
