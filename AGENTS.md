# Agent guidelines

Keep token usage (cost) low. **For isolated tasks, all rules and commands are in this file—do NOT spend tool calls reading `.agents/skills/` unless invoking a Spec Kit workflow (`speckit-*`).**

## Isolated-Call Workflow (Minimum Tokens)
1. **Map before reading**: Run `./scripts/map.sh` (or `./scripts/map.sh src/pkg`) to get all files, line counts, `Lstart-Lend` ranges, and full typed signatures in 1 call, or locate symbols with `rg -n "symbol" src tests` (`.ignore` automatically skips `.specify/`, `.agents/`, and `uv.lock`).
2. **Read narrow line ranges**: Use the `Lstart-Lend` ranges from `./scripts/map.sh` or `rg` to read only the needed function/class. Never read whole large files, lockfiles, or `.venv`.
3. **Edit in place**: Use targeted diffs. Do not rewrite or paste back whole files.
4. **Iterate on the touched file**: Run `./scripts/check.sh --fix path/to/file.py` to auto-fix, lint, type-check, verify complexity, and run the matching `tests/test_<name>.py` in 1 quiet call.
5. **Verify once at the end**: Run `./scripts/check.sh --fix` to execute all 10 repo-wide gates + coverage (outputs `ok: all checks passed`, or only failing checks).
6. **Be concise**: Answer first; state what changed in 1–3 lines; reference `path:line` instead of quoting code; ask 1 clarifying question early if requirements are ambiguous.

## Code & Architecture Gates (write compliant code on first pass)
- **Typing**: Explicit type annotations on all functions/methods (`ANN`); put typing-only imports under `if TYPE_CHECKING:` (`TC`).
- **Size & complexity**: Function CC <= 10 (`C901`/`xenon` <= B, module/avg A), Maintainability Index A (`radon mi`), <= 5 args, <= 10 branches, <= 5 returns, <= 40 statements (`PLR`).
- **Hygiene**: No dead/unused code (`vulture`), no duplicate blocks >= 6 lines (`pylint`), no commented-out code (`ERA`), no `print()` in `src/` (`T20`), no unused args (`ARG`).
- **Architecture & deps**: No circular sibling imports (`lint-imports`), no unused/missing/misplaced dependencies (`deptry`), >= 80% branch coverage (`pytest --cov`).

## Project commands
- **Codebase AST map (1 call)**: `./scripts/map.sh [path ...]`
- **Single-file gate (fast iteration)**: `./scripts/check.sh --fix path/to/file.py`
- **All repo gates (final check)**: `./scripts/check.sh --fix`
- Install: `uv sync -q`
- One test (no cov table; `-q --tb=short` is default): `uv run pytest path::test_name`
- Full tests + coverage: `uv run pytest -x --cov`
- Individual tools: `uv run ruff check --fix .`, `uv run ty check --output-format concise`, `uv run deptry .`, `uv run vulture`, `uv run lint-imports`, `uv run pylint`, `uv run xenon -b B -m A -a A src tests`

## Skills (load ONLY when needed)
- `speckit-*`: Spec Kit spec-driven workflow (`constitution` → `specify` → `clarify` → `plan` → `tasks` → `implement`); state in `.specify/`, specs in `specs/`.
- `efficient-exploration`, `concise-output`, `quiet-commands`, `context-hygiene`: Reference skills (already summarized above; do not load on simple isolated calls).

## Commits
- Use Conventional Commits (`type(scope): subject`; types: feat, fix, docs, style, refactor, perf, test, build, ci, chore, revert). Enforced by a commitizen `commit-msg` hook; `uv run cz commit` gives a guided prompt and `uv run cz bump` cuts a release.
