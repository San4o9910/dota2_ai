# Learning content recovery — 2026-09-09

## Delivered content

- 15 long-form original lessons: three per position, approximately 670–720 words per module. Each module contains three explained sections, a worked episode, a changed-condition counterexample, common errors, a replay drill, and self-check questions. Their stage pairs cover all six curriculum stages exactly once per position.
- 163 authored practice situations: 43 existing cases with expanded feedback and 120 new cases. New cases contain four explained alternatives, theory, decision steps, a worked example, a trap, a replay exercise, and a counterfactual. All 51 advanced cases include a separate changed-condition question.
- Every position × difficulty × topic group contains at least five distinct scenarios (observed range: five to nine). Default sessions can use ten decisions across topics; narrower topic selections honestly use the available group without importing incompatible roles or difficulties.

## Recovery provenance

The shared authoring filesystem disconnected after all 15 lessons and several scenario batches had been written. The completed lesson JSON was reconstructed from the successful authoring inputs, with minor wording and typo corrections; a byte-for-byte comparison against the offline local file was unavailable.

The lane batch was recovered from the successful authoring inputs with a strict parser and the separately preserved advanced support JSON. The map batch's first 20 cases were recovered with editorial rewriting of the original authored situations; this is explicitly not a byte-identical filesystem recovery. Item/fight cases were recovered from authored source and the preserved advanced tail. During integration, the correct and former-plan explanations in 20 advanced variations were rewritten to explain the actual changed fact instead of generic variation wording. The original 43 cases retain their IDs and answers and now include authored teaching notes and replay tasks.

Source recovery blobs: lane `e42d90709aeb3839b78d10e12e1e3e3f020afeea`; map `b382bda258571bb5d198ae2699f8eaf33c3daafd`; items/fights `ceac41ffc3bdd714ed006cb6e89d294252373dc9`. Integrated catalog blob: `a23115d42b04fc14a1d13e11a039430d28f5a377`.

## Checks performed

The actual `practice.js` catalog validator, filter, and session constructor from candidate `111a1fb7caf1b960e5cede9099ab4f8856bafaa9` ran against all 163 cases in V8. Only ES-module export syntax and `import.meta.url` were adapted for the execution wrapper; validation and session functions were unchanged. All catalog field caps, identifiers, answers, and role/difficulty/topic coverage passed. Sixty narrow sessions were checked for role, difficulty, and topic leakage. All cases have the required expanded teaching fields; all advanced cases have variations. The final catalog contains 755,658 Unicode characters, below the client limit.

The 15-lesson structure and one-module-per-position/stage mapping were checked separately. Content is original instructional writing, not a promise of rank gains or a statistical meta ranking. Full integration, browser, and native server checks remain the release owner's separate gates; this content checkpoint itself does not deploy production.
