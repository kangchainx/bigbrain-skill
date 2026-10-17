"""The advisor JSON contract: tolerant extraction, validation, normalisation.

The advisor must reply with exactly one JSON object.  Real models sometimes wrap
it in prose or a code fence anyway, so extraction is deliberately forgiving while
validation stays strict.

Contract (extended for the milestone flow):

    {
      "status": "continue|done|blocked",
      "summary": str,
      "assumptions": [str],
      "questions_for_executor": [str],
      "plan": [{"id","action","files","verify"}],
      "milestones": [{"id","title","steps":[...],"acceptance_criteria":[str]}],
      "current_milestone": str|null,
      "acceptance_criteria": [str],          # global, set on round 1
      "criteria_status": [{"criterion","met","evidence"}],
      "lessons": [{"text","kind","scope","confidence"}],
      "review": {"verdict": "approve|revise|reject|n/a", "issues": [str]},
      "next_instructions": str,
      "blocked_reason": str|null
    }
"""

from __future__ import annotations

import json
import re

from .config import (
    ADVISOR_STATUSES,
    ADVISOR_VERDICTS,
    CRITERIA_STATES,
    LESSON_KINDS,
    AdvisorParseError,
)

# --------------------------------------------------------------------------
# Tolerant JSON extraction
# --------------------------------------------------------------------------

_FENCE_RE = re.compile(r"```[ \t]*(?:json|JSON)?[ \t]*\r?\n?(.*?)```", re.S)


def _balanced_objects(text):
    """Yield every top-level {...} substring using a brace/string aware scan."""
    index = 0
    length = len(text)
    while index < length:
        if text[index] != "{":
            index += 1
            continue
        depth = 0
        in_string = False
        escaped = False
        found = None
        for pos in range(index, length):
            char = text[pos]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    found = text[index:pos + 1]
                    index = pos + 1
                    break
        if found is None:
            return
        yield found


def _candidates(text):
    stripped = text.strip()
    if stripped:
        yield stripped
    for match in _FENCE_RE.finditer(text):
        inner = match.group(1).strip()
        if inner:
            yield inner


def extract_json_object(text):
    """Best-effort extraction of a single JSON object from a model reply.

    Tolerates ```json fences, leading prose, and trailing commentary.
    """
    if not isinstance(text, str) or not text.strip():
        raise AdvisorParseError("advisor reply was empty")
    first_error = None
    seen = set()
    for candidate in _candidates(text):
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            parsed = json.loads(candidate)
        except ValueError as exc:
            first_error = first_error or exc
        else:
            if isinstance(parsed, dict):
                return parsed
        for chunk in _balanced_objects(candidate):
            try:
                parsed = json.loads(chunk)
            except ValueError:
                continue
            if isinstance(parsed, dict):
                return parsed
    detail = " (%s)" % first_error if first_error else ""
    raise AdvisorParseError("no JSON object found in advisor reply%s" % detail)


# --------------------------------------------------------------------------
# Field coercion helpers
# --------------------------------------------------------------------------


def _str_list(value, field, errors):
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if not isinstance(value, (list, tuple)):
        errors.append("%s must be a list of strings" % field)
        return []
    out = []
    for item in value:
        if isinstance(item, (dict, list)):
            out.append(json.dumps(item, ensure_ascii=False))
        else:
            out.append(str(item))
    return out


def _as_text(value, field, errors, default=""):
    if value is None:
        return default
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    errors.append("%s must be a string" % field)
    return default


def _as_confidence(value, field, errors, default=0.5):
    if value is None:
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        errors.append("%s must be a number in 0..1" % field)
        return default
    if number < 0.0 or number > 1.0:
        errors.append("%s must be in 0..1, got %s" % (field, number))
        return max(0.0, min(1.0, number))
    return number


# --------------------------------------------------------------------------
# Sub-object normalisers
# --------------------------------------------------------------------------


def _normalise_step(step, index, errors, prefix="plan"):
    if not isinstance(step, dict):
        errors.append("%s[%d] must be an object with id/action/files/verify" % (prefix, index))
        return None
    return {
        "id": _as_text(step.get("id"), "%s[%d].id" % (prefix, index), errors, str(index + 1)),
        "action": _as_text(step.get("action"), "%s[%d].action" % (prefix, index), errors),
        "files": _str_list(step.get("files"), "%s[%d].files" % (prefix, index), errors),
        "verify": _as_text(step.get("verify"), "%s[%d].verify" % (prefix, index), errors),
    }


def _normalise_milestones(value, errors):
    """Milestones are the advisor's plan skeleton; a bad one is a hard error.

    An advisor that emits a malformed milestone would silently drop the review
    unit the executor is supposed to work against, so unlike a stray plan step
    this is treated as a schema failure worth a repair round.
    """
    if value is None:
        return []
    if not isinstance(value, list):
        errors.append("milestones must be a list of objects")
        return []
    out = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            errors.append("milestones[%d] must be an object with id/title/steps" % index)
            continue
        milestone_id = _as_text(item.get("id"), "milestones[%d].id" % index, errors, str(index + 1))
        if not milestone_id:
            milestone_id = str(index + 1)
        steps_in = item.get("steps")
        if steps_in is None:
            steps_in = []
        if not isinstance(steps_in, list):
            errors.append("milestones[%d].steps must be a list of step objects" % index)
            steps_in = []
        steps = []
        for step_index, step in enumerate(steps_in):
            normalised_step = _normalise_step(
                step, step_index, errors, prefix="milestones[%d].steps" % index
            )
            if normalised_step is not None:
                steps.append(normalised_step)
        out.append(
            {
                "id": milestone_id,
                "title": _as_text(item.get("title"), "milestones[%d].title" % index, errors),
                "steps": steps,
                "acceptance_criteria": _str_list(
                    item.get("acceptance_criteria"),
                    "milestones[%d].acceptance_criteria" % index,
                    errors,
                ),
            }
        )
    return out


def _normalise_criteria_status(value, errors):
    if value is None:
        return []
    if not isinstance(value, list):
        errors.append("criteria_status must be a list of objects")
        return []
    out = []
    for index, item in enumerate(value):
        if isinstance(item, str):
            out.append({"criterion": item, "met": False, "evidence": ""})
            continue
        if not isinstance(item, dict):
            errors.append("criteria_status[%d] must be an object or string" % index)
            continue
        met_raw = item.get("met", False)
        if isinstance(met_raw, str):
            met = met_raw.strip().lower() in ("1", "true", "yes", "met", "on")
        else:
            met = bool(met_raw)
        state = item.get("state")
        if isinstance(state, str) and state in CRITERIA_STATES:
            met = state == "met"
        out.append(
            {
                "criterion": _as_text(
                    item.get("criterion", item.get("criterion_text")),
                    "criteria_status[%d].criterion" % index,
                    errors,
                ),
                "met": met,
                "evidence": _as_text(
                    item.get("evidence"), "criteria_status[%d].evidence" % index, errors
                ),
            }
        )
    return out


def _normalise_lessons(value, errors):
    """Lessons are advisory extras -- a malformed one is dropped, never fatal."""
    if value is None:
        return []
    if isinstance(value, str):
        value = [{"text": value}]
    if not isinstance(value, list):
        errors.append("lessons must be a list of objects")
        return []
    out = []
    for index, item in enumerate(value):
        if isinstance(item, str):
            item = {"text": item}
        if not isinstance(item, dict):
            errors.append("lessons[%d] must be an object or string" % index)
            continue
        text = ""
        for key in ("text", "lesson", "summary", "detail"):
            if item.get(key):
                text = str(item[key]).strip()
                break
        if not text:
            errors.append("lessons[%d] has no text" % index)
            continue
        kind = item.get("kind")
        if not isinstance(kind, str) or kind not in LESSON_KINDS:
            kind = "workflow"
        scope = item.get("scope")
        if not isinstance(scope, str) or not scope.strip():
            scope = "global"
        out.append(
            {
                "text": text,
                "kind": kind,
                "scope": scope.strip(),
                "confidence": _as_confidence(
                    item.get("confidence"), "lessons[%d].confidence" % index, errors
                ),
            }
        )
    return out


# --------------------------------------------------------------------------
# Top-level normalisation
# --------------------------------------------------------------------------


def normalize_advisor(obj, expect=None):
    """Validate and normalise an advisor reply.

    ``expect`` may be ``"retrospective"`` to relax the status requirement: a
    retrospective reply carries lessons and a narrative, not a loop decision.

    Returns ``(normalised_dict, errors)``.  A non-empty errors list means the
    reply must be treated as invalid.
    """
    errors = []
    if not isinstance(obj, dict):
        return None, ["advisor reply must be a JSON object"]

    out = {}
    retrospective = expect == "retrospective"

    status = obj.get("status")
    if retrospective and status is None:
        status = "continue"
    if not isinstance(status, str) or status not in ADVISOR_STATUSES:
        errors.append(
            "status must be one of %s, got %r" % ("|".join(ADVISOR_STATUSES), status)
        )
        status = "continue"
    out["status"] = status

    out["summary"] = _as_text(obj.get("summary"), "summary", errors)
    out["assumptions"] = _str_list(obj.get("assumptions"), "assumptions", errors)
    out["questions_for_executor"] = _str_list(
        obj.get("questions_for_executor"), "questions_for_executor", errors
    )

    plan = obj.get("plan")
    plan_out = []
    if plan is None:
        plan = []
    if not isinstance(plan, list):
        errors.append("plan must be a list of step objects")
        plan = []
    for index, step in enumerate(plan):
        normalised_step = _normalise_step(step, index, errors)
        if normalised_step is not None:
            plan_out.append(normalised_step)
    out["plan"] = plan_out

    out["milestones"] = _normalise_milestones(obj.get("milestones"), errors)
    out["acceptance_criteria"] = _str_list(
        obj.get("acceptance_criteria"), "acceptance_criteria", errors
    )
    out["criteria_status"] = _normalise_criteria_status(obj.get("criteria_status"), errors)
    out["lessons"] = _normalise_lessons(obj.get("lessons"), errors)

    current = obj.get("current_milestone")
    if current is None:
        out["current_milestone"] = None
    elif isinstance(current, (str, int, float)):
        out["current_milestone"] = str(current).strip() or None
    else:
        errors.append("current_milestone must be a string, number or null")
        out["current_milestone"] = None

    review = obj.get("review")
    if review is None:
        review = {}
    if not isinstance(review, dict):
        errors.append("review must be an object with verdict/issues")
        review = {}
    verdict = review.get("verdict", "n/a")
    if not isinstance(verdict, str) or verdict not in ADVISOR_VERDICTS:
        errors.append("review.verdict must be one of %s, got %r" % ("|".join(ADVISOR_VERDICTS), verdict))
        verdict = "n/a"
    out["review"] = {
        "verdict": verdict,
        "issues": _str_list(review.get("issues"), "review.issues", errors),
        "milestone_id": _as_text(
            review.get("milestone_id"), "review.milestone_id", errors
        )
        or None,
    }

    out["next_instructions"] = _as_text(obj.get("next_instructions"), "next_instructions", errors)

    blocked_reason = obj.get("blocked_reason")
    if blocked_reason is not None and not isinstance(blocked_reason, str):
        errors.append("blocked_reason must be a string or null")
        blocked_reason = str(blocked_reason)
    if status == "blocked" and not blocked_reason:
        blocked_reason = out["summary"] or "advisor reported blocked without a reason"
    if status != "blocked":
        blocked_reason = None
    out["blocked_reason"] = blocked_reason

    return out, errors


def parse_advisor_reply(text, expect=None):
    """Extract, validate and normalise an advisor reply.  Raises on failure."""
    obj = extract_json_object(text)
    normalised, errors = normalize_advisor(obj, expect=expect)
    if errors:
        raise AdvisorParseError("advisor reply failed schema validation", errors)
    return normalised


# --------------------------------------------------------------------------
# Criteria bookkeeping (item 2)
# --------------------------------------------------------------------------


def criteria_all_met(normalised, expected=None):
    """True when the advisor has marked every acceptance criterion met.

    A reply that reports no criteria at all cannot end the loop: the advisor has
    to say, explicitly, that the criteria it set are satisfied.
    """
    status_list = normalised.get("criteria_status") or []
    if not status_list:
        return False
    expected = expected or normalised.get("acceptance_criteria") or []
    reported = {item["criterion"] for item in status_list}
    return set(expected).issubset(reported) and all(bool(item.get("met")) for item in status_list)


def criteria_outstanding(normalised, expected=None):
    """The criteria the advisor did not mark met, as display strings."""
    out = []
    for item in normalised.get("criteria_status") or []:
        if not item.get("met"):
            text = item.get("criterion") or "(unnamed criterion)"
            evidence = item.get("evidence") or ""
            out.append("%s%s" % (text, " -- %s" % evidence if evidence else ""))
    reported = {item["criterion"] for item in normalised.get("criteria_status") or []}
    out.extend("%s -- not reported" % text for text in expected or [] if text not in reported)
    return out


def milestone_ids(normalised):
    return [item["id"] for item in normalised.get("milestones") or []]


def find_milestone(normalised, milestone_id):
    for item in normalised.get("milestones") or []:
        if item["id"] == str(milestone_id):
            return item
    return None


def is_loop_end(normalised):
    """True when the advisor says done AND every acceptance criterion is met."""
    return normalised.get("status") == "done" and criteria_all_met(normalised)
