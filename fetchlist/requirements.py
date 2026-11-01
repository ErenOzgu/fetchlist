"""pip requirements and constraints files."""

from __future__ import annotations

import re

from .model import INFO, PINNED, UNPINNED, Fetch
from .util import HEX40, host_of

_NAME = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)(?P<extras>\[[^\]]*\])?\s*(?P<spec>[^;@]*)(?:@\s*(?P<url>\S+))?"
)


def _logical(text: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    buf, start = "", 0
    for number, raw in enumerate(text.splitlines(), start=1):
        line = re.sub(r"(?:^|\s)#.*$", "", raw).rstrip()
        if not buf:
            start = number
        if line.endswith("\\"):
            buf += line[:-1] + " "
            continue
        full = (buf + line).strip()
        buf = ""
        if full:
            out.append((start, full))
    return out


def scan_requirements(text: str, file: str) -> list[Fetch]:
    entries = _logical(text)
    hashed_file = any(line.startswith("--require-hashes") for _, line in entries)
    out: list[Fetch] = []
    host = "pypi.org"
    for number, line in entries:
        if line.startswith(("-i ", "--index-url", "--extra-index-url", "-f ", "--find-links")):
            value = re.split(r"[\s=]+", line, maxsplit=1)[1].strip() if re.search(r"[\s=]", line) else ""
            if line.startswith(("-i ", "--index-url")) and host_of(value):
                host = host_of(value)
            out.append(
                Fetch(
                    file,
                    number,
                    "package",
                    value,
                    INFO,
                    "an index this file installs from",
                    host_of(value),
                    "pip",
                )
            )
            continue
        if line.startswith(("-e ", "--editable ")):
            line = line.split(None, 1)[1]
        spec = line.split(" --hash")[0].strip()
        hashed = " --hash=" in f" {line}" or hashed_file
        if spec.startswith(("git+", "hg+", "svn+", "bzr+")):
            ok = bool(HEX40.fullmatch(spec.split("#")[0].rsplit("@", 1)[-1])) if "@" in spec else False
            out.append(
                Fetch(
                    file,
                    number,
                    "package",
                    spec,
                    PINNED if ok else UNPINNED,
                    "pinned to a commit" if ok else "a branch or tag can move",
                    host_of(spec[4:]),
                    "pip",
                )
            )
            continue
        if spec.startswith(("http://", "https://")):
            ok = "#sha256=" in spec or hashed
            out.append(
                Fetch(
                    file,
                    number,
                    "package",
                    spec,
                    PINNED if ok else UNPINNED,
                    "the URL carries its sha256" if ok else "no #sha256= on the URL",
                    host_of(spec),
                    "pip",
                )
            )
            continue
        m = _NAME.match(spec)
        if not m:
            continue
        name = m.group("name") + (m.group("extras") or "")
        version = (m.group("spec") or "").strip()
        shown = f"{name}{version}" if version else name
        if m.group("url"):
            url = m.group("url")
            ok = HEX40.fullmatch(url.split("#")[0].rsplit("@", 1)[-1]) is not None or "#sha256=" in url
            out.append(
                Fetch(
                    file,
                    number,
                    "package",
                    f"{name} @ {url}",
                    PINNED if ok else UNPINNED,
                    "pinned to a commit or a hash" if ok else "a direct reference that can move",
                    host_of(url[4:] if url.startswith("git+") else url),
                    "pip",
                )
            )
        elif hashed:
            out.append(Fetch(file, number, "package", shown, PINNED, "installed with hashes", host, "pip"))
        elif re.fullmatch(r"(?:===|==)\s*[^=*\s,]+", version):
            out.append(Fetch(file, number, "package", shown, PINNED, "exact version", host, "pip"))
        else:
            why = "any version matches" if not version else f"'{version}' is a range, not one version"
            out.append(Fetch(file, number, "package", shown, UNPINNED, why, host, "pip"))
    return out
