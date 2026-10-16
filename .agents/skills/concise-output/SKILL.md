---
name: concise-output
description: Use when writing responses, code edits, or commit/PR text. Keeps output tokens low without losing information.
---

# Concise output

- Answer first; skip preambles, restated questions, and closing recaps.
- After an edit, state what changed in 1–3 lines. Don't paste the diff back.
- Use targeted edits (replace a block) over rewriting files.
- Don't add speculative features, extra docs, or unrequested refactors.
- Reference code by `path:line` instead of quoting it.
- Prefer bullet lists and short sentences. Use tables/diagrams only when they replace more text than they cost.
- Keep existing comments and docstrings that are unrelated to your change.
