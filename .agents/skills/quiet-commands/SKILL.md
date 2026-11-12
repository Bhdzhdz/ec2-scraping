---
name: quiet-commands
description: Use when running tests, linters, type checkers, installs, git, or any command that may produce long output.
---

# Quiet commands

Tool output is billed as input tokens on every later turn. Keep it small.

| Task | Command |
| --- | --- |
| **AST symbol & signature map (1 call)** | `./scripts/map.sh [path ...]` |
| **Single-file fast gate (iteration)** | `./scripts/check.sh --fix path/to/file.py` |
| **All quality gates (final 1-call check)** | `./scripts/check.sh` (or `./scripts/check.sh --fix`) |
| One test (fast, no cov table; `-q --tb=short` default) | `uv run pytest path::test_name` |
| All tests + coverage gate | `uv run pytest -x --cov 2>&1 \| tail -30` |
| Lint (concise by default) | `uv run ruff check .` |
| Format | `uv run ruff format -q .` |
| Types | `uv run ty check --output-format concise 2>&1 \| head -40` |
| Dependency hygiene | `uv run deptry .` |
| Dead code | `uv run vulture` |
| Import boundaries | `uv run lint-imports` |
| Duplication | `uv run pylint` |
| Complexity / MI | `uv run xenon -b B -m A -a A src tests` (`radon cc -n C -s src tests`, `radon mi -n B -s src tests`) |
| Install | `uv sync -q` |
| Git status | `git status -sb` |
| Git diff | `git diff --stat`, then `git diff -- <file>` for one file |
| Git log | `git log --oneline -n 10` |

Rules:
- Cap unknown-length output with `| head -N` or `| tail -N`.
- On failure, read only the failing section; fix, then rerun just that target.
- Run the full suite once at the end, not after every edit.
- Never `cat` lockfiles, coverage reports, or logs; use `rg`/`tail` on them.
