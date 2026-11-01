"""Text, JSON, Markdown and GitHub-annotation output."""

from __future__ import annotations

import json
from collections import Counter

from . import __version__
from .model import INFO, PINNED, STATUSES, UNPINNED, UNRESOLVED, VERIFIED, Fetch, Skip


def summary_counts(fetches: list[Fetch]) -> dict[str, int]:
    counts = Counter(f.status for f in fetches)
    return {status: counts.get(status, 0) for status in STATUSES}


def summary_line(fetches: list[Fetch]) -> str:
    counts = summary_counts(fetches)
    files = len({f.file for f in fetches})
    graded = [f for f in fetches if f.status != INFO]
    parts = [f"{counts[s]} {s}" for s in (PINNED, VERIFIED, UNPINNED, UNRESOLVED) if counts[s]]
    allowed = sum(1 for f in fetches if f.allowed)
    line = f"{len(graded)} fetches in {files} files: " + (", ".join(parts) if parts else "nothing to grade")
    return line + (f" ({allowed} allowed)" if allowed else "")


def text(fetches: list[Fetch], *, only: set[str] | None = None) -> str:
    rows = [f for f in fetches if only is None or f.status in only]
    out: list[str] = []
    current = None
    for f in rows:
        if f.file != current:
            current = f.file
            out.append(current)
        out.append(f"  {f.line:>4}  {f.kind:<7} {f.status.upper():<10} {f.ref}")
        if f.status != PINNED:
            note = f"allowed: {f.allowed}" if f.allowed else f.why
            out.append(" " * 29 + note)
    return "\n".join(out)


def markdown(fetches: list[Fetch]) -> str:
    out = ["| Where | Kind | Status | What | Why |", "|---|---|---|---|---|"]
    for f in fetches:
        ref = f.ref.replace("|", "\\|")
        out.append(
            f"| `{f.file}:{f.line}` | {f.kind} | {f.status} | `{ref}` | {f.allowed and 'allowed: ' + f.allowed or f.why} |"
        )
    return "\n".join(out)


def as_json(fetches: list[Fetch], skips: list[Skip]) -> str:
    document = {
        "fetchlist": __version__,
        "summary": summary_counts(fetches),
        "fetches": [f.to_dict() for f in fetches],
        "skipped": [s.to_dict() for s in skips],
    }
    return json.dumps(document, indent=2, ensure_ascii=False)


def github(fetches: list[Fetch]) -> str:
    out = []
    for f in fetches:
        level = "error" if f.status == UNPINNED else "warning"
        message = f"{f.kind} {f.ref}: {f.why}".replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        out.append(f"::{level} file={f.file},line={f.line},title=fetchlist {f.status}::{message}")
    return "\n".join(out)
