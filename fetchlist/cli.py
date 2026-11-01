"""The command line: scan, check, mirror."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, mirror, report
from . import config as cfg
from .discover import analyse
from .model import UNPINNED, UNRESOLVED, VERIFIED, Fetch, Skip

EXIT_OK, EXIT_FINDINGS, EXIT_ERROR = 0, 1, 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fetchlist",
        description="List what a build downloads from outside the repository, and say what is not pinned.",
    )
    parser.add_argument("--version", action="version", version=f"fetchlist {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("root", nargs="?", default=".", help="directory to scan (default: .)")
        p.add_argument("--config", help=f"configuration file (default: ROOT/{cfg.NAME} if it exists)")

    scan = sub.add_parser("scan", help="list every download the build files name, pinned or not")
    common(scan)
    scan.add_argument("--format", choices=("text", "json", "markdown"), default="text")

    check = sub.add_parser("check", help="exit 1 when something is not pinned")
    common(check)
    check.add_argument("--format", choices=("text", "json", "github"), default="text")
    check.add_argument("--strict", action="store_true", help="also fail on 'verified' and 'unresolved'")

    mir = sub.add_parser("mirror", help="list the hosts, images, actions and packages the build has to reach")
    common(mir)
    mir.add_argument("--what", choices=(*mirror.WHAT, "all"), default="hosts")
    mir.add_argument("--format", choices=("plain", "json"), default="plain")
    return parser


def _load(args: argparse.Namespace) -> tuple[Path, cfg.Config, list[Fetch], list[Skip]]:
    root = Path(args.root)
    if not root.is_dir():
        raise SystemExit(_fail(f"{args.root}: not a directory"))
    path = Path(args.config) if args.config else root / cfg.NAME
    config = cfg.Config()
    if args.config or path.is_file():
        try:
            config = cfg.load(path)
        except cfg.ConfigError as exc:
            raise SystemExit(_fail(str(exc))) from exc
    fetches, skips = analyse(root, config.exclude)
    return root, config, cfg.apply(fetches, config), skips


def _fail(message: str) -> int:
    print(f"fetchlist: {message}", file=sys.stderr)
    return EXIT_ERROR


def _report_skips(skips: list[Skip]) -> None:
    for skip in skips:
        print(f"fetchlist: skipped {skip.file}: {skip.reason}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        _root, config, fetches, skips = _load(args)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else EXIT_ERROR
    _report_skips(skips)

    if args.command == "scan":
        if args.format == "json":
            print(report.as_json(fetches, skips))
        elif args.format == "markdown":
            print(report.markdown(fetches))
        else:
            body = report.text(fetches)
            print(body + "\n" if body else "", end="")
            print(report.summary_line(fetches))
        return EXIT_OK

    if args.command == "mirror":
        output = mirror.render(fetches, args.what, args.format)
        if output:
            print(output)
        missing = mirror.unknown_hosts(fetches)
        if missing:
            noun = "fetch has" if missing == 1 else "fetches have"
            print(
                f"fetchlist: {missing} {noun} no known host (a variable in the URL, or a GitLab project include); "
                "not in the host list",
                file=sys.stderr,
            )
        return EXIT_OK

    failing = {UNPINNED} | ({VERIFIED, UNRESOLVED} if args.strict else set())
    bad = [f for f in fetches if f.status in failing and not f.allowed]
    left_over = cfg.stale(config)
    if args.format == "json":
        print(report.as_json(bad, skips))
    elif args.format == "github":
        out = report.github(bad)
        print(out) if out else None
    else:
        body = report.text(bad)
        if body:
            print(body + "\n")
        print(report.summary_line(fetches))
    for allow in left_over:
        print(
            f"fetchlist: the allowance for {allow.ref!r} in {allow.file!r} matches nothing; remove it",
            file=sys.stderr,
        )
    if skips:
        return EXIT_ERROR
    if bad or left_over:
        if args.format == "text":
            print(
                f"FAIL: {len(bad)} not pinned" + (f", {len(left_over)} stale allowances" if left_over else "")
            )
        return EXIT_FINDINGS
    if args.format == "text":
        print("OK")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
