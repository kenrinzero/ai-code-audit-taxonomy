# Same-project-knows-right-pattern

The same codebase often uses the right pattern at one site and the wrong pattern at another. The model's prior at each generation context is independent enough to produce both choices.

This is the single most load-bearing cross-cutting observation in the taxonomy's evidence base. It appears in **ten** entries and demonstrates a structural property of AI-generated code that human-paced development rarely produces.

## Where the observation appears

| Entry | Right pattern at | Wrong pattern at |
|-------|------------------|-------------------|
| [`swapped-args`](../patterns/swapped-args.md) | `orchestrator.py:464` calls function with correct argument order | `main.py:1611` calls same function with arguments swapped |
| [`wrong-tool-for-job`](../patterns/wrong-tool-for-job.md) | `hindsight` plist uses named entry-point binary | gateway plist hardcodes `python -m hermes_cli.main` (display becomes "python") |
| [`sleep-based-synchronization`](../patterns/sleep-based-synchronization.md) | WebSocket client used for other features in ha-mcp | `wait_for_entity_registered` polls REST instead of subscribing to events |
| [`convention-drift`](../patterns/convention-drift.md) | 30 functions use `getX` verb correctly | 6 functions use `fetchX`, 1 uses `loadX` for the same role |
| [`print-instead-of-logging`](../patterns/print-instead-of-logging.md) | `stage3_runner.py` uses `logger` throughout | `flow.py` uses 51 `print()` calls and 0 `logger.` calls |
| [`hardcoded-config-values`](../patterns/hardcoded-config-values.md) | Project has context-window resolution chain | `max_tokens` hardcoded, doesn't use the resolution chain |
| [`mutable-default-arguments`](../patterns/mutable-default-arguments.md) | 4 sibling Pydantic state classes use `Field(default_factory=list)` | One sibling state class drifts to bare `List[str] = []` |
| [`missing-network-timeout`](../patterns/missing-network-timeout.md) | Cogtrix `shell.py` has timeout protection; `http_request.py` clamps timeouts | Cogtrix `github_tools.py` has 4 `subprocess.run` calls with no `timeout=` |
| [`f-string-in-logger-call`](../patterns/f-string-in-logger-call.md) | gen-ai-ops codebase uses `%`-style consistently | One file (`client_routes.py:28`) drifts to f-string |
| [`async-await-mismatch`](../patterns/async-await-mismatch.md) | Prior PR A6 in coachiq fixed missing-awaits at v1→v2 cutover sites | SecurityWebSocketHandler stats + recent-events sites left unfixed; partial-fix-propagation extends with a third specimen |

Across these entries the observation scales from single-call-site (swapped-args) to per-file (print-instead-of-logging) to per-directory (convention-drift) to per-module (hardcoded-config-values). The fix-PR-boundary variant — the right pattern at sites a prior fix touched, the wrong pattern at sibling sites — has been promoted to its own note: [`partial-fix-propagation`](partial-fix-propagation.md).

One adjacent sub-shape is well-attested: **Pydantic / framework-specific drift**: the right pattern is a framework idiom (Pydantic's `Field(default_factory=...)`, Flask's `render_template`, etc.); the wrong pattern is the language-level shortcut. Captured in mutable-default-arguments (Quibo) where four Pydantic siblings use `Field(default_factory=list)` and one drifts to `List[str] = []`.

The fix-PR-boundary variant — once a sub-shape of this note — is now its own note: [`partial-fix-propagation`](partial-fix-propagation.md). It shares the local-attention mechanism documented below but adds a fix-PR-step-specific audit move and a distinct human-vs-AI differential.

## Mechanism

A language model generates each piece of code in its own attention context. The context contains the immediately surrounding tokens — the function signature being written, the nearby helpers, recently-seen imports, the docstring above the current function. The model's prior for "what shape should this code take" is shaped by *the local attention window*, not by *the codebase as a whole*.

When the model generates two related pieces of code in different attention contexts — two function call sites, two adjacent module files, two parallel adapter classes — each context produces its own prior. If the priors agree, the code is consistent. If the priors disagree, the codebase ends up with both the right pattern and the wrong pattern *living together*.

The disagreement is not random. It is driven by what the model has most recently attended to:

- A function call written immediately after seeing the function's signature is more likely to get the argument order right.
- A function call written far from the signature, with intervening unrelated code, is more likely to draw on the model's general prior about argument order (which is shaped by the corpus, not the local function).
- A file generated when the surrounding files use `logger` is more likely to use `logger`; a file generated when the surrounding files use `print` is more likely to use `print`.
- A function generated when the function's caller has just been written may use the caller's local variable order; a function generated independently may use the corpus-canonical order.
- A class generated when the surrounding classes use `Field(default_factory=list)` is more likely to use that idiom; a class generated outside that context falls back on the language-default bare list.

The mechanism is *local-fluency-without-global-consistency*. Each local generation step is fluent — the code at the wrong site is locally plausible, type-correct, syntactically valid. The cross-site inconsistency is the AI-amplified shape.

## Why this differs from human-paced drift

Human developers also produce inconsistency across a codebase, particularly in long-lived multi-author projects. But human-paced drift has a different shape:

- Human drift is *accumulated over time*: an early developer wrote one convention, a later developer extended a different convention, the codebase drifted as authorship changed.
- AI-amplified drift is *present from initial authorship*: the same model in the same session produced different choices for the same architectural question, because each generation step's attention context was different.

The captured specimens are all from young codebases where the drift was the *initial state*, not the result of historical accumulation. This is the AI-amplified differential: not that AI produces drift (humans do too), but that AI produces drift *at the moment of first writing*, before any second author or refactor pass has touched the code.

The same local-attention mechanism extends to fix-PRs: when the AI fixes one site, sibling sites outside the PR scope are not naturally surfaced. This is documented separately in the [`partial-fix-propagation`](partial-fix-propagation.md) note, which carries the fix-PR-step-specific evidence and the human-vs-AI differential particular to fix-PRs.

## Diagnostic use

The observation provides a fast audit move: *find one correct instance of the pattern, then check whether other sites match*. The right pattern usually exists somewhere in the codebase — the WebSocket client is imported elsewhere, the resolution chain is defined for context-window, the logger is used in `stage3_runner.py`, the Pydantic `Field(default_factory=list)` is used at four sibling classes, `timeout=` is set in `shell.py`. Once the right pattern is located, the audit is a grep-and-compare: which sites use it, which sites don't.

This is much faster than auditing each site against external reference (a style guide, a documentation page, an internet best-practice). The right pattern is local to the codebase; the audit can be local too.

For partial-fix-propagation: read the most recent fix-PR addressing the pattern, identify which files were touched, and check the sibling files in the same directory tree for unaddressed instances. The sibling files that weren't part of the PR's scope are the high-likelihood drift sites.

## Implications

For readers of AI-generated code:

- Always look for the *correct* pattern in the codebase first; the wrong pattern is the deviation
- Cross-file comparison is more diagnostic than within-file review for this class of pattern
- "How does this site differ from the right one elsewhere?" is the load-bearing question
- For codebases with recent fix-PRs, read the PR's scope and check sibling files (see [`partial-fix-propagation`](partial-fix-propagation.md))

For projects using AI-assisted development:

- Linters that enforce within-codebase consistency (rather than against external style) are the practical cure
- Test fixtures that exercise multiple call sites can catch some of the divergent cases
- Code-review checklists that include "is this pattern consistent with how it's used elsewhere?" elevate this audit step
- When fixing a pattern at one site, mechanically grep the codebase for sibling instances and fix them all in one PR

For the calibration training:

- This observation is at the core of how AI-generated code differs from human-written code structurally
- Drills that show two code sites and ask "do these agree?" train the diagnostic skill directly
- With 9+ entries demonstrating the observation, the calibration value is high — readers who internalize this single check will catch a large fraction of AI-typical drift

## Promotion criteria

This observation has been documented in nine entries and is robust enough that elevation to a top-level taxonomy concept is now justified at the eventual category-revisit. The mechanism (local-fluency-without-global-consistency) is more fundamental than any individual entry. A future restructuring could organize the taxonomy partly by mechanism (this being one) and partly by surface.

For now, it lives as a note. If a tenth entry demonstrates the observation on a new surface, this note should be expanded.

The partial-fix-propagation sub-shape — once tracked here as a candidate for standalone-note promotion — was promoted on 2026-05-25 after the coachiq PR A6 specimen brought the count to three. It now lives at [`partial-fix-propagation`](partial-fix-propagation.md). This note retains the broader same-project-knows-right-pattern observation it sits inside.
