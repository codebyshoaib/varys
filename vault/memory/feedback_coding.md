---
name: Coding Discipline Feedback
description: Validated approaches from prior sessions; karpathy-skills principles
type: feedback
---

# Coding Discipline — What Works

## Global Principles (Karpathy-Skills)

**Rule**: Surgical changes only — don't refactor, don't add features beyond the task.

**Why:** Code entropy kills projects. Every unnecessary change introduces bugs and debt.

**How to apply:** When fixing a bug or adding a feature, identify the minimal set of files. Touch those only. Leave everything else alone. Don't polish surrounding code unless it blocks the task.

---

**Rule**: Simplicity first — no speculative features, no premature abstractions.

**Why:** Three similar lines are better than a premature abstraction. Future requirements change; today's abstraction often becomes tomorrow's constraint.

**How to apply:** Ask "does this task require this abstraction?" If no, don't build it. Ship the minimal solution that solves the problem stated.

---

**Rule**: Goal-driven execution — every change needs verifiable success criteria and a test loop.

**Why:** "Works on my machine" isn't done. Verification separates shipped code from wish-list code.

**How to apply:** Before writing code, state what "done" looks like. Then write tests that prove it. Don't claim completion without proving it.

---

## Per-Project Overrides

> Add your own project-specific rules here after running `/setup`.

### Example: backend project (Strict)
- No changes without corresponding unit tests
- Migrations are never optional — test them
- Test database hits real schema, not mocks
- Async tasks must have integration tests

### Example: frontend project (Type-Safe)
- Type-check before committing (TypeScript strict mode)
- Component props must be fully typed
- No `any` types without justification
- Build must pass before PR

### Example: portfolio/exploratory project
- TDD not required; design exploration encouraged
- Fast iteration over perfect tests
- Visual verification is acceptable
