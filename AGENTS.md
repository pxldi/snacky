# Working on Snacky

- Public repository. No personal data anywhere in the tree, tests, fixtures,
  commits, PRs or issues: no real meals, weights, goals, schedules, names,
  hostnames or addresses. Test data is made up.
- Conventional Commits (`feat(store): ...`). Release notes are generated from
  them with git-cliff.
- `snacky.model` is the shared interface. Change it in its own PR.
- Run `uv run pytest` and `uv run ruff check` and `uv run ruff format --check`
  before pushing.
- Code comments say why the code is the way it is, in one or two sentences.
