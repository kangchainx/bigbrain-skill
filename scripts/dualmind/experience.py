"""Self-evolution experience store (item 4).

Lessons the advisor learned about how this user likes to work live in a
**user-level** directory, never inside a repository or inside the skill package:

    ${DUALMIND_HOME:-$HOME/.dualmind}/experience/
        lessons.jsonl   one lesson per line
        lessons.md      a generated, human-readable digest

The location rule is enforced, not documented: :func:`resolve_store` refuses a
path that sits inside the skill package or inside the current git repository.
A lesson store that lands in the repo gets committed, shared and stale; the
whole point is that it is this user, on this machine.

This module never reads or writes any AGENTS.md, and never touches any global
Codex/Claude configuration.  See :mod:`dualmind.agents_md`.
"""

from __future__ import annotations

import difflib
import hashlib
import os
import re
import time
from pathlib import Path

from .config import (
    DEFAULT_LESSON_CAP,
    EXIT_CONFIG,
    LESSON_JACCARD_RATIO,
    LESSON_KINDS,
    LESSON_MERGE_RATIO,
    DualmindError,
    dualmind_home_dir,
    skill_root,
)
from .io import read_jsonl, write_text
from .session import is_inside

EXPERIENCE_DIRNAME = "experience"
LESSONS_JSONL = "lessons.jsonl"
LESSONS_MD = "lessons.md"

# Recency half-life for pruning: a lesson loses half its recency weight every
# this many days since it was last used.
RECENCY_HALF_LIFE_DAYS = 30.0

_WORD_RE = re.compile(r"[^a-z0-9]+")


# --------------------------------------------------------------------------
# Location guard
# --------------------------------------------------------------------------


def git_repo_root(start=None):
    """Walk up from ``start`` looking for a ``.git`` directory or file."""
    current = Path(start) if start else Path(os.getcwd())
    try:
        current = current.resolve()
    except OSError:  # pragma: no cover - defensive
        return None
    for candidate in [current, *current.parents]:
        if (candidate / ".git").exists():
            return candidate
    return None


def validate_store_dir(path, cwd=None, allow_inside_repo=False):
    """Raise when ``path`` is not a legal experience-store location.

    Refused: anywhere inside the skill package (that directory ships to other
    people) and anywhere inside the current git repository (that directory gets
    committed).  ``allow_inside_repo`` exists only so tests can exercise the
    rest of the store; normal callers never set it.
    """
    path = Path(path).expanduser()
    try:
        resolved = path.resolve()
    except OSError:  # pragma: no cover - defensive
        resolved = path

    root = skill_root()
    if is_inside(resolved, root):
        raise DualmindError(
            "refusing to use %s as the experience store: it is inside the dualmind skill "
            "package (%s), which ships to other people. Set DUALMIND_HOME to a user-level "
            "directory instead (default ~/.dualmind)." % (resolved, root),
            EXIT_CONFIG,
        )

    repo = git_repo_root(cwd or os.getcwd())
    if repo is not None and is_inside(resolved, repo) and not allow_inside_repo:
        raise DualmindError(
            "refusing to use %s as the experience store: it is inside the git repository at %s, "
            "so lessons would be committed and shared. Set DUALMIND_HOME to a user-level "
            "directory instead (default ~/.dualmind)." % (resolved, repo),
            EXIT_CONFIG,
        )
    return resolved


def resolve_store(env=None, cwd=None, allow_inside_repo=False, create=False):
    """Return the resolved experience-store directory."""
    env = os.environ if env is None else env
    raw = (env.get("DUALMIND_EXPERIENCE_DIR") or "").strip()
    base = Path(raw).expanduser() if raw else dualmind_home_dir(env) / EXPERIENCE_DIRNAME
    resolved = validate_store_dir(base, cwd=cwd, allow_inside_repo=allow_inside_repo)
    if create:
        resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def store_paths(store_dir):
    store_dir = Path(store_dir)
    return {
        "dir": store_dir,
        "jsonl": store_dir / LESSONS_JSONL,
        "markdown": store_dir / LESSONS_MD,
    }


# --------------------------------------------------------------------------
# Lesson records
# --------------------------------------------------------------------------


def _normalise_text(text):
    return " ".join(_WORD_RE.sub(" ", str(text or "").lower()).split())


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


#: How many hex characters of the normalised-text digest go into an id.  Eight
#: is ~4 billion values against a store capped in the dozens, so a collision is
#: a bug in the digest rather than a birthday problem -- and the store is checked
#: for the collision anyway (see :func:`make_lesson`).
_ID_HASH_CHARS = 8


def _text_digest(text):
    return hashlib.sha256(_normalise_text(text).encode("utf-8")).hexdigest()[:_ID_HASH_CHARS]


def make_lesson(
    text,
    kind="workflow",
    scope="global",
    confidence=0.6,
    session=None,
    lesson_id=None,
    existing_ids=None,
):
    """Build one lesson record.

    The id is ``l<timestamp>-<digest>``: the timestamp alone is *not* unique,
    because two lessons recorded in the same second -- which is exactly what a
    single retrospective reply produces -- collide on it and make one
    unaddressable by ``mark_used``.  The digest is of the normalised text, so two
    lessons in the same second get different ids simply by saying different
    things.

    ``existing_ids`` is the set of ids already in the store.  When the generated
    id is in it, the digest is extended, and an ordinal is appended as a last
    resort, so a caller that passes the store's ids can never write a duplicate
    id even in a pathological case.
    """
    text = " ".join(str(text or "").split())
    if not text:
        raise DualmindError("a lesson needs non-empty text", EXIT_CONFIG)
    if kind not in LESSON_KINDS:
        kind = "workflow"
    try:
        confidence = max(0.0, min(1.0, float(confidence)))
    except (TypeError, ValueError):
        confidence = 0.6
    now = _now()

    if not lesson_id:
        stamp = time.strftime("%y%m%d%H%M%S")
        digest = _text_digest(text)
        campaign = hashlib.sha256(_normalise_text(text).encode("utf-8")).hexdigest()
        lesson_id = "l%s-%s" % (stamp, digest)
        if existing_ids is not None:
            extra = _ID_HASH_CHARS
            ordinal = 1
            while lesson_id in existing_ids:
                if extra < len(campaign):
                    extra += 4
                    lesson_id = "l%s-%s" % (stamp, campaign[:extra])
                else:
                    lesson_id = "l%s-%s-%d" % (stamp, campaign[:extra], ordinal)
                    ordinal += 1

    return {
        "id": lesson_id,
        "text": text,
        "kind": kind,
        "source_session": str(session) if session else None,
        "scope": scope or "global",
        "confidence": round(confidence, 3),
        "created_at": now,
        "last_used_at": now,
        "uses": 0,
    }


def similarity(left, right):
    """Similarity of two lesson texts, 0..1, on normalised word content."""
    a = _normalise_text(left)
    b = _normalise_text(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def jaccard(left, right):
    """Token-set Jaccard similarity of two lesson texts, 0..1.

    ``similarity`` compares character sequences, so it under-scores the common
    duplicate: the same lesson twice, once with the clauses reordered and once
    with a sentence appended, can fall below the merge ratio while plainly being
    one lesson.  Comparing the *sets* of words is order- and length-insensitive,
    which is what that case needs.
    """
    a = set(_normalise_text(left).split())
    b = set(_normalise_text(right).split())
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return len(a & b) / float(len(a | b))


def load_lessons(store_dir):
    paths = store_paths(store_dir)
    out = []
    for item in read_jsonl(paths["jsonl"]):
        if not isinstance(item, dict) or not str(item.get("text") or "").strip():
            continue
        item.setdefault("kind", "workflow")
        if item["kind"] not in LESSON_KINDS:
            item["kind"] = "workflow"
        item.setdefault("scope", "global")
        item.setdefault("confidence", 0.5)
        item.setdefault("uses", 0)
        item.setdefault("created_at", _now())
        item.setdefault("last_used_at", item["created_at"])
        out.append(item)
    return out


def save_lessons(store_dir, lessons):
    """Rewrite the JSONL file and regenerate the Markdown digest."""
    paths = store_paths(store_dir)
    store_dir = Path(store_dir)
    store_dir.mkdir(parents=True, exist_ok=True)
    lines = []
    for lesson in lessons:
        import json

        lines.append(json.dumps(lesson, ensure_ascii=False, sort_keys=True))
    write_text(paths["jsonl"], "\n".join(lines) + ("\n" if lines else ""))
    write_text(paths["markdown"], render_markdown(lessons))
    return paths["jsonl"]


def match_lesson(existing, candidate, merge_ratio=LESSON_MERGE_RATIO,
                 jaccard_ratio=LESSON_JACCARD_RATIO):
    """Find the existing lesson ``candidate`` duplicates, or ``None``.

    Two independent tests, either of which is enough:

    * **wording** -- difflib similarity >= ``merge_ratio``, compared within the
      same ``scope`` (a lesson is scoped to a project; the same sentence in two
      scopes is two lessons).
    * **token set** -- Jaccard >= ``jaccard_ratio``, compared within the same
      ``kind`` (an executor-weakness lesson and a workflow lesson that share
      vocabulary are still different lessons).

    Returns the best-matching record so a caller can merge into it.
    """
    best = None
    best_score = 0.0
    for item in existing or []:
        score = 0.0
        if str(item.get("scope")) == str(candidate.get("scope")):
            score = max(score, similarity(item.get("text"), candidate.get("text")))
        if str(item.get("kind")) == str(candidate.get("kind")):
            score = max(score, jaccard(item.get("text"), candidate.get("text")))
        if score > best_score:
            best, best_score = item, score

    if best is None:
        return None
    same_scope = str(best.get("scope")) == str(candidate.get("scope"))
    same_kind = str(best.get("kind")) == str(candidate.get("kind"))
    if same_scope and similarity(best.get("text"), candidate.get("text")) >= merge_ratio:
        return best
    if same_kind and jaccard(best.get("text"), candidate.get("text")) >= jaccard_ratio:
        return best
    return None


def add_lessons(store_dir, new_lessons, cap=DEFAULT_LESSON_CAP, merge_ratio=LESSON_MERGE_RATIO,
                jaccard_ratio=LESSON_JACCARD_RATIO):
    """Merge ``new_lessons`` into the store.

    A lesson that duplicates an existing one (see :func:`match_lesson`) merges
    into it: confidence is bumped, the id and creation time are kept, and the
    newer wording wins when it is longer.  Everything else is appended with a
    freshly minted id, unique against the ids already in the store.

    Returns a summary dict with ``added``, ``merged``, ``total`` and ``pruned``.
    """
    store_dir = Path(store_dir)
    existing = load_lessons(store_dir)
    used_ids = {str(item.get("id")) for item in existing if item.get("id")}
    added = 0
    merged = 0

    for lesson in new_lessons or []:
        candidate = dict(lesson)
        candidate.setdefault("kind", "workflow")
        candidate.setdefault("scope", "global")
        # Re-mint the id against everything already present: a caller that built
        # its records in one batch (cli._save_reply_lessons does) hands over
        # timestamp-derived ids that can collide with the store or each other.
        if not candidate.get("id") or str(candidate.get("id")) in used_ids:
            candidate["id"] = make_lesson(
                candidate.get("text") or "",
                kind=candidate.get("kind"),
                scope=candidate.get("scope"),
                confidence=candidate.get("confidence"),
                session=candidate.get("source_session"),
                existing_ids=used_ids,
            )["id"]

        best = match_lesson(existing, candidate, merge_ratio, jaccard_ratio)
        if best is not None:
            used_ids.discard(str(candidate.get("id")))
            best["confidence"] = round(
                min(1.0, max(float(best.get("confidence") or 0.0), float(candidate.get("confidence") or 0.0)) + 0.1),
                3,
            )
            if len(str(candidate.get("text") or "")) > len(str(best.get("text") or "")):
                best["text"] = candidate["text"]
            if candidate.get("kind") and not best.get("kind"):
                best["kind"] = candidate["kind"]
            best["last_used_at"] = _now()
            merged += 1
        else:
            existing.append(candidate)
            used_ids.add(str(candidate.get("id")))
            added += 1

    pruned = []
    if cap and len(existing) > cap:
        existing, pruned = prune_lessons(existing, cap=cap)

    save_lessons(store_dir, existing)
    return {"added": added, "merged": merged, "total": len(existing), "pruned": len(pruned)}


# --------------------------------------------------------------------------
# Pruning and ranking
# --------------------------------------------------------------------------


def _age_days(stamp, reference=None):
    reference = reference or time.time()
    try:
        parsed = time.mktime(time.strptime(str(stamp)[:19], "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, TypeError):
        return 0.0
    return max(0.0, (reference - parsed) / 86400.0)


def lesson_rank(lesson, reference=None):
    """confidence * recency, where recency halves every RECENCY_HALF_LIFE_DAYS."""
    confidence = float(lesson.get("confidence") or 0.0)
    days = _age_days(lesson.get("last_used_at") or lesson.get("created_at"), reference)
    recency = 0.5 ** (days / RECENCY_HALF_LIFE_DAYS)
    return confidence * recency


def prune_lessons(lessons, cap=DEFAULT_LESSON_CAP, reference=None):
    """Keep the ``cap`` best lessons by confidence*recency.

    Returns ``(kept, dropped)``.
    """
    if not cap or len(lessons) <= cap:
        return list(lessons), []
    ranked = sorted(lessons, key=lambda item: lesson_rank(item, reference), reverse=True)
    kept = ranked[:cap]
    dropped = ranked[cap:]
    return kept, dropped


def select_lessons(lessons, limit=8, scope=None, min_confidence=0.0):
    """Top ``limit`` lessons by rank, optionally filtered by scope."""
    candidates = []
    for item in lessons or []:
        if scope is not None and str(item.get("scope")) != str(scope):
            continue
        if float(item.get("confidence") or 0.0) < min_confidence:
            continue
        candidates.append(item)
    candidates.sort(key=lesson_rank, reverse=True)
    return candidates[:limit] if limit else candidates


def mark_used(lessons, used_ids, when=None):
    """Record that lessons were injected into a request."""
    stamp = when or _now()
    used = {str(item) for item in (used_ids or [])}
    changed = 0
    for lesson in lessons or []:
        if str(lesson.get("id")) in used:
            lesson["uses"] = int(lesson.get("uses") or 0) + 1
            lesson["last_used_at"] = stamp
            changed += 1
    return changed


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


def render_markdown(lessons):
    """Generate the human-readable digest, grouped by kind."""
    lines = [
        "# dualmind lessons",
        "",
        "Generated file -- edit `lessons.jsonl` or use `dualmind_cli.py lessons` instead.",
        "",
        "Scope: this machine and user only. These lessons are injected into advisor",
        "requests while the dualmind skill is active; they do not modify any AGENTS.md",
        "or any global Codex/Claude configuration.",
        "",
        "Total: %d" % len(lessons),
        "",
    ]
    if not lessons:
        lines.append("_(no lessons recorded yet)_")
        lines.append("")
        return "\n".join(lines)

    for kind in LESSON_KINDS:
        group = [item for item in lessons if item.get("kind") == kind]
        if not group:
            continue
        lines.append("## %s (%d)" % (kind, len(group)))
        lines.append("")
        for item in sorted(group, key=lesson_rank, reverse=True):
            lines.append(
                "- %s  \n  `%s` scope=%s confidence=%.2f uses=%d"
                % (
                    item.get("text", ""),
                    item.get("id", "?"),
                    item.get("scope", "global"),
                    float(item.get("confidence") or 0.0),
                    int(item.get("uses") or 0),
                )
            )
        lines.append("")
    other = [item for item in lessons if item.get("kind") not in LESSON_KINDS]
    if other:
        lines.append("## other (%d)" % len(other))
        lines.append("")
        for item in other:
            lines.append("- %s" % item.get("text", ""))
        lines.append("")
    return "\n".join(lines)


def store_summary(store_dir):
    lessons = load_lessons(store_dir)
    by_kind = {}
    for item in lessons:
        by_kind[item.get("kind", "workflow")] = by_kind.get(item.get("kind", "workflow"), 0) + 1
    return {
        "dir": str(store_dir),
        "total": len(lessons),
        "by_kind": by_kind,
        "jsonl": str(store_paths(store_dir)["jsonl"]),
        "markdown": str(store_paths(store_dir)["markdown"]),
    }


__all__ = [
    "EXPERIENCE_DIRNAME",
    "LESSONS_JSONL",
    "LESSONS_MD",
    "add_lessons",
    "git_repo_root",
    "lesson_rank",
    "load_lessons",
    "make_lesson",
    "mark_used",
    "prune_lessons",
    "render_markdown",
    "resolve_store",
    "save_lessons",
    "select_lessons",
    "similarity",
    "store_paths",
    "store_summary",
    "validate_store_dir",
]
