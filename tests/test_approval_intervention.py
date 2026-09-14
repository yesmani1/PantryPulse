"""BE-20 must use the Strands intervention primitive for approval."""

from types import SimpleNamespace

from strands.interventions.actions import Confirm, Proceed

from pantrypulse.agents.approvals import DonationApprovalIntervention


def test_donation_tool_returns_strands_confirm_action():
    action = DonationApprovalIntervention().before_tool_call(
        SimpleNamespace(selected_tool=SimpleNamespace(tool_name="request_donation"))
    )
    assert isinstance(action, Confirm)
    assert "Approve" in action.prompt


def test_non_consequential_tools_proceed_without_pause():
    action = DonationApprovalIntervention().before_tool_call(
        SimpleNamespace(selected_tool=SimpleNamespace(tool_name="find_recipe"))
    )
    assert isinstance(action, Proceed)
