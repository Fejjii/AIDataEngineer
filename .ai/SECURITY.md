# Workflow: SECURITY

Read `.ai/MASTER.md`, `.ai/MASTER_WORKFLOW.md`, and `.ai/ENVIRONMENTS.md` first.

## Rules

- Never print or commit secrets. Variable names only.
- Real `.env*` files stay gitignored. Only example templates may be tracked.
- Sanitize external inputs. Least privilege. Fail closed on ambiguity.
- Production data mutation and production deploys are human-gated.
- Independent review for high-risk changes: Fable 5.1, then Astra when stakes are highest.
- Do not weaken approval gates, audit logging, or environment separation.

## When a secret is required

1. Set `HANDOFF.md` to `REVIEW_REQUIRED`.
2. State the environment-variable name and where the operator enters it.
3. Do not ask for the value in chat.
4. Resume after confirmation.

## Checklist

1. Secrets from env/secret manager only; no literals in code, docs, or handoffs.
2. Least-privilege connectors and scoped tool allow lists (when product exists).
3. Auditability for sensitive actions.
4. Tests for refusal and failure paths.
5. Record decisions in `DECISIONS.md`; regenerate handoff; sync on Local Mac.

## Finding format

Severity, evidence, affected files, impact, remediation, validation.
