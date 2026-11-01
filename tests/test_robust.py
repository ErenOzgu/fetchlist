"""Whatever a build file looks like, the scanners return findings that point at a real line, or say they refuse it."""

import random
from pathlib import Path

import pytest

from fetchlist.discover import _scan, classify
from fetchlist.model import KINDS, STATUSES
from fetchlist.pom import Refused

SAMPLE = Path(__file__).parent.parent / "examples" / "sample"
FILES = sorted(p for p in SAMPLE.rglob("*") if p.is_file() and classify(p.relative_to(SAMPLE).as_posix()))
JUNK = [
    "\\",
    "'",
    '"',
    "${",
    "$(",
    "|",
    "&&",
    "<<EOF",
    "  - ",
    ": |",
    "\t",
    "@",
    "sha256:",
    "\x00",
    "https://",
    "- ",
]


def mutate(text: str, rng: random.Random) -> str:
    lines = text.splitlines()
    for _ in range(rng.randint(1, 4)):
        op = rng.choice(["drop", "dup", "cut", "junk", "swap"])
        if not lines:
            break
        i = rng.randrange(len(lines))
        if op == "drop":
            del lines[i]
        elif op == "dup":
            lines.insert(i, lines[i])
        elif op == "cut":
            lines[i] = lines[i][: rng.randrange(len(lines[i]) + 1)]
        elif op == "junk":
            j = rng.randrange(len(lines[i]) + 1)
            lines[i] = lines[i][:j] + rng.choice(JUNK) + lines[i][j:]
        else:
            k = rng.randrange(len(lines))
            lines[i], lines[k] = lines[k], lines[i]
    return "\n".join(lines) + "\n"


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.relative_to(SAMPLE).as_posix())
def test_mutated_files_never_crash_and_findings_point_at_real_lines(path):
    rel = path.relative_to(SAMPLE).as_posix()
    kind = classify(rel)
    original = path.read_text(encoding="utf-8")
    rng = random.Random(f"fetchlist:{rel}")
    for _ in range(300):
        text = mutate(original, rng)
        total = len(text.splitlines()) + 1
        try:
            found = _scan(kind, text, rel)
        except Refused:
            continue
        for f in found:
            assert f.status in STATUSES and f.kind in KINDS, f
            assert 1 <= f.line <= total, (f, text)
            assert f.file == rel and f.ref, f


def test_binary_noise_does_not_crash():
    rng = random.Random(7)
    for kind in ("dockerfile", "workflow", "gitlab", "compose", "requirements", "script", "make"):
        for _ in range(50):
            text = "".join(chr(rng.randrange(1, 256)) for _ in range(rng.randrange(0, 400)))
            _scan(kind, text, "x")
