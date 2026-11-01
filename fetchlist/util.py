"""Small helpers shared by the scanners: image references, hosts and variables."""

from __future__ import annotations

import re

from .model import PINNED, UNPINNED, UNRESOLVED

HEX40 = re.compile(r"[0-9a-f]{40}")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


def host_of(url: str) -> str:
    """The host of an http(s), ssh or git URL, or of an scp-style git address; "" when it holds a variable."""
    m = re.match(r"(?:https?|ssh|git)://(?:[^/@\s]+@)?([^/:\s]+)", url)
    if m:
        host = m.group(1)
    else:
        m = re.match(r"[\w.-]+@([^:/\s]+):", url)
        host = m.group(1) if m else ""
    return "" if "$" in host or "{" in host else host.lower()


def parse_image(ref: str) -> tuple[str, str, str, str]:
    """(registry, name, tag, digest) of an image reference. A bare name lives on docker.io."""
    name, _, digest = ref.partition("@")
    tag = ""
    if ":" in name.rsplit("/", 1)[-1]:
        name, tag = name.rsplit(":", 1)
    first, sep, _rest = name.partition("/")
    registry = first if sep and ("." in first or ":" in first or first == "localhost") else "docker.io"
    return registry, name, tag, digest


def is_loopback(url: str) -> bool:
    """A URL that points at the machine itself: a test of a service under build, not a download."""
    if re.match(r"https?://(?:[^/@\s]+@)?\[::1\]", url):
        return True
    host = host_of(url)
    return host in ("localhost", "0.0.0.0", "host.docker.internal") or host.startswith("127.")


def has_variable(text: str) -> bool:
    return "$" in text or "{{" in text


def image_status(ref: str) -> tuple[str, str]:
    """(status, why) of an image reference."""
    if has_variable(ref):
        return UNRESOLVED, "the reference holds a variable that this file does not define"
    _registry, _name, tag, digest = parse_image(ref)
    if digest:
        if DIGEST.fullmatch(digest):
            return PINNED, "pinned by digest"
        return UNPINNED, f"'{digest}' is not a sha256 digest"
    if not tag:
        return UNPINNED, "no tag, which means :latest, and that changes with every push"
    if tag == "latest":
        return UNPINNED, ":latest changes with every push"
    return UNPINNED, f"the tag :{tag} can be pushed again to different content"


_REF = re.compile(r"\$\{\{\s*env\.(\w+)\s*\}\}|\$\{(\w+)(?::?[-=]([^}]*)|:?\?[^}]*)?\}|\$\((\w+)\)|\$(\w+)")


def substitute(text: str, variables: dict[str, str | None]) -> str:
    """Fill in ${NAME}, $NAME, $(NAME), ${NAME:-default} and ${{ env.NAME }} from the variables of the file.

    A name that is not defined, or defined with two different values, stays as written, so that the
    result is reported as unresolved and not guessed."""

    def one(m: re.Match[str]) -> str:
        name = m.group(1) or m.group(2) or m.group(4) or m.group(5)
        value = variables.get(name)
        if value is None:
            return m.group(3) if m.group(3) is not None else m.group(0)
        return value

    for _ in range(5):
        new = _REF.sub(one, text)
        if new == text:
            break
        text = new
    return text


_SHELL_ASSIGN = re.compile(r"^\s*(?:export\s+|ENV\s+|ARG\s+|readonly\s+)?([A-Za-z_]\w*)=(.*?)\s*$")
_YAML_ASSIGN = re.compile(r"^\s*(?:-\s+)?([A-Z][A-Z0-9_]*):\s+(\S.*?)\s*$")
_MAKE_ASSIGN = re.compile(r"^\s*(?:export\s+)?([A-Za-z_]\w*)\s*(?:::|[:?+])?=\s*(.*?)\s*$")


def unquote(value: str) -> str:
    value = value.strip()
    if value[:1] in ("'", '"'):
        end = value.find(value[0], 1)
        return value[1:end] if end > 0 else value[1:]
    return re.split(r"\s+#", value, maxsplit=1)[0].strip()


def collect_vars(text: str, *, yaml: bool = False, make: bool = False) -> dict[str, str | None]:
    """Variables a file defines for itself. A name with two different values is None: it is ambiguous."""
    patterns = [_SHELL_ASSIGN]
    if yaml:
        patterns.append(_YAML_ASSIGN)
    if make:
        patterns = [_MAKE_ASSIGN]
    found: dict[str, str | None] = {}
    for line in text.splitlines():
        for pattern in patterns:
            m = pattern.match(line)
            if not m:
                continue
            name, value = m.group(1), unquote(m.group(2))
            if not value:
                break
            if name in found and found[name] != value:
                found[name] = None
            else:
                found.setdefault(name, value)
            break
    return found
