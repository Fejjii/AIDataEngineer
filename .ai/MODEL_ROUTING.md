# AIDataEngineer — Model Routing

Operational policy distilled from the AI Software Factory Model Routing Protocol.
Recheck official Cursor pricing and availability before changing this policy.

## Principle

Use the lowest-cost model with a high probability of success.

Escalate because of complexity, ambiguity, blast radius, security risk, architectural
impact, or repeated failure.

Do not escalate merely because a task is long.
Do not use Fable or Astra for routine implementation.
Do not allow cheaper implementation models to silently change approved architecture.

Pay premium models to decide what to build and whether it is correct. Use cheaper models
to perform the majority of implementation. Persist expensive reasoning in repository
artifacts so it is not re-derived in every coding session.

Prefer standard speed for autonomous work. Use Fast only when latency has clear value.

## Default hierarchy

```text
Astra → Fable → Sol → Grok / Muse → Composer → Luna / Flash
Think   Review     Hard debug  Build          Implement   Automate cheaply
```

### GPT 6 Astra

Role: External Chief Architect and independent final reviewer.

Typical use: greenfield system reasoning, highest-impact architecture, security reasoning,
major tradeoffs, independent milestone review, final production readiness.

Do not use for boilerplate or well-specified coding.

### Claude Fable 5.1

Role: Principal Engineer inside Cursor.

Typical use: architecture inside Cursor, repository-wide architecture review, complex
refactors, security-sensitive engineering, major migrations, final code review.

Do not use for routine implementation.

### GPT 5.6 Sol

Role: Senior Reasoning Engineer.

Typical use: hard debugging, persistent reasoning failures, complex backend or agentic
investigation.

### Grok 4.6

Role: Senior Implementation Engineer.

Typical use: complex features, data pipelines, connectors, APIs, services, difficult
integrations, substantial debugging, refactoring.

### Muse Spark 1.3

Role: High-value agentic engineer.

Typical use: large repository analysis, multi-step work, parallel Cloud work, repository
investigation.

### Composer 2.5

Role: Primary coding workforce.

Typical use: well-specified implementation, tests, schemas, APIs, routine refactors, CI,
documentation, small features.

Default coding model for this project when the task is well specified.

### Gemini 3.1 Pro

Role: Visual and frontend specialist.

Typical use: UI, screenshots, visual reasoning, frontend analysis.

Pair with Composer for UI implementation.

### GPT 5.6 Luna and Gemini Flash

Role: Low-cost automation workers.

Typical use: formatting, mechanical edits, simple tests, documentation, extraction, bulk
repetitive work.

## Escalation ladder

| Level | Trigger | Model |
|-------|---------|-------|
| 1 | Routine implementation | Composer 2.5 |
| 2 | Complex implementation or first serious debug | Grok 4.6 |
| 3 | Repository-wide investigation or multi-step debug | Muse Spark 1.3 |
| 4 | Hard reasoning or persistent failure | GPT 5.6 Sol |
| 5 | Architecture-sensitive or high-risk engineering | Claude Fable 5.1 |
| 6 | Highest-stakes first-principles decision or independent final review | GPT 6 Astra |

UI and visual work: Gemini 3.1 Pro plus Composer 2.5.

Independent review at architecture freeze, security review, production readiness, and
major migrations should not use the same model that implemented the work.

## Compression rule

After a frontier model finishes major reasoning, persist a compact implementation contract
in `ARCHITECTURE.md`, `DECISIONS.md`, and task notes: decisions, constraints, interfaces,
security rules, acceptance criteria, rejected alternatives, open questions.

Do not paste full frontier conversations into every implementation prompt.

## Indicative spend

Directional, not a quota: Astra/Fable 5–10%; Grok/Sol 15–25%; Muse 20–30%;
Composer/Luna/Flash 40–60%. High-risk work can justify more review. High-volume
implementation should shift toward worker models.
