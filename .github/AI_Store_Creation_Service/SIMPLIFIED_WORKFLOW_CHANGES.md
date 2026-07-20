# Simplified AI Store Creation Workflow

Active execution path:

`Understand -> Clarify (when needed) -> Merge Answers -> Understand Again -> Generate -> Structural Validation -> Ready for Review`

Removed from the active graph:

- Separate Blueprint node.
- Repair node and repair loop.
- Backend product-domain matching.
- Backend catalog-scope semantic matching.
- Keyword dictionaries and regex-based domain validation.
- Blueprint/personalization validation during final draft validation.

Backend validation is limited to JSON parsing, required structure, data types,
non-empty required values, allowed numeric/length limits, category references,
available templates, workflow state and counters.

AI prompts remain responsible for semantic extraction, missing-field decisions,
question wording, selected language, and semantic consistency of categories and
products.
