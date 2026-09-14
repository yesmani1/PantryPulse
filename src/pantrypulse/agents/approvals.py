"""Strands-native approval gates for consequential PantryPulse tool calls."""

from __future__ import annotations

from typing import Any

from strands import InterventionHandler
from strands.interventions.actions import Confirm, Proceed


class DonationApprovalIntervention(InterventionHandler):
    """Pause the agent before its donation-request tool can dispatch.

    The handler deliberately returns Strands' ``Confirm`` action.  This lets a
    runtime suspend and resume through the SDK's interruption mechanism instead
    of treating a Telegram callback as an authorization webhook.
    """

    @property
    def name(self) -> str:
        return "pantrypulse-donation-approval"

    def before_tool_call(self, event: Any, **_: Any) -> Confirm | Proceed:
        tool = getattr(event, "selected_tool", None)
        tool_name = getattr(tool, "tool_name", None) or getattr(tool, "name", None)
        if tool_name == "request_donation":
            return Confirm(
                prompt="Approve the donation request before PantryPulse contacts the mock recipient?"
            )
        return Proceed(reason="No approval is required for this tool.")
