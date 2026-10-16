---
name: context-hygiene
description: Use in long sessions, large tasks, or when deciding whether to delegate to a subagent or switch models. Controls context growth and cost.
---

# Context hygiene

- Context is re-billed every turn: keep it small and focused on one task per session. Start a fresh session (or compact) when switching tasks.
- Delegate broad research (many searches/reads) to a subagent; only its summary returns to the main context.
- Use a cheaper/faster model for lookups, grep-style research, and mechanical edits; reserve the strongest model for design and tricky debugging.
- Plan briefly before large changes to avoid expensive rework; confirm ambiguous requirements first.
- Keep a short notes file (e.g. `NOTES.md`, git-ignored) for decisions and progress so context can be dropped safely.
- Compact/summarize when the conversation gets long, keeping: goal, decisions, files touched, next steps.
- Don't paste large files or logs into chat; reference paths and grep them.
