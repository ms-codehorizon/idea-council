import pytest
from tests.conftest import MockAdapter
from idea_council.orchestrator.rotation import assign_roles, describe_assignments, ROLES


def make_debaters(count: int) -> list:
    return [MockAdapter(f"provider_{i}", f"model_{i}", "response") for i in range(count)]


def test_assign_roles_returns_correct_number_of_assignments():
    debaters = make_debaters(3)
    assignment = assign_roles(debaters)
    assert len(assignment) == 3


def test_assign_roles_uses_priority_order_when_fewer_than_four_debaters():
    debaters = make_debaters(2)
    assignment = assign_roles(debaters)
    assigned_roles = list(assignment.keys())
    assert "optimist" in assigned_roles
    assert "critic" in assigned_roles
    assert "devils_advocate" not in assigned_roles
    assert "domain_expert" not in assigned_roles


def test_assign_roles_drops_lowest_priority_first():
    debaters = make_debaters(3)
    assignment = assign_roles(debaters)
    assigned_roles = list(assignment.keys())
    assert "domain_expert" not in assigned_roles
    assert "optimist" in assigned_roles
    assert "critic" in assigned_roles
    assert "devils_advocate" in assigned_roles


def test_assign_roles_four_debaters_gets_all_roles():
    debaters = make_debaters(4)
    assignment = assign_roles(debaters)
    assert set(assignment.keys()) == set(ROLES)


def test_assign_roles_raises_if_fewer_than_two_debaters():
    debaters = make_debaters(1)
    with pytest.raises(ValueError, match="At least 2 debaters"):
        assign_roles(debaters)


def test_assign_roles_shuffles_providers():
    """
    Run assignment 20 times and confirm that the same provider is not always
    assigned to the same role. If assignment were deterministic this would fail.
    """
    debaters = make_debaters(4)
    first_role_providers = set()

    for _ in range(20):
        assignment = assign_roles(debaters)
        first_role = list(assignment.values())[0]
        first_role_providers.add(first_role.provider)

    assert len(first_role_providers) > 1


def test_describe_assignments_returns_serializable_dict():
    debaters = make_debaters(3)
    assignment = assign_roles(debaters)
    description = describe_assignments(assignment)

    for role, info in description.items():
        assert "provider" in info
        assert "model" in info
        assert isinstance(info["provider"], str)
        assert isinstance(info["model"], str)
