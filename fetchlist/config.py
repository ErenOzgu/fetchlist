""".fetchlist.toml: files to leave out, and allowances for things that are unpinned on purpose."""

from __future__ import annotations

import fnmatch
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path

from .model import UNPINNED, UNRESOLVED, VERIFIED, Fetch

NAME = ".fetchlist.toml"


class ConfigError(Exception):
    pass


@dataclass
class Allow:
    file: str
    ref: str
    reason: str
    used: bool = False


@dataclass
class Config:
    exclude: list[str] = field(default_factory=list)
    allow: list[Allow] = field(default_factory=list)


def load(path: Path) -> Config:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    unknown = set(data) - {"exclude", "allow"}
    if unknown:
        raise ConfigError(f"{path}: unknown key {sorted(unknown)[0]!r}; the keys are 'exclude' and [[allow]]")
    exclude = data.get("exclude", [])
    if not isinstance(exclude, list) or not all(isinstance(e, str) for e in exclude):
        raise ConfigError(f"{path}: 'exclude' must be a list of glob strings")
    allows: list[Allow] = []
    for number, entry in enumerate(data.get("allow", []), start=1):
        if not isinstance(entry, dict):
            raise ConfigError(f"{path}: allow #{number} is not a table")
        missing = {"file", "ref", "reason"} - set(entry)
        extra = set(entry) - {"file", "ref", "reason"}
        if missing or extra:
            raise ConfigError(
                f"{path}: allow #{number}: needs file, ref and reason"
                + (f"; unknown {sorted(extra)}" if extra else "")
            )
        if not all(isinstance(entry[k], str) and entry[k].strip() for k in ("file", "ref", "reason")):
            raise ConfigError(f"{path}: allow #{number}: file, ref and reason must be non-empty strings")
        allows.append(Allow(entry["file"], entry["ref"], entry["reason"].strip()))
    return Config(exclude, allows)


def apply(fetches: list[Fetch], config: Config) -> list[Fetch]:
    """Mark the fetches an allowance covers. An allowance covers a fetch with the same ref in a file that matches."""
    out: list[Fetch] = []
    for fetch in fetches:
        reason = ""
        if fetch.status in (UNPINNED, VERIFIED, UNRESOLVED):
            for allow in config.allow:
                if allow.ref == fetch.ref and fnmatch.fnmatchcase(fetch.file, allow.file):
                    allow.used = True
                    reason = allow.reason
                    break
        out.append(replace(fetch, allowed=reason) if reason else fetch)
    return out


def stale(config: Config) -> list[Allow]:
    """Allowances that covered nothing: the thing they excused is gone, so the allowance should be too."""
    return [a for a in config.allow if not a.used]
