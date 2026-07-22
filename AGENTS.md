# LangGraph Implementation Rules

## Non-Negotiable Rules
## NON-NEGOTIABLE IMPLEMENTATION RULES
1. The legacy workflow must remain the default behavior.
2. LangGraph must be protected by a feature flag that defaults to `False`.
3. Do not change existing API routes, serializers, status codes, or response contracts.
4. Initial description validation and Draft Store creation must remain outside LangGraph.
5. The graph must start only after `store_id`, `tenant_id`, and `user_id` are available.
6. Store only serializable values in graph state.
7. Do not store Django model instances, `User` objects, QuerySets, database connections, or provider clients in graph state.
8. Every node must have one clear responsibility.
9. Nodes must reuse existing providers, validators, selectors, metadata helpers, and Redis helpers.
10. Do not duplicate existing business logic inside agentic nodes.
11. Do not add final database apply logic inside LangGraph during the foundation phase.
12. Do not change the existing transactional apply flow.
13. Do not add a LangGraph checkpointer yet.
14. Redis remains the current source of truth for draft payload and workflow metadata.
15. Every unknown or unsupported route must fail closed.
16. Unknown routing decisions must produce a safe `failed_recoverable` state.
17. Never select a silent default route for invalid routing values.
18. The `Validate → Repair → Validate` loop must be controlled by `MAX_REPAIR_ATTEMPTS`.
19. Do not rely only on LangGraph recursion limits to stop loops.
20. The Repair node may increment only `repair_attempt_count`.
21. The Repair node must not change `clarification_round_count`.
22. Repair attempts must never exceed `MAX_REPAIR_ATTEMPTS`.
23. Clarification rounds must remain controlled by `MAX_CLARIFICATION_ROUNDS`.
24. Technical exception details must remain in logs and audit records.
25. Graph state and API responses must expose only safe public error messages.
26. Tenant isolation and owner isolation must be preserved in every called service.
27. No node may access a Store using only an unscoped primary-key query.
28. Human Review must not apply database records or change the Store to its final setup state.
29. The `applied` workflow status must remain reserved for the existing successful apply flow.
30. Nodes must be independently testable without a real provider or external network call.
31. Provider calls must be mocked in unit tests.
32. Graph topology and routing must have focused tests.
33. The feature flag must have tests proving that the legacy path remains unchanged when disabled.
34. Existing tests must continue to pass before any phase is merged.
35. Do not delete or replace the legacy workflow until the agentic workflow returns the same public contracts and is fully verified.
36. Implement LangGraph incrementally:

* typed state and graph skeleton
* deterministic routing
* Generate integration
* Validate integration
* Repair loop
* Human Review integration

37. Do not migrate multiple major workflow stages in one uncontrolled change.
38. Do not upgrade unrelated dependencies.
39. Pin or bound the LangGraph dependency to a compatible version.
40. Every implementation phase must document:

* files changed
* graph topology
* state fields
* routing rules
* feature-flag behavior
* test results

## Recommended Project Placement

Place these rules in:

```text
AGENTS.md
```

Use a section named:

```markdown
# LangGraph Implementation Rules
```



