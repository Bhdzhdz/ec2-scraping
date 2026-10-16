---
name: quiet-commands
description: Use when running tests, linters, type checkers, installs, git, or any command that may produce long output.
---

# Quiet commands

Tool output is billed as input tokens on every later turn. Keep it small.

| Task | Command |
| --- | --- |
| All tests | `uv run pytest -q -x --tb=short 2>&1 \| tail -30` |
| One test | `uv run pytest -q path::test_name --tb=short` |
| Lint | `uv run ruff check --output-format=concise .` |
| Format | `uv run ruff format -q .` |
| Types | `uv run ty check --output-format concise 2>&1 \| head -40` |
| Install | `uv sync -q` |
| Git status | `git status -sb` |
| Git diff | `git diff --stat`, then `git diff -- <file>` for one file |
| Git log | `git log --oneline -n 10` |

Rules:
- Cap unknown-length output with `| head -N` or `| tail -N`.
- On failure, read only the failing section; fix, then rerun just that target.
- Run the full suite once at the end, not after every edit.
- Never `cat` lockfiles, coverage reports, or logs; use `rg`/`tail` on them.
