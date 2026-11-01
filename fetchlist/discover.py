"""Find the files that say what a build downloads, and read each with the right scanner."""

from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path

from .dockerfile import scan_dockerfile
from .gitlab import scan_gitlab
from .model import Fetch, Skip
from .pom import Refused, scan_pom
from .requirements import scan_requirements
from .shell import paragraphs, scan_lines
from .util import collect_vars
from .workflows import scan_compose, scan_workflow

SKIP_DIRS = {".git", "node_modules", "target", ".venv", "venv", "__pycache__", ".tox", "site-packages"}
MAX_BYTES = 2_000_000
# Dockerfile.dev is a Dockerfile; dockerfile.py is a module that happens to start with the same word.
NOT_DOCKERFILE = {
    "py",
    "md",
    "txt",
    "json",
    "yml",
    "yaml",
    "js",
    "ts",
    "go",
    "rs",
    "sh",
    "toml",
    "cfg",
    "ini",
    "xml",
}
NOT_DOCKERFILE |= {"html", "rb", "java", "c", "h", "cpp", "lock", "pyc"}

_REQUIREMENTS = re.compile(r"^(?:requirements|constraints)(?:[-_.][\w.-]*)?\.(?:txt|in)$")
_COMPOSE = re.compile(r"^(?:docker-)?compose(?:\.[\w.-]+)?\.ya?ml$")


def classify(rel: str) -> str:
    """Which scanner reads the file at this relative path, or "" if none does."""
    parts = rel.split("/")
    name = parts[-1]
    lower = name.lower()
    if lower in ("dockerfile", "containerfile") or lower.endswith(".dockerfile"):
        return "dockerfile"
    if lower.startswith(("dockerfile.", "containerfile.")) and lower.rsplit(".", 1)[-1] not in NOT_DOCKERFILE:
        return "dockerfile"
    if name.endswith((".yml", ".yaml")):
        if (
            len(parts) >= 3
            and parts[-3:-1] == [".github", "workflows"]
            or rel.startswith(".github/workflows/")
        ):
            return "workflow"
        if name in ("action.yml", "action.yaml"):
            return "workflow"
        if name == ".gitlab-ci.yml" or name.endswith(".gitlab-ci.yml") or ".gitlab/ci/" in rel:
            return "gitlab"
        if _COMPOSE.match(name):
            return "compose"
    if name == ".gitlab-ci.yaml":
        return "gitlab"
    if name.endswith((".sh", ".bash")):
        return "script"
    if lower in ("makefile", "gnumakefile") or name.endswith(".mk"):
        return "make"
    if _REQUIREMENTS.match(name):
        return "requirements"
    if name == "pom.xml":
        return "pom"
    return ""


def walk(root: Path, exclude: list[str]) -> list[str]:
    """Relative paths of every file under root, in a stable order; directories in SKIP_DIRS are not entered."""
    found: list[str] = []
    for current, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(files):
            full = Path(current) / name
            rel = full.relative_to(root).as_posix()
            if full.is_symlink() or any(fnmatch.fnmatchcase(rel, pattern) for pattern in exclude):
                continue
            found.append(rel)
    return found


def analyse(root: Path, exclude: list[str] | None = None) -> tuple[list[Fetch], list[Skip]]:
    fetches: list[Fetch] = []
    skips: list[Skip] = []
    for rel in walk(root, exclude or []):
        kind = classify(rel)
        if not kind:
            continue
        path = root / rel
        try:
            if path.stat().st_size > MAX_BYTES:
                skips.append(Skip(rel, f"larger than {MAX_BYTES} bytes"))
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            skips.append(Skip(rel, f"cannot be read: {exc.strerror or exc}"))
            continue
        try:
            fetches.extend(_scan(kind, text, rel))
        except Refused as exc:
            skips.append(Skip(rel, str(exc)))
    fetches.sort(key=lambda f: (f.file, f.line, f.kind, f.ref))
    return fetches, skips


_LOCAL_BUILD = re.compile(
    r"\b(?:docker|podman)\s+(?:buildx\s+)?build\b[^\n]*?(?:\s-t|\s--tag)[ =]\s*[\"']?([^\s\"']+)"
)
_KIND_LOAD = re.compile(r"\bkind\s+load\s+docker-image\s+[\"']?([^\s\"']+)")


def local_images(text: str) -> set[str]:
    """Images the same file builds itself (docker build -t NAME), so that running them is not a download."""
    return {m.group(1) for m in _LOCAL_BUILD.finditer(text)} | {m.group(1) for m in _KIND_LOAD.finditer(text)}


def _scan(kind: str, text: str, rel: str) -> list[Fetch]:
    found = _scan_kind(kind, text, rel)
    if kind in ("pom", "requirements"):
        return found
    built = local_images(text)
    return [f for f in found if not (f.kind == "image" and f.ref in built)] if built else found


def _scan_kind(kind: str, text: str, rel: str) -> list[Fetch]:
    if kind == "dockerfile":
        return scan_dockerfile(text, rel)
    if kind == "workflow":
        return scan_workflow(text, rel)
    if kind == "gitlab":
        return scan_gitlab(text, rel)
    if kind == "compose":
        return scan_compose(text, rel)
    if kind == "requirements":
        return scan_requirements(text, rel)
    if kind == "pom":
        return scan_pom(text, rel)
    variables = collect_vars(text, make=kind == "make")
    out: list[Fetch] = []
    for unit in paragraphs(text):
        out.extend(scan_lines(unit, rel, variables))
    return out
