# DE-ADR-024 — Minimal Vite + React + TypeScript SPA

- **Date:** 2026-09-11 · **Status:** ACCEPTED · **Task:** DE 001

## Context
The MVP needs a simple interface: request, clarification, plan, timeline, artifacts,
validation, repairs, approvals, connector status, metrics. It is built last (DE 016) and
must not dominate effort. Next.js/Tailwind were previous defaults and must be re-evaluated.

## Decision
Vite + React + TypeScript single-page app, React Query for data, SSE for live updates,
Tailwind permitted for speed, no SSR/router framework. Built assets served by the API
image; Vite dev server in development. A Typer CLI covers all flows so the backend is fully
usable before the UI exists.

## Alternatives
- Next.js: rejected — SSR/routing weight not needed for an internal tool.
- HTMX + Jinja: viable and cheaper; rejected because an interactive timeline and approval
  cards are the recruiter-facing surface and TypeScript typing of API DTOs reduces UI bugs.
- Streamlit: prototype-only quality.

## Consequences
- Node toolchain in CI (pnpm, vitest, Playwright smoke).
- UI work can run as a Cloud lane once approval and metrics APIs have reached their baseline (DE-ADR-026).
