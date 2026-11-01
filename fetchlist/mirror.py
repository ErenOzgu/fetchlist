"""What the build needs to reach: hosts, images, actions, packages and URLs."""

from __future__ import annotations

import json

from .model import Fetch

WHAT = ("hosts", "images", "actions", "packages", "urls")


def collect(fetches: list[Fetch]) -> dict[str, list[str]]:
    return {
        "hosts": sorted({f.host for f in fetches if f.host}),
        "images": sorted({f.ref for f in fetches if f.kind == "image"}),
        "actions": sorted({f.ref for f in fetches if f.kind == "action"}),
        "packages": sorted(
            {f"{f.ecosystem}:{f.ref}" for f in fetches if f.kind == "package" and f.status != "info"}
        ),
        "urls": sorted({f.ref for f in fetches if f.kind in ("url", "git", "include")}),
    }


def unknown_hosts(fetches: list[Fetch]) -> int:
    """Fetches whose host cannot be told (a variable in the URL, a project include)."""
    return sum(1 for f in fetches if not f.host and f.status != "info" and f.kind != "action")


def render(fetches: list[Fetch], what: str, fmt: str) -> str:
    lists = collect(fetches)
    if fmt == "json":
        return json.dumps(lists if what == "all" else {what: lists[what]}, indent=2)
    if what == "all":
        return "\n\n".join(f"# {name}\n" + "\n".join(items) for name, items in lists.items() if items)
    return "\n".join(lists[what])
