---
name: efficient-exploration
description: Use when locating code, understanding the codebase, or before reading files. Minimizes tokens spent on discovery.
---

# Efficient exploration

1. Start from the AST map: `./scripts/map.sh` (or `./scripts/map.sh src/pkg`) to see all files, line counts, `Lstart-Lend` ranges, and full typed signatures in one call. Don't `ls -R` or read directory trees.
2. Locate specific text with `rg -n "symbol" src tests` (add `-l` for file names only, `-m 5` to cap matches).
3. Read ranges, not files: use the exact `Lstart-Lend` from `./scripts/map.sh` or ~40 lines around an `rg` match. Expand only if needed.
4. Prefer signatures first: `rg -n "^(def|class) " path/to/file.py` to see a file's shape and typed contracts (`ANN` is enforced) before reading bodies.
5. Skip: `.venv`, `uv.lock`, `htmlcov`, caches, generated files, and binary/data files (`.ignore` already hides `.agents/`, `.specify/`, and `uv.lock` from default `rg`/`fd` runs).
6. Remember what you've read; don't re-read unchanged files.
7. Run independent searches in one parallel batch.
