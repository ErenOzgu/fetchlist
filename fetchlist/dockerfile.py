"""Dockerfiles: base images, COPY --from, ADD from a URL, and what RUN downloads."""

from __future__ import annotations

import json
import re

from .model import PINNED, UNPINNED, UNRESOLVED, Fetch
from .shell import scan_lines
from .util import HEX40, has_variable, host_of, image_status, parse_image, substitute

_HEREDOC = re.compile(r"<<-?\s*[\"']?(\w+)[\"']?")


def instructions(text: str) -> list[tuple[int, str, str]]:
    """(first line number, KEYWORD, the rest) for each instruction; continuations and heredocs are joined."""
    lines = text.splitlines()
    out: list[tuple[int, str, str]] = []
    i = 0
    while i < len(lines):
        raw = lines[i]
        if not raw.strip() or raw.lstrip().startswith("#"):
            i += 1
            continue
        start = i + 1
        buf = raw.rstrip()
        while buf.endswith("\\") and i + 1 < len(lines):
            i += 1
            nxt = lines[i]
            if nxt.lstrip().startswith("#"):
                continue
            buf = buf[:-1] + " " + nxt.strip()
        if buf.endswith("\\"):
            buf = buf[:-1]
        keyword, _, rest = buf.strip().partition(" ")
        keyword = keyword.upper()
        heredoc = _HEREDOC.search(rest)
        if heredoc and keyword in ("RUN", "COPY", "ADD"):
            delimiter = heredoc.group(1)
            body = []
            i += 1
            while i < len(lines) and lines[i].strip() != delimiter:
                body.append(lines[i])
                i += 1
            if keyword == "RUN":
                rest = rest[: heredoc.start()].rstrip() + "\n" + "\n".join(body)
        out.append((start, keyword, rest.strip()))
        i += 1
    return out


def _flags(rest: str) -> tuple[dict[str, str], str]:
    flags: dict[str, str] = {}
    tokens = rest.split()
    while tokens and tokens[0].startswith("--"):
        name, _, value = tokens.pop(0)[2:].partition("=")
        flags[name] = value
    return flags, " ".join(tokens)


def scan_dockerfile(text: str, file: str) -> list[Fetch]:
    variables: dict[str, str | None] = {}
    stages: set[str] = set()
    out: list[Fetch] = []

    def add(number: int, ref: str) -> None:
        ref = substitute(ref, variables)
        status, why = image_status(ref)
        out.append(
            Fetch(file, number, "image", ref, status, why, "" if has_variable(ref) else parse_image(ref)[0])
        )

    for number, keyword, rest in instructions(text):
        if keyword in ("ARG", "ENV"):
            for token in rest.split():
                name, sep, value = token.partition("=")
                if sep:
                    variables[name] = value.strip("\"'") if name not in variables else variables[name]
        elif keyword == "FROM":
            flags, tail = _flags(rest)
            words = tail.split()
            if not words:
                continue
            image = words[0]
            earlier = set(stages)
            if len(words) >= 3 and words[1].upper() == "AS":
                stages.add(words[2].lower())
            if image.lower() == "scratch" or image.lower() in earlier:
                continue
            add(number, image)
        elif keyword == "COPY":
            flags, _tail = _flags(rest)
            source = flags.get("from", "")
            if source and not source.isdigit() and source.lower() not in stages:
                add(number, source)
        elif keyword == "ADD":
            flags, tail = _flags(rest)
            sources = tail.split()[:-1]
            for url in (
                s for s in sources if s.startswith(("http://", "https://", "git@")) or s.startswith("git://")
            ):
                url = substitute(url, variables)
                checksum = flags.get("checksum", "")
                ref = url.partition("#")[2]
                if has_variable(url):
                    out.append(
                        Fetch(
                            file,
                            number,
                            "url",
                            url,
                            UNRESOLVED,
                            "the URL holds a variable this file does not define",
                        )
                    )
                elif checksum.startswith("sha256:") or checksum.startswith("sha512:"):
                    out.append(Fetch(file, number, "url", url, PINNED, "ADD --checksum", host_of(url)))
                elif HEX40.fullmatch(ref):
                    out.append(Fetch(file, number, "url", url, PINNED, "pinned to a commit", host_of(url)))
                else:
                    out.append(
                        Fetch(
                            file,
                            number,
                            "url",
                            url,
                            UNPINNED,
                            "ADD from a URL without --checksum",
                            host_of(url),
                        )
                    )
        elif keyword == "RUN":
            _flags_, body = _flags(rest) if rest.startswith("--") else ({}, rest)
            if body.startswith("["):
                try:
                    body = " ".join(json.loads(body))
                except (ValueError, TypeError):
                    pass
            unit = [(number, line) for line in body.split("\n") if line.strip()]
            out.extend(scan_lines(unit, file, variables))
    return out
