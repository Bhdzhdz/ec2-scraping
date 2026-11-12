#!/usr/bin/env bash
# Print a compact AST symbol map (files, line ranges, typed signatures) to save discovery tokens.
# Usage: ./scripts/map.sh [path ...]
set -euo pipefail

if [[ $# -eq 0 ]]; then
    set -- src tests
fi

python3 - "$@" <<'PY'
import ast
import pathlib
import sys


def fmt_sig(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    ret = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    return f"{prefix} {node.name}({ast.unparse(node.args)}){ret}"


files: list[pathlib.Path] = []
for arg in sys.argv[1:]:
    p = pathlib.Path(arg)
    if p.is_file():
        files.append(p)
    elif p.is_dir():
        files.extend(sorted(p.rglob("*.py")))

for path in files:
    src = path.read_text(encoding="utf-8")
    total_lines = len(src.splitlines())
    tree = ast.parse(src, filename=str(path))
    print(f"{path} ({total_lines}L)")
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            print(f"  L{node.lineno}-L{node.end_lineno}: {fmt_sig(node)}")
        elif isinstance(node, ast.ClassDef):
            bases = f"({', '.join(ast.unparse(b) for b in node.bases)})" if node.bases else ""
            print(f"  L{node.lineno}-L{node.end_lineno}: class {node.name}{bases}")
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    print(f"    L{item.lineno}-L{item.end_lineno}: {fmt_sig(item)}")
PY
