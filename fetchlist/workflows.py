"""GitHub Actions workflows, composite actions and Compose files."""

from __future__ import annotations

import re

from .model import PINNED, UNPINNED, UNRESOLVED, Fetch
from .shell import logical_lines, scan_lines
from .util import HEX40, collect_vars, has_variable, image_status, parse_image, substitute, unquote
from .yamlish import ancestors, block_scalar, is_block, parse_key


def _action(file: str, line: int, ref: str) -> Fetch:
    if has_variable(ref):
        return Fetch(
            file,
            line,
            "action",
            ref,
            UNRESOLVED,
            "the reference holds an expression that is only known at run time",
            "github.com",
        )
    if ref.startswith("docker://"):
        image = ref[len("docker://") :]
        status, why = image_status(image)
        return Fetch(file, line, "image", image, status, why, parse_image(image)[0])
    if ref.startswith("./") or ref == ".":
        raise ValueError("local action")
    name, _, version = ref.partition("@")
    if not version:
        return Fetch(
            file, line, "action", ref, UNPINNED, "no @ref, so the default branch is used", "github.com"
        )
    if HEX40.fullmatch(version):
        return Fetch(file, line, "action", ref, PINNED, "pinned to a commit", "github.com")
    if re.fullmatch(r"v?\d+(?:\.\d+){0,2}", version):
        why = f"the tag {version} can be moved to another commit"
    elif version in ("main", "master", "HEAD", "develop", "trunk"):
        why = f"{version} is a branch and changes with every push"
    else:
        why = f"{version} is a tag or branch and can move"
    return Fetch(file, line, "action", ref, UNPINNED, why, "github.com")


def scan_workflow(text: str, file: str) -> list[Fetch]:
    lines = text.splitlines()
    variables = collect_vars(text, yaml=True)
    out: list[Fetch] = []
    i = 0
    while i < len(lines):
        parsed = parse_key(lines[i])
        if not parsed:
            i += 1
            continue
        col, key, value = parsed
        if key == "uses" and value:
            ref = substitute(unquote(value), variables)
            try:
                out.append(_action(file, i + 1, ref))
            except ValueError:
                pass
        elif key == "run" and value:
            if is_block(value):
                body, nxt = block_scalar(lines, i, col)
                out.extend(
                    scan_lines(
                        logical_lines("\n".join(t for _, t in body), body[0][0] if body else i + 2),
                        file,
                        variables,
                    )
                )
                i = nxt
                continue
            out.extend(scan_lines(logical_lines(unquote(value), i + 1), file, variables))
        elif key == "container" and value and not is_block(value):
            out.append(_image(file, i + 1, unquote(value), variables))
        elif key == "image" and value:
            enclosing = ancestors(lines, i)
            if "container" in enclosing or "services" in enclosing or unquote(value).startswith("docker://"):
                ref = unquote(value)
                if ref.startswith("docker://"):
                    ref = ref[len("docker://") :]
                out.append(_image(file, i + 1, ref, variables))
        i += 1
    return out


def _image(file: str, line: int, ref: str, variables: dict[str, str | None]) -> Fetch:
    ref = substitute(ref, variables)
    status, why = image_status(ref)
    return Fetch(file, line, "image", ref, status, why, "" if has_variable(ref) else parse_image(ref)[0])


def _service_builds(lines: list[str], i: int, col: int) -> bool:
    """True when the mapping that holds line i (a service) also has a `build` key at the same column."""

    def inside(line: str) -> bool:
        return not line.strip() or line.lstrip().startswith("#") or len(line) - len(line.lstrip(" ")) >= col

    first = i
    while first > 0 and inside(lines[first - 1]):
        first -= 1
    last = i
    while last + 1 < len(lines) and inside(lines[last + 1]):
        last += 1
    for line in lines[first : last + 1]:
        parsed = parse_key(line)
        if parsed and parsed[0] == col and parsed[1] == "build":
            return True
    return False


def scan_compose(text: str, file: str) -> list[Fetch]:
    """Images named in a Compose file. A service that also has `build` makes its image here: `image` is only the
    name it is given, so it is not a download (unless the file sets `pull_policy`, which this does not read)."""
    lines = text.splitlines()
    variables = collect_vars(text, yaml=True)
    out: list[Fetch] = []
    for i, line in enumerate(lines):
        parsed = parse_key(line)
        if parsed and parsed[1] == "image" and parsed[2] and not _service_builds(lines, i, parsed[0]):
            out.append(_image(file, i + 1, unquote(parsed[2]), variables))
    return out
