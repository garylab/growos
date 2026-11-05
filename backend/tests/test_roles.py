"""The unified role vocabulary maps onto the two stored columns without losing information."""
import pytest

from app.models.user import MEMBER_ROLES, ROLES, split_role, unified_role


def test_role_vocabulary():
    assert ROLES == ("admin", "owner", "editor", "viewer")


@pytest.mark.parametrize("role", MEMBER_ROLES)
def test_project_roles_imply_a_non_admin_account(role):
    assert split_role(role) == ("member", role)


def test_admin_is_account_wide_and_leaves_the_project_role_alone():
    # None means "do not touch project_members.role", so demoting an admin restores their old project role.
    assert split_role("admin") == ("admin", None)


@pytest.mark.parametrize("role", ROLES)
def test_split_then_unify_round_trips(role):
    account_role, project_role = split_role(role)
    assert unified_role(account_role, project_role or "owner") == role


def test_admin_outranks_any_project_role():
    for project_role in MEMBER_ROLES:
        assert unified_role("admin", project_role) == "admin"


def test_member_with_no_project_row_is_read_only():
    assert unified_role("member", None) == "viewer"
