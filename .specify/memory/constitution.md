# EC2 Scraping Constitution

## Core Principles

### I. Automated Quality & Structural Gates (NON-NEGOTIABLE)
All changes MUST pass `./scripts/check.sh` with zero errors before completion:
- **Lint, Security & Hygiene (`ruff` + `codeaudit`)**: Enforces `E, F, W, I, B, UP, SIM, C4, C90, RUF, PT, PL, ERA, ARG, T20, S, ANN, TC, PIE, FURB, PERF, RET, TID` with concise output, plus AST security validation via `codeaudit cimode src`. No commented-out code (`ERA`), no `print()` in `src/` (`T20`), no unused arguments (`ARG`), no security anti-patterns or SAST weaknesses (`S` / `codeaudit`).
- **Complexity & Function Size (`ruff` + `xenon` + `radon`)**: Cyclomatic complexity <= 10 (rank A/B per block, rank A module & average via `xenon`), Maintainability Index rank A (`radon mi`), and Pylint structural limits: max 5 arguments, max 10 branches, max 5 returns, max 40 statements per function.
- **Static Typing (`ty` + `ruff ANN/TC`)**: Explicit type annotations are mandatory on all function and method signatures. `ty check` must pass cleanly.
- **Zero Duplication & Dead Code (`pylint` + `vulture`)**: No duplicated code blocks >= 6 lines (`pylint` `duplicate-code`); no unused functions, classes, methods, or variables (`vulture`).
- **Architecture & Dependency Hygiene (`import-linter` + `deptry`)**: No circular imports between sibling modules (`lint-imports`); no unused, missing, or misplaced dependencies (`deptry`).

### II. Test & Coverage Discipline (NON-NEGOTIABLE)
- Minimum **80% branch coverage** (`pytest --cov`) across `src/ec2_scraping`.
- Run targeted tests (`uv run pytest -q path::test_name --tb=short`) while iterating; run the full gate (`./scripts/check.sh`) once at the end.

### III. Self-Documenting Code for Agentic AI
- Signatures (`def` / `class`) must have complete type annotations and descriptive names so contracts are clear from `rg -n "^(def|class) "` without reading function bodies.
- Prefer small, pure, single-responsibility functions and flat control flow (early returns over deep nesting).

### IV. Token & Context Efficiency
- Locate before reading (`fd` / `rg`, which automatically skip `.specify/`, `.agents/`, and `uv.lock` via `.ignore`).
- Read narrow line ranges around matches; edit in place with targeted diffs.
- Use `./scripts/check.sh` (or `./scripts/check.sh --fix`) to validate all gates in a single tool call that only prints output on failure.

## Governance
- Managed with `uv`, `pre-commit` (hygiene + ruff on commit; `./scripts/check.sh` on push), and `commitizen` (Conventional Commits).
- These principles are non-negotiable across `$speckit-plan`, `$speckit-analyze`, `$speckit-implement`, and code review.

**Version**: 1.0.0
