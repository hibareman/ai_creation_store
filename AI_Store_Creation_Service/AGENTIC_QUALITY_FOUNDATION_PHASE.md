# Agentic Semantic Quality — Phase 1 Foundation

## Files changed

- `constants.py`
- `agentic/state.py`
- `agentic/runner.py`
- `AGENTIC_QUALITY_FOUNDATION_PHASE.md`

## Graph topology

Unchanged in this phase. No reviewer or improvement node is active yet.

## State fields

- `quality_review_status`: `not_started`, `passed`, `revision_required`, or
  `revision_applied`.
- `quality_score`: nullable integer from 0 to 100.
- `quality_issues`: strict JSON-serializable semantic issue objects.
- `quality_revision_count`: bounded semantic revision counter.

`MAX_QUALITY_REVISIONS` is fixed at `1` and is independent from structural
`repair_attempt_count`. Passing requires a score of at least `80`, no high or
medium issues, and no semantic revision. At most five bounded issue objects are
stored.

Cached v1 sessions without the new quartet receive safe `not_started`
defaults when they are validated. Partial or malformed quality state fails
closed. A completed one-time improvement uses `revision_applied`, clears the
old score and issues, and records `quality_revision_count = 1` before the
improved draft is reviewed again.

## Routing rules

Unchanged in this phase. Existing unknown routes still fail closed. Later
phases will route technically valid drafts through semantic review and will
require `passed` before final human review/apply. If the single revision cannot
produce a technically and semantically acceptable draft, it will route to
`failed_recoverable`; it cannot return to Quality Improve a second time.

## Feature-flag behavior

Unchanged. The legacy workflow remains the default and LangGraph remains
protected by its existing feature flag, which defaults to `False`.

## Verification

The large automated test suite was intentionally deferred. `python manage.py
check` completed successfully with no reported issues. A focused state-contract
sanity check also confirmed the default counter is `0` and a counter of `2` is
rejected.
