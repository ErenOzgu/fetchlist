import json
import os
from pathlib import Path

import pytest

from fetchlist.cli import main

SHA = "a" * 40
HASH = "b" * 64


def tree(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def run(capsys, *argv):
    code = main([str(a) for a in argv])
    out = capsys.readouterr()
    return code, out.out, out.err


PINNED = {"Dockerfile": f"FROM alpine:3.20@sha256:{HASH}\n"}
UNPINNED = {"Dockerfile": "FROM alpine:3.20\n"}


def test_check_passes_on_a_pinned_tree(tmp_path, capsys):
    code, out, _ = run(capsys, "check", tree(tmp_path, PINNED))
    assert code == 0 and out.rstrip().endswith("OK") and "1 pinned" in out


def test_check_fails_on_an_unpinned_one_and_says_where(tmp_path, capsys):
    code, out, _ = run(capsys, "check", tree(tmp_path, UNPINNED))
    assert code == 1
    assert "Dockerfile" in out and "UNPINNED" in out and "alpine:3.20" in out and "FAIL: 1 not pinned" in out


def test_an_empty_tree_is_fine(tmp_path, capsys):
    code, out, _ = run(capsys, "check", tmp_path)
    assert code == 0 and "nothing to grade" in out


def test_scan_never_fails_on_findings(tmp_path, capsys):
    code, out, _ = run(capsys, "scan", tree(tmp_path, UNPINNED))
    assert code == 0 and "UNPINNED" in out


def test_json_output_has_the_summary_and_every_field(tmp_path, capsys):
    code, out, _ = run(capsys, "scan", tree(tmp_path, UNPINNED), "--format", "json")
    document = json.loads(out)
    assert code == 0 and document["summary"]["unpinned"] == 1
    assert set(document["fetches"][0]) == {
        "file",
        "line",
        "kind",
        "ref",
        "status",
        "why",
        "host",
        "ecosystem",
        "allowed",
    }


def test_markdown_output(tmp_path, capsys):
    _, out, _ = run(capsys, "scan", tree(tmp_path, UNPINNED), "--format", "markdown")
    assert out.splitlines()[0].startswith("| Where |") and "`Dockerfile:1`" in out


def test_github_annotations(tmp_path, capsys):
    code, out, _ = run(capsys, "check", tree(tmp_path, UNPINNED), "--format", "github")
    assert code == 1
    assert out.startswith("::error file=Dockerfile,line=1,title=fetchlist unpinned::image alpine:3.20")


def test_strict_also_fails_verified_and_unresolved(tmp_path, capsys):
    files = {"s.sh": 'curl -fsSLo t https://example.com/t\necho "x  t" | sha256sum -c -\n'}
    root = tree(tmp_path, files)
    assert run(capsys, "check", root)[0] == 0
    assert run(capsys, "check", root, "--strict")[0] == 1
    unresolved = tree(tmp_path / "u", {"Dockerfile": "FROM ${BASE}\n"})
    assert run(capsys, "check", unresolved)[0] == 0
    assert run(capsys, "check", unresolved, "--strict")[0] == 1


def test_a_missing_directory_is_exit_2(tmp_path, capsys):
    code, _, err = run(capsys, "check", tmp_path / "nope")
    assert code == 2 and "not a directory" in err


def test_a_file_that_cannot_be_analysed_makes_check_exit_2_and_scan_say_so(tmp_path, capsys):
    root = tree(tmp_path, {"pom.xml": '<!DOCTYPE x [<!ENTITY a "b">]><project/>'})
    code, _, err = run(capsys, "check", root)
    assert code == 2 and "skipped pom.xml" in err and "DOCTYPE" in err
    assert run(capsys, "scan", root)[0] == 0


def test_an_allowance_with_a_reason_lets_check_pass(tmp_path, capsys):
    config = '[[allow]]\nfile = "Dockerfile"\nref = "alpine:3.20"\nreason = "a throw-away base"\n'
    root = tree(tmp_path, {**UNPINNED, ".fetchlist.toml": config})
    code, out, _ = run(capsys, "check", root)
    assert code == 0 and "(1 allowed)" in out
    _, scanned, _ = run(capsys, "scan", root)
    assert "allowed: a throw-away base" in scanned


def test_an_allowance_matches_by_file_glob_and_exact_ref(tmp_path, capsys):
    config = '[[allow]]\nfile = "docker/*"\nref = "alpine:3.20"\nreason = "x"\n'
    root = tree(
        tmp_path,
        {
            "docker/Dockerfile": "FROM alpine:3.20\n",
            "Dockerfile": "FROM alpine:3.20\n",
            ".fetchlist.toml": config,
        },
    )
    code, out, _ = run(capsys, "check", root)
    assert code == 1 and "FAIL: 1 not pinned" in out


def test_a_stale_allowance_fails(tmp_path, capsys):
    config = '[[allow]]\nfile = "Dockerfile"\nref = "alpine:3.20"\nreason = "was needed once"\n'
    root = tree(tmp_path, {**PINNED, ".fetchlist.toml": config})
    code, out, err = run(capsys, "check", root)
    assert code == 1 and "matches nothing" in err and "stale" in out


@pytest.mark.parametrize(
    ("config", "message"),
    [
        ("[[allow]]\nfile = 'a'\nref = 'b'\n", "needs file, ref and reason"),
        ("[[allow]]\nfile = 'a'\nref = 'b'\nreason = ''\n", "non-empty"),
        ("[[allow]]\nfile = 'a'\nref = 'b'\nreason = 'c'\nwhy = 'd'\n", "unknown"),
        ("flavour = 1\n", "unknown key"),
        ("exclude = 'x'\n", "list of glob"),
        ("this is not toml", "fetchlist.toml"),
    ],
)
def test_a_bad_config_is_exit_2_with_a_message(tmp_path, capsys, config, message):
    root = tree(tmp_path, {**UNPINNED, ".fetchlist.toml": config})
    code, _, err = run(capsys, "check", root)
    assert code == 2 and message in err


def test_exclude_leaves_files_out(tmp_path, capsys):
    root = tree(
        tmp_path,
        {
            **UNPINNED,
            "examples/Dockerfile": "FROM alpine\n",
            ".fetchlist.toml": 'exclude = ["examples/**"]\n',
        },
    )
    _, out, _ = run(capsys, "scan", root)
    assert "examples" not in out and "1 fetches in 1 files" in out


def test_config_option_names_another_file(tmp_path, capsys):
    root = tree(tmp_path / "src", UNPINNED)
    config = (
        tree(
            tmp_path / "cfg",
            {"c.toml": '[[allow]]\nfile = "Dockerfile"\nref = "alpine:3.20"\nreason = "x"\n'},
        )
        / "c.toml"
    )
    assert run(capsys, "check", root, "--config", config)[0] == 0


def test_mirror_lists_hosts_images_actions_and_packages(tmp_path, capsys):
    root = tree(
        tmp_path,
        {
            "Dockerfile": "FROM ghcr.io/o/i:1\nRUN pip install ruff==0.6.1\n",
            ".github/workflows/c.yml": f"steps:\n  - uses: actions/checkout@{SHA}\n  - run: curl -O https://example.com/t\n",
        },
    )
    _, hosts, _ = run(capsys, "mirror", root)
    assert hosts.split() == ["example.com", "ghcr.io", "github.com", "pypi.org"]
    _, images, _ = run(capsys, "mirror", root, "--what", "images")
    assert images.split() == ["ghcr.io/o/i:1"]
    _, packages, _ = run(capsys, "mirror", root, "--what", "packages")
    assert packages.split() == ["pip:ruff==0.6.1"]
    _, as_json, _ = run(capsys, "mirror", root, "--what", "actions", "--format", "json")
    assert json.loads(as_json) == {"actions": [f"actions/checkout@{SHA}"]}


def test_mirror_says_what_it_cannot_place(tmp_path, capsys):
    root = tree(tmp_path, {"s.sh": "curl -O https://${HOST}/t\n"})
    _, out, err = run(capsys, "mirror", root)
    assert out == "" and "1 fetch has no known host" in err


def test_the_default_root_is_the_current_directory(tmp_path, capsys, monkeypatch):
    tree(tmp_path, UNPINNED)
    monkeypatch.chdir(tmp_path)
    assert run(capsys, "check")[0] == 1


def test_version_and_usage(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0 and "fetchlist 0.1.1" in capsys.readouterr().out
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2


def test_output_does_not_depend_on_the_directory_walk_order(tmp_path, capsys):
    files = {f"d{i}/Dockerfile": "FROM alpine\n" for i in range(5)}
    root = tree(tmp_path, files)
    first = run(capsys, "scan", root)[1]
    assert [line for line in first.splitlines() if line.endswith("Dockerfile")] == [
        f"d{i}/Dockerfile" for i in range(5)
    ]


@pytest.mark.skipif(os.name == "nt", reason="symlinks")
def test_a_symlink_is_not_followed(tmp_path, capsys):
    outside = tree(tmp_path / "outside", UNPINNED)
    root = tree(tmp_path / "root", {"README.md": "x"})
    (root / "Dockerfile").symlink_to(outside / "Dockerfile")
    (root / "linked").symlink_to(outside, target_is_directory=True)
    _, out, _ = run(capsys, "scan", root)
    assert "nothing to grade" in out


def test_files_come_out_in_path_order_whatever_the_walk_order(tmp_path, capsys):
    root = tree(
        tmp_path, {"Dockerfile": "FROM alpine\n", ".github/workflows/c.yml": "steps:\n  - uses: o/r@v1\n"}
    )
    out = run(capsys, "scan", root)[1].splitlines()
    assert out.index(".github/workflows/c.yml") < out.index("Dockerfile")


def test_an_allowance_covers_only_the_ref_it_names(tmp_path, capsys):
    config = '[[allow]]\nfile = "Dockerfile"\nref = "alpine:3.20"\nreason = "x"\n'
    root = tree(tmp_path, {"Dockerfile": "FROM alpine:3.20\nFROM debian:12\n", ".fetchlist.toml": config})
    code, out, _ = run(capsys, "check", root)
    assert code == 1 and "debian:12" in out and "FAIL: 1 not pinned" in out


def test_an_allowance_for_something_that_is_pinned_is_stale(tmp_path, capsys):
    ref = f"alpine:3.20@sha256:{HASH}"
    config = f'[[allow]]\nfile = "Dockerfile"\nref = "{ref}"\nreason = "x"\n'
    root = tree(tmp_path, {**PINNED, ".fetchlist.toml": config})
    assert run(capsys, "check", root)[0] == 1


def test_github_format_warns_for_verified_and_errors_for_unpinned(tmp_path, capsys):
    root = tree(tmp_path, {"s.sh": 'curl -fsSLo t https://example.com/t\necho "x  t" | sha256sum -c -\n'})
    code, out, _ = run(capsys, "check", root, "--format", "github", "--strict")
    assert code == 1 and out.startswith("::warning file=s.sh,line=1,")


def test_an_index_in_requirements_is_a_host_but_not_a_package(tmp_path, capsys):
    root = tree(tmp_path, {"requirements.txt": "--index-url https://pkgs.example.com/simple\nruff==0.6.1\n"})
    assert run(capsys, "mirror", root, "--what", "packages")[1].split() == ["pip:ruff==0.6.1"]
    assert "pkgs.example.com" in run(capsys, "mirror", root)[1].split()
