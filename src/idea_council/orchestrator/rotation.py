import random

from idea_council.providers.adapter import ProviderAdapter


# Roles in priority order — when fewer than 4 debaters are available,
# roles are dropped from the bottom of this list first.
ROLES = ["optimist", "critic", "devils_advocate", "domain_expert"]


def assign_roles(debaters: list[ProviderAdapter]) -> dict:
    """
    Randomly assigns roles to debaters. If there are fewer debaters than
    roles, the lowest-priority roles are dropped. If there are more debaters
    than roles, the extra debaters are not used.

    Returns a dict mapping role -> ProviderAdapter.
    """
    if len(debaters) < 2:
        raise ValueError(
            f"At least 2 debaters are required to run a debate. Got {len(debaters)}."
        )

    active_roles = ROLES[: len(debaters)]

    shuffled_debaters = debaters.copy()
    random.shuffle(shuffled_debaters)

    assignment = {}
    for role, debater in zip(active_roles, shuffled_debaters):
        assignment[role] = debater

    return assignment


def describe_assignments(assignment: dict) -> dict:
    """
    Returns a serializable summary of role assignments for the final report.
    Format: { role: { "provider": str, "model": str } }
    """
    result = {}
    for role, adapter in assignment.items():
        result[role] = {
            "provider": adapter.provider,
            "model": adapter.model,
        }
    return result
