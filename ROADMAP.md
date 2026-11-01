# Roadmap

Small steps, in order. A step is done when CI is green, the README says what changed and the CHANGELOG has a line for
it. A step that adds a rule also adds a test for the case that passes and the case that does not, and the mutation check
is run again on the new lines.

- [ ] `pyproject.toml` (project, optional and build dependencies, `[tool.uv]` sources) and `uv.lock`, `poetry.lock`
- [ ] `package.json`, `package-lock.json`: ranges and `latest` in dependencies, git URLs without a commit, `npm install`
      without `ci` in scripts
- [ ] `apt-get install`, `apk add`, `yum`/`dnf install`: packages without a version, and the distribution hosts in `mirror`
- [ ] `--format sarif`, so findings appear in GitHub's code scanning
- [ ] `fetchlist pin REF`: look up the digest or commit that a tag or branch points at today (the one command that needs
      the network, and so a separate command)
- [ ] `.pre-commit-config.yaml` (`rev:` that is a tag, not a commit), Helm `Chart.yaml` dependencies, Terraform
      `required_providers` and module sources
- [ ] Gradle (`build.gradle`, `libs.versions.toml`): dynamic versions (`+`, `latest.release`) and `mavenLocal()`
- [ ] A GitLab CI run of the same checks, and the CI of this repository on GitLab, to confirm the GitLab scanner against
      a real pipeline and not only against test files
- [ ] `--baseline FILE`: accept the current findings and fail only on new ones, for adopting the tool on an old repository
