"""Just enough of YAML to read CI files by line, without a YAML library.

A CI file is read as lines: a key, its value and the keys that enclose it (found by indentation). That is enough to
find `uses:`, `image:`, `run:` and `script:`. It is not a YAML parser: anchors, flow mappings (`{a: b}`), merge keys
and multi-document files are not understood, and the README says so.
"""

from __future__ import annotations

import re

from .util import unquote

_KEY = re.compile(
    r"""^(?P<indent>\s*)(?P<dash>-\s+)?(?P<key>[A-Za-z_.][\w.\-]*|"[^"]+"|'[^']+')\s*:(?:\s+(?P<value>.*))?$"""
)
_BLOCK = re.compile(r"^[|>][+\-0-9]*(?:\s+#.*)?$")


def parse_key(line: str) -> tuple[int, str, str] | None:
    """(column of the key, key, value) of a `key: value` line, or None. A `- ` before the key counts to the column."""
    m = _KEY.match(line.rstrip())
    if not m:
        return None
    col = len(m.group("indent")) + (len(m.group("dash")) if m.group("dash") else 0)
    return col, m.group("key").strip("\"'"), (m.group("value") or "").strip()


def is_block(value: str) -> bool:
    return bool(_BLOCK.match(value))


def indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def block_scalar(lines: list[str], i: int, key_col: int) -> tuple[list[tuple[int, str]], int]:
    """The body of a `|` or `>` block after line i: [(line number, text)], and the index of the next line."""
    body: list[tuple[int, str]] = []
    j = i + 1
    while j < len(lines):
        line = lines[j]
        if line.strip() and indent_of(line) <= key_col:
            break
        body.append((j + 1, line))
        j += 1
    return body, j


def ancestors(lines: list[str], i: int) -> list[str]:
    """The keys that enclose line i, outermost first."""
    first = parse_key(lines[i])
    want = first[0] if first else indent_of(lines[i])
    out: list[str] = []
    for j in range(i - 1, -1, -1):
        key = parse_key(lines[j])
        if key and key[0] < want:
            out.append(key[1])
            want = key[0]
            if want == 0:
                break
    return out[::-1]


def list_items(lines: list[str], i: int, key_col: int) -> list[list[tuple[int, str]]]:
    """The `- item` entries under the key on line i. Each is a list of (line number, text): one line for a plain
    item, several for a block scalar."""
    items: list[list[tuple[int, str]]] = []
    j = i + 1
    while j < len(lines):
        line = lines[j]
        if not line.strip() or line.lstrip().startswith("#"):
            j += 1
            continue
        indent = indent_of(line)
        stripped = line.strip()
        if not stripped.startswith("- ") and stripped != "-":
            if indent <= key_col:
                break
            j += 1
            continue
        if indent < key_col:
            break
        text = stripped[2:].strip()
        if is_block(text):
            body, j = block_scalar(lines, j, indent)
            items.append([(n, t) for n, t in body])
            continue
        items.append(
            [(j + 1, unquote(text) if text[:1] in ("'", '"') else re.split(r"\s+#", text, maxsplit=1)[0])]
        )
        j += 1
    return items
