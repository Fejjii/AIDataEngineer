# AIDataEngineer — Architecture

## Current status

**NOT YET DESIGNED**

## Architecture owner

**DE 001**

## Rules for DE 000 and later implementation tasks

Architecture may not be silently invented during DE 000 or during routine implementation.

Until DE 001 produces and the operator accepts an architecture, agents must:

- implement no product backend, frontend, connectors, schemas, APIs, or orchestration;
- not freeze stack choices beyond the directional notes in `PROJECT_CONTEXT.md`;
- surface any architecture temptation as an open question rather than embedding it in code.

## Upcoming architecture task

DE 001 will design the MVP architecture: system boundaries, agent responsibilities, tool
contracts, permission tiers, approval gates, audit logging, Snowflake/dbt/GitHub connector
contracts, and repository structure. Independent review by a higher-tier model is expected
before implementation begins.
