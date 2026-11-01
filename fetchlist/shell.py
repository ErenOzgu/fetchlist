"""Find downloads in shell text: the commands of a CI step, a RUN instruction, a script or a Makefile recipe.

The unit that is scanned together matters: a download counts as verified when a checksum or signature check is in the
same unit (one step, one RUN, one blank-line-separated paragraph of a script). That is a heuristic. It shows that a
check exists, not that it covers the file that was downloaded.
"""

from __future__ import annotations

import re
import shlex

from .model import PINNED, UNPINNED, UNRESOLVED, VERIFIED, Fetch
from .util import (
    HEX40,
    collect_vars,
    has_variable,
    host_of,
    image_status,
    is_loopback,
    parse_image,
    substitute,
)

Lines = list[tuple[int, str]]

_DOWNLOADER = re.compile(r"(?<![\w./-])(?:curl|wget)\b")
_URL = re.compile(r"https?://[^\s'\"`<>|;&)(\\]+")
_URL_ASSIGN = re.compile(r"^\s*(?:export\s+)?\w+=[\"']?https?://")
_PIPE_TO_SHELL = re.compile(
    r"(?:curl|wget)\b[^|;&]*\|\s*(?:sudo\s+(?:-\S+\s+)*)?(?:ba|z|da|k)?sh\b"
    r"|(?:ba|z|da)?sh\s+(?:-c\s+)?[\"']?\$\(\s*(?:curl|wget)\b"
    r"|(?:ba|z|da)?sh\s+<\(\s*(?:curl|wget)\b"
    r"|(?:curl|wget)\b[^|;&]*\|\s*(?:sudo\s+)?(?:python3?|perl|ruby)\b"
)
_VERIFY = re.compile(
    r"\b(?:sha(?:1|224|256|384|512)sum|shasum|b2sum)\b[^\n]*?(?:\s-c\b|--check\b)"
    r"|\bgpgv?2?\b[^\n]*?--verify|\bgpgv\b|\bcosign\s+verify|\bminisign\b[^\n]*?\s-V\b"
    r"|\bslsa-verifier\b|\bgh\s+attestation\s+verify"
)
_LITERAL_HASH = re.compile(r"(?<![0-9a-fA-F:])(?:[0-9a-f]{64}|[0-9a-f]{128})(?![0-9a-fA-F])")
_INSECURE = re.compile(r"(?<![\w-])(?:-k|--insecure|--no-check-certificate)\b")
_COMMIT_URL = re.compile(r"/[0-9a-f]{40}(?:/|\.|$)")
_COMMIT_HOSTS = {
    "raw.githubusercontent.com",
    "github.com",
    "codeload.github.com",
    "gitlab.com",
    "bitbucket.org",
}

_WRAPPERS = {"sudo", "time", "exec", "command", "nohup", "env", "-E", "-H", "-n", "doas"}

_PIP_VALUED = {
    "-r", "--requirement", "-c", "--constraint", "-e", "--editable", "-i", "--index-url", "--extra-index-url",
    "-f", "--find-links", "-t", "--target", "--prefix", "--root", "--python", "--platform", "--python-version",
    "--implementation", "--abi", "--src", "--cache-dir", "--proxy", "--retries", "--timeout", "--trusted-host",
    "--config-settings", "-C", "--global-option", "--install-option", "--only-binary", "--no-binary",
}  # fmt: skip
_DOCKER_VALUED = {
    "-p", "--publish", "-e", "--env", "-v", "--volume", "--name", "--network", "--net", "-u", "--user", "-w",
    "--workdir", "--entrypoint", "--env-file", "--mount", "--add-host", "--cap-add", "--cap-drop", "-l", "--label",
    "-m", "--memory", "--cpus", "--restart", "-h", "--hostname", "--platform", "--pull", "--log-driver",
    "--security-opt", "--tmpfs", "--ulimit", "--device", "--group-add", "--health-cmd", "--shm-size", "--ip",
    "--dns", "--pid", "--ipc", "--cidfile", "--stop-signal", "--stop-timeout", "--runtime", "--gpus", "--sysctl",
}  # fmt: skip
_GIT_VALUED = {
    "--depth", "-b", "--branch", "-o", "--origin", "-c", "--config", "--reference", "--separate-git-dir", "-j",
    "--jobs", "--filter", "--template", "--shallow-since", "--shallow-exclude", "--revision", "-u", "--upload-pack",
}  # fmt: skip
_GO_VALUED = {
    "-o",
    "-ldflags",
    "-tags",
    "-gcflags",
    "-asmflags",
    "-mod",
    "-modfile",
    "-p",
    "-pkgdir",
    "-buildmode",
}
_NPM_VALUED = {
    "--registry",
    "--prefix",
    "--loglevel",
    "--cache",
    "--userconfig",
    "--tag",
    "-w",
    "--workspace",
}

_EXACT_NPM = re.compile(r"\d+\.\d+\.\d+(?:[-+][\w.-]+)?")
_GO_VERSION = re.compile(r"v\d+\.\d+\.\d+(?:[-+][\w.+-]+)?")
_PIP_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(?:\[[^\]]*\])?(?P<spec>.*)$")


def logical_lines(text: str, first_line: int) -> Lines:
    """The lines of a script with backslash continuations joined; comment-only and empty lines are left out."""
    out: Lines = []
    buf, start = "", None
    for offset, raw in enumerate(text.splitlines()):
        line = raw.rstrip()
        if start is None:
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            start = first_line + offset
        if line.endswith("\\"):
            buf += line[:-1] + " "
            continue
        out.append((start, (buf + line).strip()))
        buf, start = "", None
    if start is not None:
        out.append((start, buf.strip()))
    return out


def paragraphs(text: str, first_line: int = 1) -> list[Lines]:
    """A script or Makefile split on blank lines; each paragraph is scanned as one unit."""
    units, current, number = [], [], first_line
    for raw in [*text.splitlines(), ""]:
        if raw.strip():
            current.append(raw)
        elif current:
            units.append(logical_lines("\n".join(current), number - len(current)))
            current = []
        number += 1
    return [u for u in units if u]


def _tokens(segment: str) -> list[str]:
    try:
        tokens = shlex.split(segment)
    except ValueError:
        tokens = segment.split()
    while tokens and (re.match(r"^[A-Za-z_]\w*=", tokens[0]) or tokens[0] in _WRAPPERS):
        tokens.pop(0)
    return tokens


def _segments(line: str) -> list[str]:
    return [s for s in re.split(r"\s*(?:&&|\|\||;)\s*|\s\|\s", line) if s.strip()]


def scan_lines(unit: Lines, file: str, variables: dict[str, str | None]) -> list[Fetch]:
    """Everything a unit of shell lines downloads."""
    if not unit:
        return []
    text = "\n".join(line for _, line in unit)
    variables = {**variables, **collect_vars(text)}
    found: list[Fetch] = []
    has_downloader = bool(_DOWNLOADER.search(text))
    verified = bool(_VERIFY.search(text))
    literal = verified and bool(_LITERAL_HASH.search(substitute(text, variables)))
    commit_pinned = bool(re.search(r"\bgit\s+(?:checkout|reset\s+--hard)\s+(?:-\S+\s+)*[0-9a-f]{40}\b", text))

    for number, line in unit:
        seen: set[str] = set()
        if has_downloader and (_DOWNLOADER.search(line) or _URL_ASSIGN.match(line)):
            piped = bool(_PIPE_TO_SHELL.search(line))
            insecure = bool(_DOWNLOADER.search(line) and _INSECURE.search(line))
            for url in _URL.findall(line):
                url = substitute(url.rstrip(".,"), variables)
                if url in seen or is_loopback(url):
                    continue
                seen.add(url)
                status, why = _url_status(url, piped, insecure, verified, literal)
                found.append(Fetch(file, number, "url", url, status, why, host_of(url)))
        for segment in _segments(line):
            tokens = _tokens(segment)
            if tokens:
                found.extend(_command(tokens, file, number, variables, commit_pinned))
    return found


def _url_status(url: str, piped: bool, insecure: bool, verified: bool, literal: bool) -> tuple[str, str]:
    if has_variable(url):
        return UNRESOLVED, "the URL holds a variable that this file does not define"
    host = host_of(url)
    if _COMMIT_URL.search(url) and host in _COMMIT_HOSTS:
        return PINNED, "the URL names a commit, so the content cannot change"
    if piped:
        return UNPINNED, "piped into a shell, so nothing can check what runs"
    if literal:
        return PINNED, "a literal sha256 is checked in the same step"
    weak = (
        "plain http"
        if url.startswith("http://")
        else "certificate checking is turned off"
        if insecure
        else ""
    )
    if weak:
        return UNPINNED, f"{weak}, and nothing in the step ties the download to a known hash"
    if verified:
        return (
            VERIFIED,
            "a checksum or signature check is in the same step; where its value comes from is not visible",
        )
    latest = ", and the URL says latest" if re.search(r"/latest(?:/|$)", url) else ""
    return UNPINNED, f"nothing in the same step checks what was downloaded{latest}"


def _command(
    tokens: list[str], file: str, line: int, variables: dict[str, str | None], commit_pinned: bool
) -> list[Fetch]:
    head = tokens[0].rsplit("/", 1)[-1]
    if head in ("pip", "pip3", "pipx") or (head.startswith("python") and tokens[1:3] == ["-m", "pip"]):
        return _pip(tokens, file, line, variables)
    if head == "uv" and "pip" in tokens[:3]:
        return _pip(tokens, file, line, variables)
    if head == "npm" or head == "npx":
        return _npm(tokens, file, line, variables)
    if head == "go" and tokens[1:2] == ["install"]:
        return _go(tokens, file, line, variables)
    if head in ("docker", "podman") and tokens[1:2] in (["pull"], ["run"], ["create"]):
        return _docker(tokens, file, line, variables)
    if head == "git" and tokens[1:2] == ["clone"]:
        return _git(tokens, file, line, variables, commit_pinned)
    return []


def _positionals(args: list[str], valued: set[str]) -> list[str]:
    out, skip = [], False
    for token in args:
        if skip:
            skip = False
        elif token in valued:
            skip = True
        elif token.startswith("-"):
            continue
        else:
            out.append(token)
    return out


def _is_local_path(spec: str) -> bool:
    """A path or file: URL, which is installed from disk. A package name never holds a slash."""
    if spec.startswith(("file:", "~", ".")):
        return True
    return "://" not in spec and not spec.startswith(("git+", "hg+", "svn+", "bzr+")) and "/" in spec


def _pip(tokens: list[str], file: str, line: int, variables: dict[str, str | None]) -> list[Fetch]:
    try:
        args = tokens[tokens.index("install") + 1 :]
    except ValueError:
        return []
    hashed = "--require-hashes" in args
    index = ""
    for flag in ("-i", "--index-url", "--extra-index-url"):
        if flag in args and args.index(flag) + 1 < len(args):
            index = host_of(substitute(args[args.index(flag) + 1], variables))
    host = index or "pypi.org"
    out: list[Fetch] = []
    for raw in _positionals(args, _PIP_VALUED):
        spec = substitute(raw, variables)
        if _is_local_path(spec):
            continue
        if has_variable(spec):
            out.append(
                Fetch(
                    file,
                    line,
                    "package",
                    spec,
                    UNRESOLVED,
                    "holds a variable this file does not define",
                    host,
                    "pip",
                )
            )
        elif spec.startswith(("git+", "hg+", "svn+", "bzr+")):
            ok = bool(HEX40.fullmatch(spec.rsplit("@", 1)[-1].split("#")[0])) if "@" in spec else False
            why = "pinned to a commit" if ok else "a branch or tag can move"
            out.append(
                Fetch(file, line, "package", spec, PINNED if ok else UNPINNED, why, host_of(spec[4:]), "pip")
            )
        elif spec.startswith(("http://", "https://")):
            ok = "#sha256=" in spec
            why = "the URL carries its sha256" if ok else "no #sha256= on the URL"
            out.append(
                Fetch(file, line, "package", spec, PINNED if ok else UNPINNED, why, host_of(spec), "pip")
            )
        else:
            m = _PIP_NAME.match(spec)
            if not m:
                continue
            exact = re.fullmatch(r"\s*(?:===|==)\s*[^=*\s,;]+\s*", m.group("spec"))
            if hashed:
                out.append(
                    Fetch(file, line, "package", spec, PINNED, "installed with --require-hashes", host, "pip")
                )
            elif exact:
                out.append(Fetch(file, line, "package", spec, PINNED, "exact version", host, "pip"))
            else:
                why = (
                    "any version matches"
                    if not m.group("spec")
                    else f"'{m.group('spec').strip()}' is a range, not one version"
                )
                out.append(Fetch(file, line, "package", spec, UNPINNED, why, host, "pip"))
    return out


def _npm(tokens: list[str], file: str, line: int, variables: dict[str, str | None]) -> list[Fetch]:
    if tokens[0].rsplit("/", 1)[-1] == "npx":
        args = tokens[1:]
        names = _positionals(args, _NPM_VALUED | {"-p", "--package"})[:1]
        names += [a for flag, a in zip(args, args[1:], strict=False) if flag in ("-p", "--package")]
    else:
        if tokens[1:2] not in (["install"], ["i"], ["add"]):
            return []
        names = _positionals(tokens[2:], _NPM_VALUED)
    out: list[Fetch] = []
    for raw in names:
        spec = substitute(raw, variables)
        if spec.startswith((".", "/", "file:")) or "://" in spec or ":" in spec:
            continue
        version = "" if spec.count("@") == (1 if spec.startswith("@") else 0) else spec.rsplit("@", 1)[1]
        if has_variable(spec):
            out.append(
                Fetch(
                    file,
                    line,
                    "package",
                    spec,
                    UNRESOLVED,
                    "holds a variable this file does not define",
                    "registry.npmjs.org",
                    "npm",
                )
            )
        elif _EXACT_NPM.fullmatch(version):
            out.append(
                Fetch(file, line, "package", spec, PINNED, "exact version", "registry.npmjs.org", "npm")
            )
        else:
            why = (
                "no version, which means the newest"
                if not version
                else f"'{version}' is a tag or range, not one version"
            )
            out.append(Fetch(file, line, "package", spec, UNPINNED, why, "registry.npmjs.org", "npm"))
    return out


def _go(tokens: list[str], file: str, line: int, variables: dict[str, str | None]) -> list[Fetch]:
    out: list[Fetch] = []
    for raw in _positionals(tokens[2:], _GO_VALUED):
        spec = substitute(raw, variables)
        if "@" not in spec:
            continue
        version = spec.rsplit("@", 1)[1]
        if has_variable(spec):
            out.append(
                Fetch(
                    file,
                    line,
                    "package",
                    spec,
                    UNRESOLVED,
                    "holds a variable this file does not define",
                    "proxy.golang.org",
                    "go",
                )
            )
        elif _GO_VERSION.fullmatch(version) or HEX40.fullmatch(version):
            out.append(
                Fetch(
                    file,
                    line,
                    "package",
                    spec,
                    PINNED,
                    "a release version or a commit",
                    "proxy.golang.org",
                    "go",
                )
            )
        else:
            out.append(
                Fetch(
                    file,
                    line,
                    "package",
                    spec,
                    UNPINNED,
                    f"@{version} is not a release version",
                    "proxy.golang.org",
                    "go",
                )
            )
    return out


def _docker(tokens: list[str], file: str, line: int, variables: dict[str, str | None]) -> list[Fetch]:
    args = tokens[2:]
    positional = _positionals(args, _DOCKER_VALUED if tokens[1] != "pull" else {"--platform"})
    if not positional:
        return []
    ref = substitute(positional[0], variables)
    status, why = image_status(ref)
    host = "" if has_variable(ref) else parse_image(ref)[0]
    return [Fetch(file, line, "image", ref, status, why, host)]


def _git(
    tokens: list[str], file: str, line: int, variables: dict[str, str | None], commit_pinned: bool
) -> list[Fetch]:
    positional = _positionals(tokens[2:], _GIT_VALUED)
    if not positional:
        return []
    url = substitute(positional[0], variables)
    if not (
        url.startswith(("http://", "https://", "ssh://", "git://")) or re.match(r"[\w.-]+@[\w.-]+:", url)
    ):
        return []
    if has_variable(url):
        return [
            Fetch(file, line, "git", url, UNRESOLVED, "the URL holds a variable this file does not define")
        ]
    revision = next((tokens[i + 1] for i, t in enumerate(tokens[:-1]) if t == "--revision"), "")
    if commit_pinned or HEX40.fullmatch(revision):
        return [
            Fetch(file, line, "git", url, PINNED, "a commit is checked out in the same step", host_of(url))
        ]
    branch = next((tokens[i + 1] for i, t in enumerate(tokens[:-1]) if t in ("-b", "--branch")), "")
    why = (
        f"'{branch}' is a branch or tag and can move"
        if branch
        else "the default branch moves with every push"
    )
    return [Fetch(file, line, "git", url, UNPINNED, why, host_of(url))]
