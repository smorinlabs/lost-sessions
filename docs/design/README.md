# Design / requirements specs

Normative documents that specify **what to build and how it must behave** —
feature proposals, conventions, and requirements — before or while implementing.

## Conventions

- **Filename:** `NNNN-kebab-title.md` (zero-padded, sequential).
- **Status header** at the top of each doc: `Status`, `Type`, `Created`, and
  what it `Applies to`.
- **Status lifecycle:** `Draft` → `Proposed` → `Accepted` →
  (`Implemented` | `Superseded` | `Withdrawn`).
- A design doc may **spawn ADRs** for its load-bearing decisions, and may cite
  **research** docs that motivated it. Cross-link them.

## Index

| Doc | Title | Status |
|-----|-------|--------|
| [0003](0003-logging-conventions.md) | Logging conventions — one pipeline, two profiles | Superseded (ADR 0020) |
| [0004](0004-template-press-plan.md) | Template Press — reusable init/post-init engine plan | Accepted |
| [0005](0005-hexagonal-architecture-and-enforcement.md) | Hexagonal architecture & boundary enforcement (the HEX-xx baseline) | Superseded (by 0006) |
| [0006](0006-lost-sessions-plugin-design.md) | lost-sessions plugin design (pluggy, agent and session-manager plugins) | Accepted |
