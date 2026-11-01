"""What the scanners produce."""

from __future__ import annotations

from dataclasses import asdict, dataclass

PINNED = "pinned"  # the content is fixed: a digest, a commit, an exact version, a literal checksum
VERIFIED = (
    "verified"  # a checksum or signature check is in the same step, but where it comes from is not visible
)
UNPINNED = "unpinned"  # the content can change without the repository changing
UNRESOLVED = "unresolved"  # the reference holds a variable this file does not define
INFO = "info"  # not graded: a registry or an index that is used, recorded for `mirror`

STATUSES = (PINNED, VERIFIED, UNPINNED, UNRESOLVED, INFO)

KINDS = ("image", "action", "url", "package", "git", "include")


@dataclass(frozen=True)
class Fetch:
    file: str  # relative to the scanned root, always with "/"
    line: int
    kind: str  # one of KINDS
    ref: str  # what is fetched, as written, with the variables this file defines filled in
    status: str  # one of STATUSES
    why: str  # one sentence: what makes it pinned or not
    host: str = ""  # the host that serves it, "" when it cannot be told
    ecosystem: str = ""  # for packages: pip, npm, go or maven
    allowed: str = ""  # the reason in .fetchlist.toml, when an allowance covers it

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class Skip:
    """A file that looked like a build file and could not be read the way it needs to be."""

    file: str
    reason: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
