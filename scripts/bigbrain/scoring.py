"""Auto-escalation scoring (item 1).

Turns a handful of cheap signals about a task into a single 0..1 score and an
escalate/stay-local decision.  The point is to make "should I bother the
advisor?" a number that an agent can compute honestly, instead of a judgement
call that quietly drifts toward whatever is convenient.

Signals and their defaults::

    files        --files-changed N / --files-estimated N   saturates at 5
    ambiguity    --ambiguity 0..1                          used as-is
    failures     --consecutive-failures N                  saturates at 3
    risk         --high-risk migration,delete,auth,...     binary
    user         --user-request                            binary

Each component is weighted, the weights are normalised to sum to 1.0, and the
weighted sum is the score.  ``score > threshold`` (default 0.60) means escalate.
"""

from __future__ import annotations

from .config import (
    DEFAULT_THRESHOLD,
    DEFAULT_WEIGHTS,
    FAILURES_SATURATION,
    FILES_SATURATION,
    RISK_TAGS,
)

COMPONENTS = ("files", "ambiguity", "failures", "risk", "user")

_HUMAN = {
    "files": "files touched",
    "ambiguity": "ambiguity",
    "failures": "consecutive failures",
    "risk": "high-risk domain",
    "user": "user asked for the advisor",
}


def parse_risk_tags(raw):
    """Parse ``--high-risk`` values into a normalised, de-duplicated list."""
    tags = []
    if raw is None:
        return tags
    if isinstance(raw, str):
        raw = [raw]
    for item in raw:
        if item is None:
            continue
        for piece in str(item).replace(";", ",").split(","):
            piece = piece.strip().lower()
            if piece and piece not in tags:
                tags.append(piece)
    return tags


def _normalise_weights(weights):
    merged = dict(DEFAULT_WEIGHTS)
    for key, value in (weights or {}).items():
        if key in merged:
            try:
                merged[key] = float(value)
            except (TypeError, ValueError):
                continue
    total = sum(merged.values())
    if total <= 0:
        return dict(DEFAULT_WEIGHTS)
    return {key: value / total for key, value in merged.items()}


def _ratio(value, saturation):
    if value is None:
        return 0.0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if number <= 0:
        return 0.0
    return min(1.0, number / float(saturation))


def score_task(
    files=None,
    ambiguity=0.0,
    consecutive_failures=0,
    high_risk=None,
    user_request=False,
    weights=None,
    threshold=None,
):
    """Return a result dict describing the escalation decision.

    Keys: ``score``, ``threshold``, ``decision`` (``escalate``/``stay_local``),
    ``components`` (per-signal contribution), ``signals`` (raw inputs),
    ``risk_tags``, ``weights`` and ``reasons``.
    """
    effective_weights = _normalise_weights(weights)
    effective_threshold = DEFAULT_THRESHOLD if threshold is None else float(threshold)

    tags = parse_risk_tags(high_risk)
    if tags:
        risk_value = 1.0
    else:
        risk_value = 0.0

    ambiguity_value = 0.0
    if ambiguity is not None:
        try:
            ambiguity_value = max(0.0, min(1.0, float(ambiguity)))
        except (TypeError, ValueError):
            ambiguity_value = 0.0

    signals = {
        "files": 0 if files is None else max(0, int(files)),
        "ambiguity": ambiguity_value,
        "consecutive_failures": 0 if consecutive_failures is None else max(0, int(consecutive_failures)),
        "high_risk": tags,
        "user_request": bool(user_request),
    }

    raw_ratios = {
        "files": _ratio(signals["files"], FILES_SATURATION),
        "ambiguity": ambiguity_value,
        "failures": _ratio(signals["consecutive_failures"], FAILURES_SATURATION),
        "risk": risk_value,
        "user": 1.0 if signals["user_request"] else 0.0,
    }

    components = {}
    for key in COMPONENTS:
        components[key] = round(raw_ratios[key] * effective_weights[key], 6)

    score = round(sum(components.values()), 6)
    score = max(0.0, min(1.0, score))
    decision = "escalate" if user_request or score > effective_threshold else "stay_local"

    reasons = []
    if signals["files"]:
        reasons.append("%d file(s) changed" % signals["files"])
    if ambiguity_value:
        reasons.append("ambiguity %.2f" % ambiguity_value)
    if signals["consecutive_failures"]:
        reasons.append("%d consecutive failure(s)" % signals["consecutive_failures"])
    if tags:
        reasons.append("high-risk: %s" % ",".join(tags))
    if signals["user_request"]:
        reasons.append("user requested the advisor")

    return {
        "score": score,
        "threshold": effective_threshold,
        "decision": decision,
        "components": components,
        "raw": raw_ratios,
        "signals": signals,
        "risk_tags": tags,
        "weights": effective_weights,
        "reasons": reasons,
    }


def banner_line(result, prefix="[Bigbrain]"):
    """The one-line human banner, e.g.

    ``[Bigbrain] evaluating escalation score 0.72 > 0.60 -> escalate``
    """
    if result["signals"]["user_request"]:
        return "%s user requested the advisor -> escalate (score %.2f)" % (prefix, result["score"])
    operator = ">" if result["decision"] == "escalate" else "<="
    return "%s evaluating escalation score %.2f %s %.2f -> %s" % (
        prefix,
        result["score"],
        operator,
        result["threshold"],
        result["decision"],
    )


def explain(result, indent="  ", include_banner=True):
    """Multi-line breakdown suitable for ``score --explain``."""
    lines = [banner_line(result)] if include_banner else []
    lines.append("%sweights (normalised): %s" % (indent, ", ".join(
        "%s=%.2f" % (key, result["weights"][key]) for key in COMPONENTS
    )))
    for key in COMPONENTS:
        lines.append(
            "%s%-10s raw=%.2f  weight=%.2f  contributes %.3f%s"
            % (
                indent,
                key,
                result["raw"][key],
                result["weights"][key],
                result["components"][key],
                "  (%s)" % _HUMAN[key],
            )
        )
    if result["risk_tags"]:
        known = [tag for tag in result["risk_tags"] if tag in RISK_TAGS]
        unknown = [tag for tag in result["risk_tags"] if tag not in RISK_TAGS]
        if unknown:
            lines.append(
                "%snote: unrecognised risk tags still count as high-risk: %s"
                % (indent, ", ".join(unknown))
            )
        if known:
            lines.append("%srecognised risk tags: %s" % (indent, ", ".join(known)))
    if result["signals"]["files"] == 0 and not result["risk_tags"] and not result["signals"]["user_request"]:
        lines.append("%sno signals given: score 0.00, stay local" % indent)
    return "\n".join(lines)
