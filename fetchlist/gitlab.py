"""GitLab CI files: images, services, includes and scripts."""

from __future__ import annotations

import re

from .model import PINNED, UNPINNED, UNRESOLVED, Fetch
from .shell import logical_lines, scan_lines
from .util import HEX40, collect_vars, has_variable, host_of, image_status, parse_image, substitute, unquote
from .yamlish import ancestors, indent_of, list_items, parse_key

_SCRIPT_KEYS = {"script", "before_script", "after_script"}


def _image(file: str, line: int, ref: str, variables: dict[str, str | None]) -> Fetch:
    ref = substitute(ref, variables)
    status, why = image_status(ref)
    return Fetch(file, line, "image", ref, status, why, "" if has_variable(ref) else parse_image(ref)[0])


def scan_gitlab(text: str, file: str) -> list[Fetch]:
    lines = text.splitlines()
    variables = collect_vars(text, yaml=True)
    out: list[Fetch] = []
    for i, raw in enumerate(lines):
        parsed = parse_key(raw)
        if not parsed:
            continue
        col, key, value = parsed
        enclosing = ancestors(lines, i)
        if key == "image" and value and not value.startswith("{"):
            out.append(_image(file, i + 1, unquote(value), variables))
        elif key == "name" and value and enclosing and enclosing[-1] in ("image", "services"):
            out.append(_image(file, i + 1, unquote(value), variables))
        elif key == "services" and not value:
            for item in list_items(lines, i, col):
                text_item = item[0][1].strip()
                if not parse_key(text_item) and text_item:
                    out.append(_image(file, item[0][0], unquote(text_item), variables))
        elif key in _SCRIPT_KEYS and not value:
            unit = [
                pair
                for item in list_items(lines, i, col)
                for pair in logical_lines("\n".join(t for _, t in item), item[0][0])
            ]
            out.extend(scan_lines(unit, file, variables))
        elif key == "include":
            out.extend(_includes(lines, i, col, value, file, variables))
    return out


def _include_fetch(file: str, entry: dict[str, tuple[int, str]]) -> Fetch | None:
    if "remote" in entry:
        number, url = entry["remote"]
        if has_variable(url):
            return Fetch(file, number, "include", url, UNRESOLVED, "the URL holds a variable", host_of(url))
        if re.search(r"/[0-9a-f]{40}(?:/|$)", url):
            return Fetch(file, number, "include", url, PINNED, "the URL names a commit", host_of(url))
        return Fetch(file, number, "include", url, UNPINNED, "the file at this URL can change", host_of(url))
    if "project" in entry:
        number, project = entry["project"]
        ref = entry.get("ref", (number, ""))[1]
        shown = f"{project}@{ref}" if ref else project
        if HEX40.fullmatch(ref):
            return Fetch(file, number, "include", shown, PINNED, "pinned to a commit")
        why = f"{ref} is a branch or tag and can move" if ref else "no ref, so the default branch is used"
        return Fetch(file, number, "include", shown, UNPINNED, why)
    if "template" in entry:
        number, name = entry["template"]
        return Fetch(
            file,
            number,
            "include",
            f"template:{name}",
            UNPINNED,
            "GitLab's own templates change with GitLab",
            "",
        )
    if "component" in entry:
        number, component = entry["component"]
        version = component.rpartition("@")[2] if "@" in component else ""
        if HEX40.fullmatch(version):
            return Fetch(
                file,
                number,
                "include",
                component,
                PINNED,
                "pinned to a commit",
                host_of("https://" + component),
            )
        why = f"@{version} can move" if version else "no version"
        return Fetch(file, number, "include", component, UNPINNED, why, host_of("https://" + component))
    return None


def _includes(
    lines: list[str], i: int, col: int, value: str, file: str, variables: dict[str, str | None]
) -> list[Fetch]:
    if value:
        url = substitute(unquote(value), variables)
        if url.startswith("http"):
            fetch = _include_fetch(file, {"remote": (i + 1, url)})
            return [fetch] if fetch else []
        return []
    out: list[Fetch] = []
    entry: dict[str, tuple[int, str]] = {}
    j = i + 1
    while j < len(lines):
        raw = lines[j]
        stripped = raw.strip()
        if (
            stripped
            and not stripped.startswith("#")
            and indent_of(raw) <= col
            and not stripped.startswith("-")
        ):
            break
        parsed = parse_key(raw)
        if stripped.startswith("- ") and entry:
            fetch = _include_fetch(file, entry)
            if fetch:
                out.append(fetch)
            entry = {}
        if parsed:
            entry[parsed[1]] = (j + 1, substitute(unquote(parsed[2]), variables))
        j += 1
    fetch = _include_fetch(file, entry) if entry else None
    if fetch:
        out.append(fetch)
    return out
