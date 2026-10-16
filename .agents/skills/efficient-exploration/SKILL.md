---
name: efficient-exploration
description: Use when locating code, understanding the codebase, or before reading files. Minimizes tokens spent on discovery.
---

# Efficient exploration

1. Start from the layout: `fd -t f -e py . src tests | head -50` (fd's first argument is a pattern; `.` matches all). Don't `ls -R` or read directory trees.
2. Locate with `rg -n "symbol" src tests` (add `-l` for file names only, `-m 5` to cap matches).
3. Read ranges, not files: view ~40 lines around the match. Expand only if needed.
4. Prefer signatures first: `rg -n "^(def|class) " path/to/file.py` to see a file's shape before reading bodies.
5. Skip: `.venv`, `uv.lock`, `htmlcov`, caches, generated files, and binary/data files.
6. Remember what you've read; don't re-read unchanged files.
7. Run independent searches in one parallel batch.
