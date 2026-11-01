# Changelog

## Unreleased

## 0.1.1 - 2026-11-01

### Fixed

- A Compose service that has `build:` as well as `image:` is no longer reported: the image is built there, `image` is
  only the name it gets. Found by running the tool on 24 real repositories (3 tests, and the new lines were
  mutation-checked).

## 0.1.0 - 2026-11-01

First release.

### Added

- `fetchlist scan`, `check` and `mirror`, with text, JSON and Markdown output and GitHub annotations.
- Scanners for Dockerfiles, GitHub Actions workflows and composite actions, GitLab CI files, Compose files, shell
  scripts and Makefiles, `requirements*.txt` and `pom.xml`.
- Statuses `pinned`, `verified`, `unpinned`, `unresolved` and `info`; `--strict` also fails on `verified` and `unresolved`.
- Shell recognition of `curl` and `wget` (with `| sh`, `$(curl ...)` and `<(curl ...)`), `pip`, `npm`/`npx`, `go install`,
  `docker`/`podman` pull and run, and `git clone`; variables the file defines are filled in.
- `.fetchlist.toml` with `exclude` and `[[allow]]` entries that need a reason; an allowance that matches nothing fails.
- Exit status 2 when a file had to be skipped (a `pom.xml` with a `DOCTYPE`, a file over 2 MB).
- 225 tests, a robustness test over mutated inputs, and CI that checks this repository with its own tool.
