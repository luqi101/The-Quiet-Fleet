"""Explain credible inventory mismatches without treating roster status as a timeline."""

from .asset_context import DeviceContext
from .fault import FaultDecision
from .models import LikelyCause, WhoActs
from .time_utils import from_epoch_us, utc_text


def assignment_fault(context: DeviceContext) -> FaultDecision | None:
    if context.documented_removed:
        return None

    if context.assignment_ambiguous:
        reason = "Eligible VIN reports conflict about the installed tracker or its assigned asset."
    elif context.assignment_evidence and context.asset_id is not None:
        device = context.device
        if device.asset_id == context.asset_id and device.status != "stock":
            return None
        if device.asset_id is not None and device.asset_id != context.asset_id:
            reason = f"The reported VIN matches asset {context.asset_id}, while inventory lists {device.asset_id}."
        else:
            reason = f"The reported VIN matches asset {context.asset_id}, while inventory shows this serial as unassigned or in stock."
    else:
        return None

    claim = max(event.observed_us for event in context.assignment_evidence if event.observed_us is not None)
    reason += f" The latest supporting observation is from {utc_text(from_epoch_us(claim))}."
    return FaultDecision(
        cause=LikelyCause.DEVICE_SWAPPED,
        reason=reason,
        evidence=context.assignment_evidence,
        owner=WhoActs.SUPPORT,
        next_action="Verify the installed serial against the reported VIN and reconcile the inventory record.",
        confidence=0.8 if context.assignment_ambiguous else 1.0,
    )
