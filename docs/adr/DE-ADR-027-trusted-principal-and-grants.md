# DE-ADR-027 — Trusted local principal and server-authorized workflow grants

- **Date:** 2026-09-11 · **Status:** ACCEPTED · **Task:** DE 001R2A

## Context

Policy cannot trust actor roles or workflow grants supplied by API, CLI, fixtures or an
LLM. DE 002 needs a credible identity baseline, but enterprise IAM is outside the MVP.

## Decision

Use one operator-provisioned local account with an Argon2id password hash referenced by
configuration. Login creates an opaque random server-side PostgreSQL session. Browser
authentication uses an HttpOnly, same-site cookie and session-bound CSRF token for
mutations; same-origin SSE is read-only. CLI uses the same login/session API.

Authentication middleware creates immutable `PrincipalRef(authentication_source,
principal_id, roles, session_id)`. Clients cannot set actor, roles or effective grants.
They may request a grant subset; `GrantAuthorizer` derives and persists effective grants
from the trusted principal, role policy, target environment, connector policy and global
disabled set. Actor identity propagates through commands, workflow state, approvals,
attempts and audit.

V1 may assign both `operator` and `approver` roles to the one local principal, but checks
remain distinct. Production remains disabled and cannot be self-approved.

## Alternatives

- Trust grants in workflow creation DTOs: rejected; caller-controlled authorization.
- Full OIDC/enterprise IAM/RBAC administration: deferred; disproportionate to local MVP.
- Browser-stored API token: rejected; poorer secret handling and CSRF/session semantics.

## Consequences

- DE 002A implements auth/grant contracts and tests caller forgery rejection.
- This is explicitly a local single-operator baseline, not a multi-tenant IAM claim.
- Future OIDC can issue the same `PrincipalRef` without changing policy contracts.
