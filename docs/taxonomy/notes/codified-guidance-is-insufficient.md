# Codified-guidance-is-insufficient

Projects with explicit codified conventions against specific AI-typical patterns continue to produce those patterns. The codification exists *because* of the pattern, not as a preventative.

## Where the observation appears

Sixteen+ entries demonstrate this:

| Entry | Codified guidance | AI violations |
|-------|-------------------|---------------|
| [`unreachable-defensive-guard`](../patterns/unreachable-defensive-guard.md) | aabtzu CLAUDE.md ("Belt and suspenders reads as un-confident") | abstract reference in audit |
| [`unjustified-lazy-import`](../patterns/unjustified-lazy-import.md) | aabtzu CLAUDE.md ("lazy import only for circular dep + `# circular`") | ~12 instances |
| [`swallowed-exceptions`](../patterns/swallowed-exceptions.md) | Mzzkc `constraints.yaml` MN-007 ("NEVER silence errors without explanation") | 125 instances |
| [`swallowed-exceptions`](../patterns/swallowed-exceptions.md) | pollypm (ruff `BLE001` enabled) | 1,066 instances (silenced via `# noqa`) |
| [`narrating-comments`](../patterns/narrating-comments.md) | StefanBS CLAUDE.md ("Don't explain WHAT") | accreted across migration |
| [`wrong-tool-for-job`](../patterns/wrong-tool-for-job.md) | aabtzu#48 AI-tells table (`.format()` for HTML flagged) | continued in str.format → brace-escape bug |
| [`convention-drift`](../patterns/convention-drift.md) | jobseek AGENTS.md exists; specific verb convention undocumented | 30/6/1 verb drift across action files |
| [`print-instead-of-logging`](../patterns/print-instead-of-logging.md) | aabtzu#48 includes print-to-logging conversion as remediation | continued use across multiple projects |
| [`hardcoded-config-values`](../patterns/hardcoded-config-values.md) | ContentEngineAI's Pydantic typed-config convention | scraper module holds out (68 sites) |
| [`mutable-default-arguments`](../patterns/mutable-default-arguments.md) | ruff `B006` / Pylint `W0102` community lint rules; LlamaFactory CLAUDE.md mentions ruff in CI | 4 clustered instances despite ruff in CI |
| [`mutable-default-arguments`](../patterns/mutable-default-arguments.md) | Quibo project uses `Field(default_factory=list)` in 4 of 5 state classes (convention by majority) | one state class drifts to bare `List[str] = []` |
| [`f-string-in-logger-call`](../patterns/f-string-in-logger-call.md) | IBM AGENTS.md "Lazy logging style preferred"; ruff `G004` / Pylint `W1203` rules exist | ~1000+ violations across `mcpgateway/services/` |
| [`assert-for-runtime-validation`](../patterns/assert-for-runtime-validation.md) | Bandit `B101` / Ruff equivalent + Python docs warn against asserts in production | 2,693 instances across 185 files in amplihack despite CLAUDE.md |
| [`async-await-mismatch`](../patterns/async-await-mismatch.md) | SonarCloud `S7503` / Ruff `RUF029` / pyright strict mode catch unnecessary-async + missing-await | 51 unnecessary-asyncs in agentculture; partial-fix-propagation in coachiq |
| [`resource-leak-no-context-manager`](../patterns/resource-leak-no-context-manager.md) | Ruff `SIM115` + PEP 343 (context managers, 2005) | 3 sites in agno (CLAUDE.md present); producer-consumer-split in litellm |
| [`string-built-sql`](../patterns/string-built-sql.md) | Bandit `B608` + OWASP guidance + Python docs warn against string-built SQL | SQL injection in agent-tool-surface despite CLAUDE.md coding standards |
| [`tarfile-extractall-without-filter`](../patterns/tarfile-extractall-without-filter.md) | Bandit `B202` + Python 3.12 DeprecationWarning + CVE-2007-4559 (open since 2007) + PEP 706 (2024) | 2026-03-16 batch audit caught bandit's own example file; AI codebases still produce pre-filter form |
| [`shell-true-subprocess-injection`](../patterns/shell-true-subprocess-injection.md) | Bandit `B602`/`B604`/`B605` + OWASP Command Injection + CWE-78 | shell=True at agent TUI gateway, LLM-output-direct-to-shell, compound shape with swallowed-exception bypass |

The pattern is now visible across three forms of codification:

1. **Project documentation (CLAUDE.md / AGENTS.md / constraints.yaml / style guides)** — aabtzu, Mzzkc, StefanBS, jobseek, ContentEngineAI, IBM — convention documented in a project-internal file; AI produces the violation anyway.
2. **Community lint rules** — ruff `BLE001`, `B006`, `G004`, `PLC0415`; Pylint `W0102`, `W1203`; bandit `B113`, `B105`, `B110` — convention enforced by widely-adopted tooling; AI produces violations at unusual density.
3. **Within-codebase precedent** — same-project-knows-right-pattern instances where the *correct* idiom is the project's majority usage (4 of 5 Pydantic siblings; the rest of the codebase); the AI drifts despite the visible precedent.

## Mechanism

A language model generates each piece of code in a local attention context. The context contains the immediately-surrounding tokens, the function being generated, the recent test fixtures, the visible imports. Project-level documentation files (CLAUDE.md, AGENTS.md, `constraints.yaml`, style guides) live *outside* the local generation context unless they happen to be in the model's visible context window during the specific generation step.

The model is *capable* of consulting CLAUDE.md when asked directly. What it does not reliably do during local generation is consult the project's codified conventions strongly enough to override the corpus-default behavior. The corpus's pull is heavier than the project's documentation's pull. The model produces corpus-plausible code, then a later audit catches that the code violates the project's documented convention.

This is consistent with how attention-based language models work in general: the local context dominates global context. Project-level conventions are global context; they need to be either constantly re-read by the model or operationalized through enforcement mechanisms (linters, CI checks, type errors).

Community lint rules are themselves an *implicit* codification — the rule's existence and adoption is a community-level statement that the pattern is undesirable. The fact that the rules exist with broad adoption across the Python ecosystem is itself evidence that the patterns they catch are widespread. The AI-amplified observation is that the rules fire at higher density on AI-generated code than on human-paced development, *because* the AI defaults to the patterns the rules catch.

A particularly diagnostic instance is the **rule-silenced-rather-than-fixed** pattern: the project enables a lint rule (correct), the rule fires on AI-generated code (correct), and the developer (or AI agent) responds by suppressing the rule annotation-by-annotation rather than fixing the underlying code. The pollypm case (1,066 `# noqa: BLE001` annotations) is the canonical instance; smaller-scale instances appear elsewhere.

## The cure is enforcement, not codification

Across the captured specimens, the prescribed fix is consistently *enforcement* rather than additional documentation:

- jobseek prescribes both documentation *and* an eslint rule
- pollypm has ruff `BLE001` enabled — the rule fired 1,066 times and was silenced via `# noqa`; the cure is removing the noqa annotations
- ContentEngineAI prescribes migration to Pydantic with `extra = "forbid"` — load-time validation that fails on misspelled keys
- IBM prescribes adding `G004` to `.pre-commit-config.yaml` plus a one-shot codemod (`flynt` or libcst)
- LlamaFactory's ruff config already includes general rules; the cure is enabling B006 specifically
- Multiple specimens recommend pre-commit hooks, CI checks, or type-error-producing constructs

Documentation tells the developer (or the AI agent reading the docs) what to do. Enforcement tells the *code* what to do, by failing builds, tests, or commits when the pattern appears. Only the second one is reliable against the corpus-default pull.

The within-codebase-precedent case is interesting: the precedent exists *in the code itself*, available to be read by the model. Yet the model drifts. This is the strongest evidence that the codified-guidance-is-insufficient mechanism is genuinely about the *local-attention limitation* rather than about whether the guidance is "visible" or "documented." Even when the right pattern is in the next file over, the model can produce the wrong pattern at the current generation site.

## Implications

For readers of AI-generated code:

- Read CLAUDE.md / AGENTS.md / project style guides as *signals of what the project's authors want*, but do not treat them as predictions of what the AI-generated code looks like
- The presence of a codified rule against pattern X is mild evidence that the project has hit pattern X — a useful diagnostic signal in itself
- Lint-rule configurations (ruff, pylint, mypy, pyright) are similarly diagnostic — rules enabled but not enforced (suppressions accumulating) signal the codified-guidance-insufficient shape

For projects using AI-assisted development:

- Linters > documentation > nothing, in that order of effectiveness
- For each AI-typical pattern the project wants to prevent, the question to ask is "what mechanical check would prevent this?" (a ruff rule, a pyright check, a custom lint rule, a CI test, a pre-commit hook). Documenting the rule without that check is observably insufficient.
- The aabtzu/CLAUDE.md, Mzzkc/constraints.yaml, StefanBS/CLAUDE.md, IBM AGENTS.md patterns are all admirable in intent and observably insufficient in effect. The projects that codified the rule *also* hit the rule's violation in production code.
- Run new codemods + linter additions *together* — codify the rule, fix the existing violations, add the lint check in CI. The IBM specimen's proposed remediation captures this three-step shape exactly.

For readers learning to audit AI-generated code:

- A reader who sees a project with a documented convention should expect AI-generated code in that project to *partially* follow the convention — most generated code agrees with the convention, but drift sites exist
- The cross-cutting observation reinforces that AI-generated code is *not* well-served by reading the project's documentation as a substitute for reading the code

## Why this is a note, not an entry

The underlying defect is *the project's codified rule being ignored*, which is more of a structural property of AI-assisted development than a defect class with its own mechanism. The entries it appears in cover the specific defects the codification was meant to prevent.

With 16+ entries participating, this is the most broadly-connected note in the taxonomy — it touches nearly every category.

Two sub-shapes sit close to the surface of this note:

1. **Rule-silenced-rather-than-fixed** (`# noqa: BLE001` × 1,066 in pollypm; `# noqa: F401` × 388 in microsoft/apm; mixed `noqa` + `type: ignore` in Red Hat AI sdg_hub; mixed `nosec` + `noqa` in endavis/infrafoundry) — currently a sub-pattern within swallowed-exceptions.

2. **Partial-fix-propagation** (IBM precursor #1837 → broader migration unaddressed; Dagster prior #17831 → developer-CLI path unaddressed; coachiq PR A6 → SecurityWebSocketHandler-and-dashboard sites explicitly deferred) — its own note: [`partial-fix-propagation`](partial-fix-propagation.md).
