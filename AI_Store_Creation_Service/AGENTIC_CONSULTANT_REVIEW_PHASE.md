# Agentic Semantic Quality — Phase 2 Consultant Review

## Files changed

- `agentic_quality_prompts.py`
- `providers.py`
- `agentic/quality_contracts.py`
- `agentic/quality_reviewing.py`
- `agentic/nodes/consultant_review.py`
- `agentic/nodes/__init__.py`
- `agentic/nodes/validate.py`
- `agentic/nodes/human_review.py`
- `agentic/state.py`
- `agentic/routing.py`
- `agentic/graph.py`
- `agentic/runner.py`
- `agentic_session_services.py`
- `agentic_state_store.py`
- `agentic_production_services.py`
- `AGENTIC_CONSULTANT_REVIEW_PHASE.md`

## Graph topology

```text
Generate
  -> Structural Validate
      -> Repair -> Structural Validate
      -> Consultant Review
          -> Human Review                 (passed)
          -> Recoverable Failure          (revision required or invalid)
```

Quality Improve is intentionally not present in this phase. It will replace
the temporary `revision_required -> failed_recoverable` edge in phase 3.

## Reviewer contract and state

The provider returns exactly `score` and `issues`. It cannot choose the final
workflow status. The backend derives:

- `passed`: score is at least 80 and there are no high or medium issues.
- `revision_required`: score is below 80 or a material issue exists.

The reviewer is read-only. It does not modify `draft_payload` and does not
increment `repair_attempt_count` or `quality_revision_count`. Output is bounded
to five strict issues with supported paths, criteria, severities, and text
lengths. Invalid output receives one bounded corrective retry and then fails
closed. The complete provider user message is escaped, untrusted JSON data;
merchant-controlled text cannot create a new prompt boundary.

Regenerated full and partial drafts pass through the same consultant gate
before replacing the prior cached Agentic draft.

## Routing rules

- Structural validation errors keep using the existing bounded Repair loop.
- A structurally valid draft must enter Consultant Review.
- Only a backend-validated `passed` review can enter Human Review.
- `revision_required`, provider failures, malformed JSON, unsupported fields,
  unknown paths, and inconsistent score/severity combinations fail closed.
- Cached or synthetic ready-for-review states cannot be approved unless their
  quality status is a valid `passed` result.
- An old or invalid Agentic cache envelope remains classified as Agentic and
  cannot silently fall through to Legacy operations.
- Session detection distinguishes `absent`, `present`, and `invalid`; only a
  confirmed `absent` state may use Legacy. Cache errors fail closed.

## Feature flag and public API

The existing Agentic feature flag is unchanged and still defaults to `False`;
the legacy workflow remains the default. No route, serializer, status code, or
public response key was added. Quality details stay in internal JSON state.

## Verification

- `python manage.py check`: passed with no reported issues.
- Focused fake-provider sanity check: strict reviewer parsing returned
  `passed` for a valid score, and the updated graph compiled successfully.
- Corrective-retry sanity check: the first malformed response was rejected and
  the second request carried the corrective retry signal before passing.
- Session-presence sanity check: missing cache state returned `absent` while a
  malformed envelope returned `invalid`, preventing Legacy fallback.
- The large automated test suite remains deferred as requested.
