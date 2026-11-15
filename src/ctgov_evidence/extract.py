"""Raw registry JSON to ``Trial``, recording the source path of every value."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .models import Outcome, Sourced, Trial

PROTOCOL = "protocolSection"


class ExtractionError(ValueError):
    """The record has no NCT ID, so it cannot be identified."""


def _dig(obj: Any, path: str) -> Any:
    for key in path.split("."):
        if not isinstance(obj, dict) or key not in obj:
            return None
        obj = obj[key]
    return obj


def _field(
    raw: dict[str, Any],
    nct_id: str,
    path: str,
    convert: Callable[[Any], Any] | None = None,
) -> Sourced[Any]:
    """Read ``path`` from ``raw``. Empty values and conversion failures become None."""
    value = _dig(raw, path)
    if value in (None, "", []):
        value = None
    elif convert is not None:
        try:
            value = convert(value)
        except (TypeError, ValueError):
            value = None
    return Sourced(value=value, source=f"{nct_id}:{path}")


def _names(items: Any) -> list[str] | None:
    if not isinstance(items, list):
        return None
    names = [i["name"] for i in items if isinstance(i, dict) and i.get("name")]
    return names or None


def _outcomes(items: Any) -> list[Outcome] | None:
    if not isinstance(items, list):
        return None
    out = [
        Outcome(measure=i.get("measure"), time_frame=i.get("timeFrame"))
        for i in items
        if isinstance(i, dict)
    ]
    return out or None


def _string_list(items: Any) -> list[str] | None:
    if not isinstance(items, list):
        return None
    out = [str(i) for i in items if i not in (None, "")]
    return out or None


def extract_trial(raw: dict[str, Any]) -> Trial:
    nct_id = _dig(raw, f"{PROTOCOL}.identificationModule.nctId")
    if not nct_id:
        raise ExtractionError("Record has no protocolSection.identificationModule.nctId")
    p = PROTOCOL

    def f(path: str, convert: Callable[[Any], Any] | None = None) -> Sourced[Any]:
        return _field(raw, nct_id, path, convert)

    return Trial(
        nct_id=nct_id,
        title=f(f"{p}.identificationModule.briefTitle", str),
        sponsor=f(f"{p}.sponsorCollaboratorsModule.leadSponsor.name", str),
        sponsor_class=f(f"{p}.sponsorCollaboratorsModule.leadSponsor.class", str),
        study_type=f(f"{p}.designModule.studyType", str),
        phase=f(f"{p}.designModule.phases", _string_list),
        status=f(f"{p}.statusModule.overallStatus", str),
        enrollment=f(f"{p}.designModule.enrollmentInfo.count", int),
        enrollment_type=f(f"{p}.designModule.enrollmentInfo.type", str),
        start_date=f(f"{p}.statusModule.startDateStruct.date", str),
        primary_completion_date=f(f"{p}.statusModule.primaryCompletionDateStruct.date", str),
        completion_date=f(f"{p}.statusModule.completionDateStruct.date", str),
        allocation=f(f"{p}.designModule.designInfo.allocation", str),
        masking=f(f"{p}.designModule.designInfo.maskingInfo.masking", str),
        conditions=f(f"{p}.conditionsModule.conditions", _string_list),
        interventions=f(f"{p}.armsInterventionsModule.interventions", _names),
        primary_outcomes=f(f"{p}.outcomesModule.primaryOutcomes", _outcomes),
        has_results=f("hasResults", bool),
        results_first_submitted=f(f"{p}.statusModule.resultsFirstSubmitDate", str),
        fda_regulated_drug=f(f"{p}.oversightModule.isFdaRegulatedDrug", bool),
        fda_regulated_device=f(f"{p}.oversightModule.isFdaRegulatedDevice", bool),
    )
