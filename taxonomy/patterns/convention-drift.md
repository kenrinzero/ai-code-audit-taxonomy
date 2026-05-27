---
name: convention-drift
category: consistency
difficulty: medium
generation: evergreen
since_model: null
evidence_grade: observed
---

# Convention Drift

## Code example

A web app's `apps/web/src/lib/actions/` directory has 37 exported read functions across a dozen files. Three different verb conventions live side by side:

```typescript
// apps/web/src/lib/actions/company.ts (30 exports use this verb)
export async function getCompanyBySlug(slug: string): Promise<Company> { ... }
export async function getCompanyPostings(id: string): Promise<Posting[]> { ... }

// apps/web/src/lib/actions/bootstrap.ts (6 exports use this verb)
export async function fetchAppBootstrap(): Promise<BootstrapData> { ... }

// apps/web/src/lib/actions/search.ts (1 export uses this verb)
export async function loadMorePostings(cursor: string): Promise<Posting[]> { ... }
```

Each file is locally consistent — every export in `company.ts` uses `get`, every export in `bootstrap.ts` uses `fetch`. Across files, the conventions drift without rule. New action files mostly use `get` because that is what the rest of the codebase looks like; new `*-page-data.ts` files use `fetch` because that is what their nearest neighbors use; one stray `loadX` lives in a file with `get` siblings.

The defect path is named in the captured specimen:

> rename `getPostingDetail` → `fetchPostingDetail` and the codebase looks consistent for a week; the next new action goes back to `getX` because that's what the rest looks like. Without a rule, every PR re-litigates.

And worse — the drift can produce **real bugs from name collisions**:

```typescript
// apps/web/src/lib/actions/stats.ts:11
export async function getStats(): Promise<SiteStats> { ... }

// apps/web/src/lib/actions/my-jobs-stats.ts:33
export async function getStats(): Promise<MyJobsStats> { ... }
```

A developer or AI agent that imports `getStats` from the wrong path compiles cleanly and ships a dashboard with the wrong data. TypeScript's type system can't disambiguate the two `getStats` because both return JSON-shaped objects that pass each other's annotations.

The pattern has three captured sub-shapes:

- **Function-naming verb-convention drift across sibling files** — `getX` vs `fetchX` vs `loadX` for what should be one verb. 30/6/1 counts across one `actions/` directory. Captured in colophon-group/jobseek#3237.
- **Return-shape convention drift across sibling adapters** — five VLM parsers (`from_qwen_2_5_vl`, `from_qwen_3_vl`, `from_paligemma`, `from_google_gemini_2_0`, `from_google_gemini_2_5`) wrap five different vision-language models; two return `np.empty((0,), dtype=int)` on failed parse, three return `None`. Downstream code branches on `class_id is None` still exist. Captured in roboflow/supervision#2219.
- **Import-style convention drift within a package** — top-level modules use relative imports, `rules/*` use absolute imports, `rules/pipeline.py` mixes both *in the same file*. Captured in eric-tramel/slop-guard#93.

All sub-shapes share the same root mechanism: the model generated each generation context locally, with each context's prior favoring whichever convention was most-frequent in the immediate attention window. Adjacent files (or adjacent lines) share a convention; the codebase as a whole drifts.

## Mechanism

A language model generates each file (and within a file, each function body) in its own attention context. The local attention window favors conventions visible in the immediate surrounding tokens — the imports at the top of the current file, the function signatures of nearby helpers, the test fixtures called by the function. The model's prior for "which verb should this read function use" or "which import style should this file have" is the *locally most-frequent* choice from the attention window, not a *globally consistent* rule.

For most generation tasks this works adequately, because the file being generated has a consistent local style and the new function fits in. The drift emerges when:

1. **Multiple files are generated in different contexts.** Two action files generated weeks apart have different attention windows; the model produces `getX` in one and `fetchX` in another. Neither file is wrong on its own; the codebase as a whole has two conventions for the same thing.
2. **The model has multiple priors and the attention window doesn't decisively favor one.** For "wrap a VLM and return Detections-compatible tuples on failure," the model might have `None`-returning examples and empty-ndarray-returning examples in training data; depending on which is more frequent nearby, it produces one or the other. The Qwen parsers cluster around one prior; the PaliGemma/Gemini parsers cluster around the other.
3. **The file is long enough that the attention context drifts within it.** The slop-guard `rules/pipeline.py` file mixes relative and absolute imports *in the same file* — the model generated some imports with one prior, hit a context-shift trigger (perhaps a new import block, a docstring, or a comment), and resumed with the other prior. Long-file imports are a particular weak point because import statements often appear in distinct blocks with significant other content between them.

This is the meta-mechanism that aabtzu's libertas-travel#48 AI-tells audit captured in plain English:

> AI follows rules locally but doesn't apply them broadly.

The audit's specific examples — `fla` comment violating the project's own naming rule, inline SQL not following the SCREAMING_SNAKE_CASE pattern already established in the same file — are instances of the same root mechanism applied to different surfaces.

The training corpus reinforces the failure mode. Real-world codebases often have multiple conventions (legacy code from different periods, contributions from different teams, copy-pastes from different tutorials). The model has seen all of these as "valid Python code." Without a specific instruction or strong codebase signal, the model produces *plausible-given-this-corpus* code rather than *consistent-with-this-codebase* code. The two are not the same.

Three concrete failure paths are visible in the captured specimens:

**Path 1: Function-naming convention drift across sibling files.** Each file's exports use one verb; across files, three verbs coexist. New code follows the *local* convention (whichever verb is in the same file) without enforcing a *global* convention. The jobseek specimen documents this with 30/6/1 counts and a same-name-different-shape collision (`getStats` × 2 in different files).

**Path 2: Return-shape convention drift across sibling adapters.** Multiple adapters wrap the same kind of upstream API (VLM parsers, LLM client classes, file-format readers). Each adapter is generated in its own context, often conditioned on the upstream API's documentation style. Two halves of the adapter family end up with different conventions for the same field's empty/error representation. Downstream code branches on one convention and behaves wrong with the other.

**Path 3: Import-style or stylistic convention drift within a package.** The model generates some files with one convention (relative imports, full docstrings, four-space indentation) and other files with another (absolute imports, terse docstrings, etc.). Mixing within a single file is the most diagnostic version because it can only have come from local-attention drift, not from any architectural choice.

The defect paths are varied:

1. **Refactor friction.** Every PR re-litigates the convention. The codebase looks consistent for a week after a cleanup, then drifts again.
2. **Test mock complexity.** Mocking `getX` vs `fetchX` requires looking up which file exports it; reviewers have to verify each mock matches the real export.
3. **Same-name collisions.** Two `getStats` in different files with different shapes; a typo in the import path silently ships wrong data.
4. **Type-system invisibility.** Most convention drift doesn't trigger type errors because the conventions are stylistic, not type-level.
5. **Cognitive load on readers.** Every reader has to learn multiple conventions and keep track of which applies where.

This pattern is the **generalized cousin of [`inconsistent-error-handling`](inconsistent-error-handling.md)**. That entry covers error-contract divergence specifically; this entry covers any-convention divergence — naming, return shape, import style, file organization, anything that should be uniform but isn't. The mechanism is identical (local-fluency-without-global-consistency); the surface is broader. The two entries are kept separate because the error-contract case has a distinctive defect path (API contract violations downstream) that earns its own focus.

The pattern is **AI-amplified, not AI-exclusive**. Human-written codebases drift constantly — multi-author projects, codebases that grow over many years, codebases that absorb contributions from different teams. The AI-amplified observation is that AI-generated codebases drift *from initial authorship*, not from accumulated history. The captured specimens are all from relatively young codebases where the drift was present in the first commits rather than introduced by historical accumulation.

## Evidence / incident

Three captured specimens at three different layers (function names, return shapes, import styles), each from a different AI-coded Python or TypeScript project. Specimens live in `evidence/github-issues/`.

- **[colophon-group/jobseek#3237](https://github.com/colophon-group/jobseek/issues/3237)** — function-naming verb-convention drift. `getX` × 30 vs `fetchX` × 6 vs `loadX` × 1 in one `actions/` directory; explicit AGENTS.md present; same-name-different-shape collision (`getStats` × 2) creates a silent-typo failure mode. Audit framework: "audit-architecture." Specimen: [colophon-group-jobseek-3237.md](../../evidence/github-issues/2026-05-15-colophon-group-jobseek-3237.md).
- **[roboflow/supervision#2219](https://github.com/roboflow/supervision/issues/2219)** — return-shape convention drift across sibling VLM parsers. Five parsers wrap five vision-language models; Qwen pair returns `np.empty((0,), dtype=int)`, PaliGemma/Gemini triple returns `None`. Downstream `is None` branches still exist in three sinks. Specimen: [roboflow-supervision-2219.md](../../evidence/github-issues/2026-05-15-roboflow-supervision-2219.md).
- **[eric-tramel/slop-guard#93](https://github.com/eric-tramel/slop-guard/issues/93)** — import-style convention drift within one package; top-level modules use relative imports, `rules/*` use absolute imports, `rules/pipeline.py` mixes both *in the same file*. Project is "Slop Scoring to Stop Slop" — an AI-slop detection tool exhibiting AI-slop convention drift, meta-perfect specimen. Specimen: [eric-tramel-slop-guard-93.md](../../evidence/github-issues/2026-05-15-eric-tramel-slop-guard-93.md).

Three different convention layers (naming / return shape / import style), three different domains (job-search app / CV tooling / AI-slop detector), three different audit frames (architecture audit / design issue / style cleanup). Cross-context coverage is broad.

Supplementary references:

- **aabtzu/libertas-travel#48** AI-tells table contains the canonical statement of the mechanism: *"AI follows rules locally but doesn't apply them broadly."* — applied to specific instances of `fla` comment violating naming rule, inline SQL not following SCREAMING_SNAKE_CASE, and other within-codebase drift. This is the original audit-framework recognition of the meta-pattern.
- **F4CTE/polyforge-sdk-python#42 + #91** — webhook event values flipped between dot.notation and SCREAMING_SNAKE_CASE conventions in successive releases; convention drift across versions rather than across files. Adjacent shape worth noting.
- **wuxixixi/ProjectInsight#2134** — test files use inconsistent naming conventions; broad scope but less specific evidence.

## Detection cues

What to look for in a diff or completion:

- **Multiple sibling files/functions implementing the same conceptual role with different surface conventions.** Look for verb mixing (`getX` vs `fetchX` vs `loadX`); look for return-shape divergence on the empty/error path; look for import-style mixing within a package.
- **Counts of conventions in a directory.** Run `grep -c '^export async function get' apps/web/src/lib/actions/*.ts` vs `^export async function fetch` — if both produce nonzero counts, the directory has drifted.
- **Same-name-different-shape collisions across files.** Two functions with identical names exporting from different files. If a typo in the import path silently compiles to the other function, the collision is a real bug magnet.
- **Mixed conventions within a single file.** A file that has both relative and absolute imports; a file that has both `getX` and `fetchX` functions; a class with both `_private` and `__double_private` attributes. Most diagnostic single-instance shape.
- **Adapter/wrapper classes with split conventions.** Multiple sibling adapters (LLM provider clients, VLM parsers, backend modules) — read each adapter's return values for the same field name across all adapters. If half return one shape and half return another, the convention has drifted across the family.
- **Project AGENTS.md / CLAUDE.md / style-guide says one thing but the code says another.** The codified guidance is correct; the AI code drifted anyway. This is the codified-guidance-is-insufficient observation applied at the convention layer.
- **A renamed identifier that didn't propagate.** A refactor that renamed `loadPostings` → `getPostings` in some files but not others. Half-completed renames are convention drift in slow motion.

The diagnostic question for any candidate: *what convention should be consistent here, and is it?* If the answer is "I don't know, every file does it differently," the convention has drifted. The fix is a cleanup pass plus a documented rule plus (often) a linter to enforce the rule going forward. Codifying without enforcement is observably insufficient.

## Notes

**Category `consistency`** — new category. Previous entries have used `structure`, `testing`, `defensive-programming`, `error-handling`, `control-flow`, `documentation`, `library-usage`, `async`. The new category captures patterns about *uniformity across a codebase* — convention drift is the umbrella; specific sub-categories (naming consistency, error-handling consistency, type consistency) are nested within. [`inconsistent-error-handling`](inconsistent-error-handling.md) could plausibly move to `consistency` at the category-revisit; for now it stays in `error-handling` because the defect path is error-specific.

**Difficulty rated `medium`.** Spotting a single inconsistent identifier or import is easy. Recognizing convention drift as a pattern requires reading across multiple files and counting frequencies. A reader who only audits one file at a time will not flag the pattern; once the reader knows to count conventions in a directory, detection is a quick `grep` away.

**The pattern is AI-amplified, not AI-exclusive.** Human-written codebases drift constantly through multi-author contributions and historical accumulation. The AI-amplified observation is the *initial-state* drift — AI-generated codebases produce convention divergence from the first commits, not as accumulated history. The captured specimens are all from young codebases where the drift was present from the start.

**False-positive shapes.** Be cautious before flagging:

- *Intentional naming conventions that differentiate behaviors.* `getX` for synchronous reads vs `fetchX` for network-bound reads is a legitimate two-tier convention if the difference is documented and enforced. The cue is whether the verb difference encodes a *real semantic distinction* or is just drift.
- *Test files using different conventions from production code.* `test_*` vs `*_test.py` is a common variance that exists for organizational reasons (pytest's default conventions vs Django's). Within either set, consistency is the goal.
- *Code in different languages using their respective conventions.* TypeScript files using camelCase, Python files using snake_case, JSON config using kebab-case. This is multi-language convention, not drift.
- *Adapter classes intentionally normalizing different upstream conventions.* If the adapter's *job* is to translate provider X's naming to the project's convention, the adapter's internals may reflect the upstream convention while the public surface is consistent. The cue is whether the public surface is consistent.
- *Historical patches that haven't been migrated.* A function that uses an old naming convention because it predates the new convention and a migration hasn't run is convention drift in slow motion, but not the AI-generated-initial-state shape.

**Mutation operator hint.** A deterministic mutation that takes a consistent set of N sibling files and changes one to use a different naming/return/import convention produces this pattern from clean code. Variants:

- Take three sibling files each exporting `getX` functions; change one to `fetchX`
- Take a file with all relative imports; change one to absolute
- Take an adapter family that all return `None` on error; change two to return empty containers
- Take a class with all snake_case methods; add a camelCase method
- Take a file with all double-quoted strings; introduce single-quoted strings to half the literals

These mutations compose well with [`inconsistent-error-handling`](inconsistent-error-handling.md) (the error-specific version) and [`narrating-comments`](narrating-comments.md) (a codebase with convention drift often also has WHAT-narration drift — both are local-without-global-enforcement instances).

**Connection to [`codified-guidance-is-insufficient`](../notes/codified-guidance-is-insufficient.md) note.** The jobseek specimen explicitly notes that the project's documentation site (`apps/web/docs/`) does not document the verb convention, and the prescribed fix is *both* documentation *and* eslint enforcement. Documentation alone is insufficient (per the multi-entry observation across this taxonomy); enforcement is the cure. This entry is one of 10+ in the cross-cutting note, with the diagnostic detail that *enforcement is the missing piece* — not just naming the convention but mechanically preventing drift.

**Connection to [`same-project-knows-right-pattern`](../notes/same-project-knows-right-pattern.md) note.** Convention drift is the project-wide version of the per-call-site observation seen in [`swapped-args`](swapped-args.md), [`wrong-tool-for-job`](wrong-tool-for-job.md), and [`sleep-based-synchronization`](sleep-based-synchronization.md). In those entries, the project uses the right pattern at one site and the wrong pattern at another; here, the project uses one *convention* at some sites and another *convention* at others. The local-vs-global tension is the same root mechanism applied at different scales (single-call-site vs whole-directory). The note formalizes this at 9 entries.
