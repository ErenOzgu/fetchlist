"""Maven pom.xml: dependencies, plugins and repositories whose version can change."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from .model import INFO, PINNED, UNPINNED, UNRESOLVED, Fetch
from .util import host_of

CENTRAL = "repo.maven.apache.org"


class Refused(Exception):
    """The file is not read, and the reason is reported."""


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _children(node: ET.Element, name: str) -> list[ET.Element]:
    return [c for c in node if _local(c.tag) == name]


def _text(node: ET.Element, name: str) -> str:
    found = _children(node, name)
    return (found[0].text or "").strip() if found else ""


def _line_of(text: str, artifact: str, used: set[int]) -> int:
    """The line of `<artifactId>artifact</artifactId>` (nearest unused match), for a readable report."""
    for number, line in enumerate(text.splitlines(), start=1):
        if number not in used and re.search(rf"<artifactId>\s*{re.escape(artifact)}\s*</artifactId>", line):
            used.add(number)
            return number
    return 1


def _resolve(version: str, properties: dict[str, str]) -> str:
    for _ in range(5):
        new = re.sub(r"\$\{([^}]+)\}", lambda m: properties.get(m.group(1), m.group(0)), version)
        if new == version:
            break
        version = new
    return version


def _version_status(version: str) -> tuple[str, str]:
    if "${" in version:
        return UNRESOLVED, "the version is a property that this file does not define (a parent pom may)"
    if version in ("LATEST", "RELEASE"):
        return UNPINNED, f"{version} follows whatever is newest"
    if version.startswith(("[", "(")) or "," in version:
        return UNPINNED, f"{version} is a range, not one version"
    if version.endswith("-SNAPSHOT"):
        return UNPINNED, "a SNAPSHOT is replaced by every deploy"
    return PINNED, "exact version"


def scan_pom(text: str, file: str) -> list[Fetch]:
    if re.search(r"<!(?:DOCTYPE|ENTITY)", text):
        raise Refused("contains a DOCTYPE or ENTITY declaration, which this tool does not expand")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise Refused(f"not well-formed XML: {exc}") from exc
    properties: dict[str, str] = {}
    for props in _children(root, "properties"):
        for prop in props:
            properties[_local(prop.tag)] = (prop.text or "").strip()
    for key in ("version", "groupId"):
        if _text(root, key):
            properties[f"project.{key}"] = _text(root, key)
    used: set[int] = set()
    out: list[Fetch] = []
    managed_plugins = {
        _text(p, "artifactId")
        for mgmt in root.iter()
        if _local(mgmt.tag) == "pluginManagement"
        for p in mgmt.iter()
        if _local(p.tag) == "plugin" and _text(p, "version")
    }
    managed_deps = {
        _text(d, "artifactId")
        for mgmt in root.iter()
        if _local(mgmt.tag) == "dependencyManagement"
        for d in mgmt.iter()
        if _local(d.tag) == "dependency"
    }
    has_bom = any(
        _text(d, "scope") == "import"
        for mgmt in root.iter()
        if _local(mgmt.tag) == "dependencyManagement"
        for d in mgmt.iter()
        if _local(d.tag) == "dependency"
    )
    for node in root.iter():
        kind = _local(node.tag)
        if kind not in ("dependency", "plugin", "extension", "parent"):
            continue
        artifact = _text(node, "artifactId")
        if not artifact:
            continue
        group = _text(node, "groupId") or ("org.apache.maven.plugins" if kind == "plugin" else "")
        version = _text(node, "version")
        number = _line_of(text, artifact, used)
        version = _resolve(version, properties)
        coordinate = f"{group}:{artifact}" + (f":{version}" if version else "")
        if version:
            status, why = _version_status(version)
            out.append(Fetch(file, number, "package", coordinate, status, why, CENTRAL, "maven"))
        elif kind == "plugin" and artifact not in managed_plugins:
            out.append(
                Fetch(
                    file,
                    number,
                    "package",
                    coordinate,
                    UNPINNED,
                    "no version here and none in pluginManagement; Maven picks one, unless a parent pom sets it",
                    CENTRAL,
                    "maven",
                )
            )
        elif kind in ("dependency", "extension") and (has_bom or artifact in managed_deps):
            out.append(
                Fetch(
                    file,
                    number,
                    "package",
                    coordinate,
                    PINNED,
                    "the version comes from this pom's dependencyManagement or an imported BOM",
                    CENTRAL,
                    "maven",
                )
            )
        elif kind in ("dependency", "extension") and not _children(root, "parent"):
            out.append(
                Fetch(
                    file,
                    number,
                    "package",
                    coordinate,
                    UNRESOLVED,
                    "no version here and no dependencyManagement",
                    CENTRAL,
                    "maven",
                )
            )
    for repo in root.iter():
        if _local(repo.tag) in ("repository", "pluginRepository"):
            url = _text(repo, "url")
            if not url:
                continue
            number = next((n for n, line in enumerate(text.splitlines(), start=1) if url in line), 1)
            if url.startswith("http://"):
                out.append(
                    Fetch(
                        file,
                        number,
                        "url",
                        url,
                        UNPINNED,
                        "a repository over plain http; Maven 3.8.1 and later refuse it",
                        host_of(url),
                        "maven",
                    )
                )
            else:
                out.append(
                    Fetch(
                        file,
                        number,
                        "url",
                        url,
                        INFO,
                        "a repository this pom downloads from",
                        host_of(url),
                        "maven",
                    )
                )
    return out
