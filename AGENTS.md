# Agent guidelines

Keep token usage (cost) low. Skills in `.agents/skills/` give details; load them when relevant.

## Always
- Search before reading: use `rg`/`fd` to locate code, then read only the needed line ranges. Never read whole large files or directories.
- Edit in place with targeted diffs. Do not rewrite or re-print whole files.
- Limit command output (`| head`, `| tail`, `-q`, `--tb=short`). Never dump logs, lockfiles, or generated files.
- Batch independent tool calls in parallel; avoid repeating reads of the same file.
- Be concise: no restating the task, no summaries of diffs the user can see, no long preambles.
- Ask one clarifying question early instead of guessing and redoing work.
- Don't re-run the full test suite repeatedly; run the specific failing test first.

## Project commands
- Install: `uv sync`
- Lint/format: `uv run ruff check --fix . && uv run ruff format .`
- Types: `uv run ty check`
- Tests: `uv run pytest -q -x --tb=short`

## Skills
- `efficient-exploration`: navigating the codebase cheaply
- `concise-output`: response and edit style
- `quiet-commands`: running tools with minimal output
- `context-hygiene`: long sessions, subagents, model choice
- `speckit-*`: Spec Kit spec-driven workflow (constitution → specify → clarify → plan → tasks → implement); state in `.specify/`, specs in `specs/`

## Commits
- Use Conventional Commits (`type(scope): subject`; types: feat, fix, docs, style, refactor, perf, test, build, ci, chore, revert). Enforced by a commitizen `commit-msg` hook; `uv run cz commit` gives a guided prompt and `uv run cz bump` cuts a release.
