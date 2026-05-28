---
name: f-string-in-logger-call
category: observability
difficulty: low
generation: evergreen
since_model: null
evidence_grade: observed
---

# F-String In Logger Call

## Code example

```python
import logging
logger = logging.getLogger(__name__)


def process_request(request, tenant_id):
    logger.info(f"Processing request {request.id} for tenant {tenant_id}")
    try:
        result = handle(request)
    except Exception as e:
        logger.error(f"Failed to process {request.id}: {e}")
        raise
    logger.debug(f"Request {request.id} produced {len(result.items)} items")
    return result
```

Every log call uses an f-string. The strings are *eagerly interpolated* at call time, before the logger has decided whether the message will actually be emitted at the current log level. When the deployment runs at WARNING or ERROR level, the INFO and DEBUG f-strings are still formatted — Python evaluates `f"Processing request {request.id} for tenant {tenant_id}"` even though the resulting string is then discarded by the logging library.

The tightened version uses **lazy `%`-style interpolation**:

```python
import logging
logger = logging.getLogger(__name__)


def process_request(request, tenant_id):
    logger.info("Processing request %s for tenant %s", request.id, tenant_id)
    try:
        result = handle(request)
    except Exception:
        logger.exception("Failed to process %s", request.id)
        raise
    logger.debug("Request %s produced %d items", request.id, len(result.items))
    return result
```

The `%s` / `%d` placeholders are templates; the substitution is performed inside the logger's `Formatter` *only if* the message will be emitted. At runtime, `logger.info("foo %s", x)` evaluates whether INFO is enabled before formatting. The f-string form has no way to defer this — the f-string is interpolated by the Python parser before the function call.

The defect has three components, all real:

1. **Performance**: every f-string log call pays the formatting cost regardless of log level. For high-frequency loggers in production at WARN+ level, this is wasted CPU. Negligible per call; nontrivial in aggregate (the IBM specimen has ~1000+ such calls in one service tree).
2. **Structured-log aggregation broken**: log aggregators (Datadog, Sentry, ELK, Splunk, CloudWatch Insights) index log messages by their *template*. `logger.info("Processing request %s", request.id)` aggregates under one template across thousands of distinct requests. With f-strings, each call produces a unique pre-formatted string, and template-based aggregation collapses to per-message instances.
3. **Loss of structured-attribute extraction**: the logger's `extra=` kwarg and structured-formatter pipelines work on the template + args, not on the pre-formatted f-string. Many production observability features assume the template form.

The use of `logger.exception` instead of `logger.error(f"Failed: {e}")` is a separate but related improvement — `logger.exception` automatically captures the traceback, which the f-string form drops.

The pattern has several visible sub-shapes in captured specimens:

- **Codebase-scale clustering** — ~1000+ `logger.<level>(f"...")` calls across one service tree, with per-file densities of 133 / 59 / dozens-each. Captured in IBM/mcp-context-forge#4617. The project's AGENTS.md *explicitly says* lazy logging is preferred — codified-guidance-is-insufficient at extreme scale.
- **Medium-scale codebase clustering** — 148 calls across 27 files in a project's `backend/` tree. Captured in wuxixixi/ProjectInsight#1954 with Chinese-locale log messages (the pattern is language-of-log-message-agnostic).
- **Single-site drift in same-project-knows-right-pattern** — one file uses f-string while the rest of the codebase consistently uses `%`-style. Captured in knowitcz/gen-ai-ops-04-30#48 via the **"Hledac → Oponent → Soudce"** Czech-language multi-stage AI audit pipeline (15th distinct audit framework).
- **Half-completed-propagation of a prior fix** — a prior PR migrated two specific hot paths; ~1000 sibling-module sites remained. Captured as part of IBM/mcp-context-forge#4617 (precursor #1837 fixed `sse_transport.py` and `resource_service.py` only).

All sub-shapes share the same root mechanism: the model defaulted to f-string interpolation — the most fluent Python string-formatting idiom — for log message construction, regardless of whether the log call would actually be evaluated.

## Mechanism

A language model generates each `logger.<level>(...)` call in a local context. The training corpus contains both shapes:

- **Defective**: `logger.info(f"...{x}...")`. F-strings became Python's most-recommended string-formatting idiom after PEP 498 (Python 3.6, 2016). Modern Python tutorials, books, and Stack Overflow answers almost universally use f-strings for string construction. The model has seen f-strings as the *default* way to build a string in modern Python.
- **Correct (for logging)**: `logger.info("...%s...", x)`. The `%`-style placeholder form is the historical Python logging idiom, predating f-strings. The `logging` module's documentation has always recommended this form for *lazy formatting* reasons. It looks older and less Pythonic to readers calibrated for f-strings as the modern default.

The model's prior strongly favors f-strings as the "modern Python" form. When generating a log call, the local-attention generation step produces `logger.info(f"...")` because that's the form that most-frequently follows `logger.info(` in modern Python corpus segments. The `%`-style form is over-represented in older training data (Python 2 / pre-2016 Python 3) and under-represented in newer training data.

This is a particularly clean instance of the **AI-pedagogical-bias** mechanism (see [`taxonomy/notes/ai-pedagogical-bias.md`](../notes/ai-pedagogical-bias.md)): the corpus's modern Python tutorial style overwhelmingly favors f-strings; production logging is one of the few domains where the older `%`-style remains the correct choice. The model inherits the modern tutorial style and applies it where the production-appropriate idiom is the older one.

There is a corpus-specific reinforcement: **the Python documentation's `logging` cookbook still uses the `%`-style form**, but the cookbook is itself a small fraction of the Python logging code in the wild. Most published examples of Python logging — blog posts, repository code, application snippets — use f-strings because they look cleaner and the performance/aggregation costs are usually invisible in the example context. The cookbook's recommendation is over-ridden by the corpus's dominant practice.

Three concrete failure paths are visible in the captured specimens:

**Path 1: Codebase-scale clustering with codified-guidance-is-insufficient.** IBM/mcp-context-forge has AGENTS.md *explicitly* requesting lazy logging style. The project has a prior fix-PR (#1837) that migrated two specific hot paths. The broader codebase still has ~1000+ f-string log calls. The convention exists; it has not been mechanically enforced. The model produced the corpus-default form (f-strings) at every generation site, and the AGENTS.md convention did not override the corpus-default at generation time.

**Path 2: Mid-scale clustering at sticky-local-pattern density.** wuxixixi/ProjectInsight has 148 logger f-string calls across 27 files in `backend/`. The model produced f-strings uniformly across the codebase — once the local-attention context contained an f-string log call, the next 147 followed the same template. The non-English locale (Chinese log messages) is orthogonal to the pattern, confirming the mechanism is at the *primitive choice* layer (f-string vs `%`-style) rather than the *message content* layer.

**Path 3: Single-site drift surfaced by an AI audit pipeline.** knowitcz/gen-ai-ops-04-30 has one f-string log call in `client_routes.py:28` while the rest of the codebase uses `%`-style. The Hledac/Oponent/Soudce automated AI quality pipeline (finder → opponent → judge) detected the drift. This is the **same-project-knows-right-pattern** mechanism: the model knew the right form in most files; one file drifted. The discovery is itself AI-on-AI auditing — an AI pipeline finding an AI-generated drift.

The training corpus also reinforces the failure mode in a meta way: **community lint rules exist precisely because the pattern is widespread**. Ruff's `G004` (`logging-f-string`) and Pylint's `W1203` (`logging-fstring-interpolation`) are widely-adopted rules that explicitly flag this pattern. The rules exist *because* the broader Python community recognizes f-string logging as a defect class. The AI-amplified observation is that AI-generated codebases trigger these rules at unusual density and produce the pattern despite documented project conventions against it.

This pattern is the **lazy-formatting cousin of [`print-instead-of-logging`](print-instead-of-logging.md)**. Both stem from the model producing a string-output primitive without considering the deployment-context cost. Print-instead-of-logging uses the wrong I/O primitive entirely (print vs logger); f-string-in-logger uses the right I/O primitive but the wrong string-construction idiom within it. Both are AI-pedagogical-bias members applied at adjacent surfaces.

The pattern is **AI-amplified, not AI-exclusive**. Human Python programmers write f-string log calls constantly — particularly Python developers who adopted f-strings after PEP 498 and never re-internalized the lazy-formatting recommendation. The AI-amplified differential rests on:

1. **Density and scale**: ~1000+ instances in one IBM project, 148 in one ProjectInsight project. These densities are uncommon in human-written codebases unless an entire team has the same blind spot.
2. **Codified-guidance-is-insufficient at scale**: IBM's AGENTS.md *says* to use lazy logging and the codebase has ~1000+ violations despite the documented convention. The convention exists *because* the pattern is recurring.
3. **Persistence across half-completed fixes**: the IBM precursor #1837 migrated two specific hot paths; sibling modules remain unaddressed. This is the **partial-fix-propagation** shape applied to lazy-logging conventions.

## Evidence / incident

Three captured specimens, each from a different AI-coded Python project. Detailed specimen notes are not included in the public repository.

- **[IBM/mcp-context-forge#4617](https://github.com/IBM/mcp-context-forge/issues/4617)** — codebase-scale clustering with codified-guidance-is-insufficient at extreme density. ~1000+ `logger.<level>(f"...")` calls across `mcpgateway/services/`. Per-file densities: 133 in `gateway_service.py`, 59 in `tool_service.py`, dozens more across ~50 sibling modules. Project AGENTS.md (22KB) explicitly states "Lazy logging style preferred." Precursor fix #1837 (closed Jan 2026) migrated two specific hot paths; broader codebase still has the pattern. IBM-organization project; substantial enterprise MCP-tooling.
- **[wuxixixi/ProjectInsight#1954](https://github.com/wuxixixi/ProjectInsight/issues/1954)** — mid-scale clustering at codebase scale. 148 logger calls across 27 files in `backend/`. Chinese-locale log messages (`logger.info(f"模拟已启动, LLM模式: {use_llm}")`) — confirms the pattern is independent of log-message language. Self-audit by maintainer.
- **[knowitcz/gen-ai-ops-04-30#48](https://github.com/knowitcz/gen-ai-ops-04-30/issues/48)** — single-site drift surfaced by an **AI quality pipeline**. Hledac (finder) → Oponent (opponent) → Soudce (judge) — three-stage Czech-language adversarial AI audit pipeline. Bug ID F014, verdict VALID. Rest of the codebase uses `%`-style; one file drifted. 15th distinct audit framework captured in the taxonomy's evidence base.

Three different scales (1000+ / 148 / 1), three different project domains (IBM enterprise MCP server / Chinese-locale backend / gen-AI ops automation), three different audit framings (IBM project-internal CHORE / Chinese-language self-audit / automated AI audit pipeline). The three scales span four orders of magnitude — useful range evidence for the AI-amplification claim.

Supplementary references:

- **[mozilla/bugbug](https://github.com/mozilla/bugbug/issues/?)** "Enable Ruff lint rule G004 (logging-f-string)" — 2026-03-13. Mozilla data project enabling the lint rule as a cleanup measure. Independent identification of the pattern by a non-AI-coded project, suggesting the pattern is recognized as a defect class beyond AI-only contexts.
- **[boaznahum/cubesolve](https://github.com/boaznahum/cubesolve)** "Clean up logging: fix eager f-strings in log_lazy/debug_lazy" — 2026-03-28. Includes a project-specific `log_lazy` / `debug_lazy` shorthand for lazy logging; the audit identifies the f-string drift even where the project has a custom lazy-logging idiom.
- **[reactive-firewall-org/multicast](https://github.com/reactive-firewall-org/multicast)** "Ignore select style RUFF warnings in config" — 2025-04-14. A counter-instance: project explicitly *suppressed* G004 in ruff config. Worth noting as a false-positive shape (project intentionally accepts the performance cost; the suppression is documented).
- **[aabtzu/libertas-travel#48](https://github.com/aabtzu/libertas-travel)** AI-tells audit includes in remediation list: *"Convert `print()` calls to `logging` (mapper.py has 17, several other files). Already in MEMORY/cleanup."* The print→logger migration is adjacent to this entry's f-string→`%`-style migration; both are tutorial-style-in-production fixes.

Ruff has rule **G004** (`logging-f-string`) and Pylint has **W1203** (`logging-fstring-interpolation`). Both are widely-adopted community lint rules, evidence the pattern is recognized as a defect class independent of AI authorship. As with mutable-default-arguments' ruff B006 and missing-network-timeout's bandit S113, the AI-amplified observation is that AI-generated codebases trigger these rules at unusually high densities.

## Detection cues

What to look for in a diff or completion:

- **`logger.<level>(f"...")` calls** — the canonical defective form. Any of `logger.debug(f"...")`, `logger.info(f"...")`, `logger.warning(f"...")`, `logger.error(f"...")`, `logger.critical(f"...")`. The substring `(f"` or `(f'` inside any logger method call is the surface signal.
- **`logger.<level>("...".format(...))` calls** — the `str.format()` variant of the same defect. Same eager-formatting problem; same fix.
- **`logger.<level>("..." + var + "...")` calls** — string-concatenation variant. Eager construction; same trap.
- **`logger.error(f"Failed: {e}")` paired with no `raise`.** The f-string in the error log captures the exception's string but drops the traceback. The correct form is `logger.exception("Failed")` (which logs the exception with traceback automatically), or `logger.error("Failed", exc_info=True)`. This is a connected sub-defect from [`swallowed-exceptions`](swallowed-exceptions.md).
- **Multiple f-string log calls in one file.** If you find one, look for the others — sticky-local-pattern density.
- **A codebase with `AGENTS.md` / `CLAUDE.md` / style-guide mentioning "lazy logging" or "%-style" — and f-string logger calls in the code.** Codified-guidance-is-insufficient signal; the convention is documented but unenforced.
- **A prior fix-PR that migrated some files to `%`-style and stopped.** The half-completed-propagation shape; sibling modules still have the pattern.

The diagnostic question for any candidate log call: *will this string be evaluated even if the log level disables this message?* If the answer is yes (f-string, .format(), concatenation, manual string construction), the formatting is eager. If the answer is no (`%`-style placeholders with args passed separately to the logger), the formatting is lazy.

The fix is mechanical at scale: `flynt --transform-fstrings logging.warning` or a libcst codemod can convert the dominant pattern automatically. Manual review is needed for multi-arg or expression-containing f-strings (`logger.info(f"User {user.name} ({user.id}) failed login attempt #{user.fail_count + 1}")` doesn't translate trivially). The IBM specimen explicitly recommends this hybrid approach: codemod for the dominant shape, manual review for the residue, ruff G004 for regression coverage.

## Notes

**Category `observability`.** Joins [`print-instead-of-logging`](print-instead-of-logging.md) — second entry in this category. Both stem from the model producing string-output primitives that ignore the deployment-context cost. Together they form a tight observability-defect cluster within the AI-pedagogical-bias family.

**Difficulty rated `low`.** Spotting `logger.<level>(f"...` is visually trivial. The diagnostic step (does eager formatting matter here?) requires knowing the logging-cookbook recommendation and the structured-log aggregation argument, but the cue itself is unambiguous. A reader who knows the pattern can scan AI-generated logging code quickly.

**The pattern is AI-amplified, not AI-exclusive.** Restated for emphasis: many human Python developers also default to f-string logging because f-strings are the modern recommended idiom for general string construction. The AI-amplified observation is density (~1000+ instances in one IBM project), persistence-across-codified-convention (IBM AGENTS.md says don't), and partial-fix-propagation shapes.

**False-positive shapes.** Be cautious before flagging:

- *Log calls where the f-string contains no variables.* `logger.info(f"")` is just a string; no eager-formatting cost.
- *Log calls where the message construction is genuinely cheap.* `logger.info(f"User {user.id}")` for a single integer formatting is negligibly more expensive than the `%s` form. The performance argument is weakest here; the structured-aggregation argument is still real (the log aggregator sees `"User 12345"` instead of `"User %s"` template).
- *Custom logging adapters or structlog setups.* Some projects use `structlog` or custom adapters where the f-string idiom is appropriate because the underlying logger handles it differently. The cue is whether the project uses standard `logging` or a structured-logging library.
- *Test code intentionally logging deterministic strings for assertions.* Tests that assert specific log messages may use f-strings deliberately. The cue is whether the test asserts against the log content.
- *Performance hot-paths where the log level is *always* enabled.* If a log message is always emitted at the production level (e.g., a startup banner that fires once per process), the eager-formatting cost is paid regardless of form. Negligible difference; not the AI-amplified shape.

**Mutation operator hint.** A deterministic mutation that takes a clean `%`-style log call and converts to f-string produces this pattern from clean code. Variants:

- Replace `logger.info("Processed %d items", count)` with `logger.info(f"Processed {count} items")`
- Replace `logger.error("Failed: %s", err)` with `logger.error(f"Failed: {err}")` (also drops `logger.exception` opportunity)
- Replace `logger.debug("Cache hit for key %s", key)` with `logger.debug(f"Cache hit for key {key}")`
- Convert `logger.info("%s | %s", a, b)` (positional template) to `logger.info(f"{a} | {b}")` (the cleanest-looking change with the same defect)

These compose with [`print-instead-of-logging`](print-instead-of-logging.md) — a function that mixes `print(f"...")` and `logger.<level>(f"...")` is the maximally AI-tell shape; both calls use the wrong primitive *and* the wrong string-construction idiom.

**Connection to [`ai-pedagogical-bias`](../notes/ai-pedagogical-bias.md) note.** This entry contributes the fifth instance to the AI-pedagogical-bias meta-family, joining [`narrating-comments`](narrating-comments.md), [`print-instead-of-logging`](print-instead-of-logging.md), [`hardcoded-config-values`](hardcoded-config-values.md), and [`missing-network-timeout`](missing-network-timeout.md). The pattern of "modern Python tutorial style produces correct-looking but production-suboptimal output" now spans five surfaces (comments, output primitives, configuration, networking, log-message formatting). The cross-cutting note's promotion criterion (5+ entries) is met.

**Connection to [`same-project-knows-right-pattern`](../notes/same-project-knows-right-pattern.md) note.** The gen-ai-ops specimen shows the right pattern in most files and the wrong pattern at one — a clean instance of within-codebase drift. This adds an instance to the cross-cutting observation.

**Connection to [`partial-fix-propagation`](../notes/partial-fix-propagation.md) note.** The IBM specimen is one of the three founding specimens for this note: precursor #1837 migrated `sse_transport.py` and `resource_service.py` to `%`-style; ~50 sibling modules and ~1000+ residual f-string log calls remained outside the PR's scope (surfaced in #4617). The shape was part of what triggered the 2026-05-25 promotion of partial-fix-propagation from a sub-shape inside same-project-knows-right-pattern into its own note.

**Connection to [`codified-guidance-is-insufficient`](../notes/codified-guidance-is-insufficient.md) note.** IBM AGENTS.md explicitly states "Lazy logging style preferred"; the codebase has ~1000+ violations. This is now a 10+ entry observation. The IBM specimen is the highest-volume instance of codified-guidance-insufficient captured to date.

**Audit-framework catalog continues to grow.** The Hledac/Oponent/Soudce three-stage AI pipeline (knowitcz/gen-ai-ops-04-30) is the 15th distinct audit framework captured. The combination of bot-authored audits (Cogtrix), AI-quality-pipeline audits (knowitcz), and AI-on-AI review (jparson2389/aetherflow's Copilot+Codex catching off-by-one) is now well-attested. AI-driven audit infrastructure is itself an emergent pattern worth tracking. Worth a future cross-cutting note: *AI-on-AI defect discovery as an audit-framework class*.
