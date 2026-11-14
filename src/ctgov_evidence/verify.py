"""Check each narrative sentence against the registry records it cites.

A sentence passes only if it cites at least one known NCT ID and every checkable claim in it
(numbers, phases, statuses, sponsor and intervention names, posted results) is supported by
the cited trials. The check is deliberately conservative: it flags what it cannot support.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from .models import Trial
from .summarise import phase_label

CITE_RE = re.compile(r"\[\s*(NCT\d{8}(?:\s*[,;]\s*NCT\d{8})*)\s*\]")
NCT_RE = re.compile(r"NCT\d{8}")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\[])")
NUMBER_RE = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?(?![\w])")
ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4}
PHASE_RE = re.compile(
    r"\bphase\s*(?P<a>[1-4]|iv|iii|ii|i)\b"
    r"(?:\s*(?:/|and|or)\s*(?:phase\s*)?(?P<b>[1-4]|iv|iii|ii|i)\b)?",
    re.IGNORECASE,
)
WORD_NUMBERS = {
    w: i
    for i, w in enumerate(
        "zero one two three four five six seven eight nine ten eleven twelve thirteen "
        "fourteen fifteen sixteen seventeen eighteen nineteen twenty".split()
    )
}
STATUS_PHRASES = {
    "not yet recruiting": "NOT_YET_RECRUITING",
    "active, not recruiting": "ACTIVE_NOT_RECRUITING",
    "active not recruiting": "ACTIVE_NOT_RECRUITING",
    "enrolling by invitation": "ENROLLING_BY_INVITATION",
    "recruiting": "RECRUITING",
    "completed": "COMPLETED",
    "terminated": "TERMINATED",
    "withdrawn": "WITHDRAWN",
    "suspended": "SUSPENDED",
}
RESULTS_RE = re.compile(
    r"\b(?:posted results|results posted|results (?:are )?posted|have results)\b", re.I
)
NEGATION_RE = re.compile(r"\b(?:no|not|none|without|neither|never)\b", re.I)
ORG_RE = re.compile(
    r"\b(?:[A-Z][\w&'.-]*\s+){1,6}(?:Inc|Ltd|LLC|Corporation|Corp|Company|Pharmaceuticals?|"
    r"Pharma|University|Hospital|Institute|Foundation|GmbH|AG|SA|Co)\b\.?"
)


@dataclass
class SentenceResult:
    text: str
    cited: list[str]
    ok: bool
    reasons: list[str] = field(default_factory=list)


@dataclass
class VerificationReport:
    sentences: list[SentenceResult]

    @property
    def n_total(self) -> int:
        return len(self.sentences)

    @property
    def n_verified(self) -> int:
        return sum(1 for s in self.sentences if s.ok)

    def render(self, on_fail: str = "mark") -> str:
        """Rebuild the paragraph. Failed sentences are tagged or dropped."""
        parts = []
        for s in self.sentences:
            if s.ok:
                parts.append(s.text)
            elif on_fail == "mark":
                parts.append(f"{s.text} [unverified]")
        return " ".join(parts)


def split_sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    return [s for s in SENTENCE_SPLIT_RE.split(text) if s]


UNIT = r"(?:weeks?|months?|days?|years?|hours?)"
UNIT_AFTER_RE = re.compile(rf"^\s*-?\s*{UNIT}\b", re.I)
UNIT_BEFORE_RE = re.compile(rf"\b{UNIT}\s*$", re.I)


def _numbers(text: str) -> list[tuple[float, bool]]:
    """Numbers in the text, each flagged when it sits next to a time unit (``16 weeks``)."""
    out: list[tuple[float, bool]] = []
    for m in NUMBER_RE.finditer(text):
        try:
            value = float(m.group(0).replace(",", ""))
        except ValueError:
            continue
        timed = bool(
            UNIT_AFTER_RE.match(text[m.end() :]) or UNIT_BEFORE_RE.search(text[: m.start()])
        )
        out.append((value, timed))
    for word in re.findall(r"\b[a-z]+\b", text.lower()):
        if word in WORD_NUMBERS:
            out.append((float(WORD_NUMBERS[word]), False))
    return out


def _years(value: str | None) -> set[int]:
    return {int(y) for y in re.findall(r"\b(?:19|20)\d{2}\b", value or "")}


def _time_frame_numbers(trials: list[Trial]) -> set[float]:
    out: set[float] = set()
    for t in trials:
        for o in t.primary_outcomes.value or []:
            out |= {float(m) for m in re.findall(r"\d+", o.time_frame or "")}
    return out


def _supported_numbers(cited: list[Trial]) -> set[float]:
    ok: set[float] = {float(len(cited))}
    by_kind: dict[str, int] = {}
    for t in cited:
        if t.enrollment.value is not None:
            ok.add(float(t.enrollment.value))
            kind = t.enrollment_type.value or "UNSPECIFIED"
            by_kind[kind] = by_kind.get(kind, 0) + t.enrollment.value
        for d in (t.start_date, t.primary_completion_date, t.completion_date):
            ok |= {float(x) for x in _years(d.value)}
        if t.interventions.value:
            ok.add(float(len(t.interventions.value)))
    ok |= {float(v) for v in by_kind.values()}
    if by_kind:
        ok.add(float(sum(by_kind.values())))
    # counts of cited trials sharing a categorical value
    for getter in (
        lambda t: t.status.value,
        lambda t: phase_label(t.phase.value),
        lambda t: t.sponsor.value,
        lambda t: t.has_results.value,
        lambda t: t.enrollment_type.value,
        lambda t: t.study_type.value,
        lambda t: t.allocation.value,
        lambda t: t.masking.value,
    ):
        ok |= {float(n) for n in Counter(getter(t) for t in cited).values()}
    return ok


def _roman_or_int(token: str) -> int:
    return int(token) if token.isdigit() else ROMAN[token.lower()]


def _mentioned_phases(text: str) -> tuple[set[int], str]:
    found: set[int] = set()
    for m in PHASE_RE.finditer(text):
        found.add(_roman_or_int(m.group("a")))
        if m.group("b"):
            found.add(_roman_or_int(m.group("b")))
    return found, PHASE_RE.sub(" ", text)


def _trial_phase_numbers(t: Trial) -> set[int]:
    nums = set()
    for p in t.phase.value or []:
        m = re.fullmatch(r"(?:EARLY_)?PHASE(\d)", p)
        if m:
            nums.add(int(m.group(1)))
    return nums


def verify_sentence(sentence: str, all_trials: list[Trial]) -> SentenceResult:
    by_id = {t.nct_id: t for t in all_trials}
    cited_ids: list[str] = []
    for m in CITE_RE.finditer(sentence):
        cited_ids += NCT_RE.findall(m.group(1))
    cited_ids = list(dict.fromkeys(cited_ids))
    reasons: list[str] = []

    if not cited_ids:
        return SentenceResult(sentence, [], False, ["no NCT citation"])
    unknown = [c for c in cited_ids if c not in by_id]
    if unknown:
        reasons.append("cites NCT ID(s) not in the retrieved set: " + ", ".join(unknown))
    cited = [by_id[c] for c in cited_ids if c in by_id]
    if not cited:
        return SentenceResult(sentence, cited_ids, False, reasons)

    body = NCT_RE.sub(" ", CITE_RE.sub(" ", sentence))

    # phases
    phases, body_no_phase = _mentioned_phases(body)
    if phases:
        available = set().union(*(_trial_phase_numbers(t) for t in cited))
        for p in sorted(phases - available):
            reasons.append(f"phase {p} not a phase of any cited trial")

    # numbers
    supported = _supported_numbers(cited) | {float(len(all_trials))}
    timed_ok = _time_frame_numbers(cited)
    for n, timed in _numbers(body_no_phase):
        if n in supported or (timed and n in timed_ok):
            continue
        shown = int(n) if n == int(n) else n
        reasons.append(f"number {shown} not supported by cited trials")

    # statuses
    lowered = body.lower()
    cited_statuses = {t.status.value for t in cited}
    remaining = lowered
    for phrase, code in STATUS_PHRASES.items():
        if phrase in remaining:
            remaining = remaining.replace(phrase, " ")
            if code not in cited_statuses:
                reasons.append(f"status '{phrase}' does not match any cited trial")

    # results
    if RESULTS_RE.search(body):
        negated = bool(NEGATION_RE.search(body))
        for t in cited:
            if t.has_results.value is (not negated) or t.has_results.value is None:
                continue
            reasons.append(
                f"{t.nct_id} {'has no' if not negated else 'has'} posted results, "
                "which contradicts the sentence"
            )

    # named entities known from the retrieved set
    cited_sponsors = {t.sponsor.value for t in cited if t.sponsor.value}
    cited_text = " ".join(
        [
            *(i for t in cited for i in (t.interventions.value or [])),
            *(t.title.value or "" for t in cited),
            *(c for t in cited for c in (t.conditions.value or [])),
        ]
    ).lower()
    for t in all_trials:
        name = t.sponsor.value
        if name and name not in cited_sponsors and name.lower() in lowered:
            reasons.append(f"sponsor '{name}' is not a sponsor of any cited trial")
    for t in all_trials:
        for name in t.interventions.value or []:
            if len(name) > 3 and name.lower() in lowered and name.lower() not in cited_text:
                reasons.append(f"intervention '{name}' is not in any cited trial")
    known_sponsors = {t.sponsor.value.lower() for t in all_trials if t.sponsor.value}
    for m in ORG_RE.finditer(body):
        candidate = m.group(0).rstrip(".").strip()
        low = candidate.lower()
        if not any(low in k or k in low for k in known_sponsors):
            reasons.append(f"organisation '{candidate}' does not appear in the retrieved records")

    reasons = list(dict.fromkeys(reasons))
    return SentenceResult(sentence, cited_ids, not reasons, reasons)


def verify_narrative(text: str, trials: list[Trial]) -> VerificationReport:
    return VerificationReport([verify_sentence(s, trials) for s in split_sentences(text)])
