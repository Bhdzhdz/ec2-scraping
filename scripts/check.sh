#!/usr/bin/env bash
# Unified quality gate runner. Prints output ONLY on failure to minimize token usage.
# Usage:
#   ./scripts/check.sh [--fix]                  # Run all 11 repo-wide gates + coverage
#   ./scripts/check.sh [--fix] path/to/file.py  # Fast single-file check + matching unit test
set -uo pipefail

fix=0
target=""
for arg in "$@"; do
    if [[ "$arg" == "--fix" ]]; then
        fix=1
    else
        target="$arg"
    fi
done

failed=0

run_gate() {
    local name="$1"
    shift
    local out
    if ! out="$("$@" 2>&1)"; then
        echo "FAIL [$name]:"
        printf '%s\n' "$out" | head -n 60 || true
        failed=1
    fi
}

run_mi_gate() {
    local out status=0
    out="$(uv run radon mi -n B -s "$@" 2>&1)" || status=$?
    if [[ "$status" -ne 0 || -n "$out" ]]; then
        echo "FAIL [radon-mi] (files below Maintainability Index rank A):"
        printf '%s\n' "$out" | head -n 60 || true
        failed=1
    fi
}

if [[ -n "$target" ]]; then
    if [[ "$fix" -eq 1 ]]; then
        uv run ruff check --fix -q "$target" || true
        uv run ruff format -q "$target"
    fi
    run_gate "ruff-lint" uv run ruff check "$target"
    run_gate "ruff-format" uv run ruff format --check -q "$target"
    run_gate "ty" uv run ty check --output-format concise "$target"
    run_gate "xenon-complexity" uv run xenon --max-absolute B --max-modules A --max-average A "$target"
    run_mi_gate "$target"

    if [[ "$target" == tests/* && -f "$target" ]]; then
        run_gate "pytest" uv run pytest "$target" -x
    elif [[ "$target" == src/* ]]; then
        run_gate "codeaudit" uv run codeaudit cimode "$target"
        base="$(basename "$target" .py)"
        if [[ -f "tests/test_${base}.py" ]]; then
            run_gate "pytest" uv run pytest "tests/test_${base}.py" -x
        fi
    fi
else
    if [[ "$fix" -eq 1 ]]; then
        uv run ruff check --fix -q . || true
        uv run ruff format -q .
    fi
    run_gate "ruff-lint" uv run ruff check .
    run_gate "ruff-format" uv run ruff format --check -q .
    run_gate "ty" uv run ty check --output-format concise
    run_gate "deptry" uv run deptry .
    run_gate "vulture" uv run vulture
    run_gate "import-linter" uv run lint-imports
    run_gate "pylint-duplication" uv run pylint
    run_gate "codeaudit" uv run codeaudit cimode src
    run_gate "xenon-complexity" uv run xenon --max-absolute B --max-modules A --max-average A src tests
    run_mi_gate src tests
    run_gate "pytest" uv run pytest -x --cov
fi

if [[ "$failed" -eq 0 ]]; then
    echo "ok: all checks passed"
fi
exit "$failed"
