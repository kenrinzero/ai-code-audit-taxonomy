# AI-pedagogical-bias

The model defaults to patterns appropriate for tutorial / example / teaching code when the deployment context calls for production-grade alternatives. The model treats production code as if it were tutorial code.

## Where the observation appears

Six entries currently demonstrate this:

| Entry | Tutorial behavior | Production-appropriate alternative |
|-------|-------------------|------------------------------------|
| [`narrating-comments`](../patterns/narrating-comments.md) | Comment each line to explain WHAT it does | Comments for WHY (non-obvious constraints), not WHAT |
| [`print-instead-of-logging`](../patterns/print-instead-of-logging.md) | `print()` for visible output | `logger.*()` for suppressible / level-filtered / structured output |
| [`hardcoded-config-values`](../patterns/hardcoded-config-values.md) | Inline numeric/string literals for clarity | Configurable parameters (env var, config file, CLI flag, constructor argument) |
| [`missing-network-timeout`](../patterns/missing-network-timeout.md) | `requests.get(url)` — minimal HTTP call from a tutorial | `requests.get(url, timeout=(5, 30))` — explicit timeout for production reliability |
| [`f-string-in-logger-call`](../patterns/f-string-in-logger-call.md) | `logger.info(f"Processing {x}")` — modern Python's preferred string idiom | `logger.info("Processing %s", x)` — lazy interpolation idiomatic for the `logging` module |
| [`assert-for-runtime-validation`](../patterns/assert-for-runtime-validation.md) | `assert isinstance(x, T)` — concise pytest / type-narrowing idiom | `if not isinstance(x, T): raise TypeError(...)` — survives `python -O` and `PYTHONOPTIMIZE=1` |

## Mechanism

A language model's prior for "how should I write this code" is shaped by the training corpus distribution. The corpus is heavy with:

- Tutorial code (Python tutorials, course materials, programming books)
- Stack Overflow answers (which solve narrow asker-specific problems with minimal scaffolding)
- Beginner Python content (where each lesson focuses on one feature without distractions)
- README examples in library documentation (where the example demonstrates *how to use the library*, not *how to deploy it*)
- REPL / Jupyter notebook exploration code

What the corpus contains less of, per-token, is *production hygiene*:

- Library code that uses `logger` instead of `print` because the library has users who need to control output
- Production code that documents non-obvious constraints rather than narrating each operation
- Server code that exposes operational parameters as config because deployments vary
- HTTP/subprocess calls with explicit `timeout=` because indefinite hangs are not acceptable in production
- Log calls using `%`-style lazy formatting because the logging module supports level-filtering before formatting

The model generates code that fits the corpus-modal style. In tutorial code that style is correct; in production code it is suboptimal or wrong. The model does not reliably distinguish "this is a tutorial example" from "this is library/server/agent code with operational requirements."

The defects produced are *pedagogically inflected*: each pattern looks educational, looks helpful, looks like it would be at home in a Python tutorial. They look correct *as instruction*. They are wrong *as deployed software*.

A deeper observation: **the patterns differ in surface but converge on mechanism**. Comments, output primitives, configuration, network calls, and log-message formatting are five distinct domains of Python code. The model produces the *same kind of failure* in each: the simpler/more-corpus-frequent form, biased toward tutorial intelligibility, applied in a deployment context where the production-hardened form would be correct. The same root mechanism produces five different surface defects.

## Implications

For readers of AI-generated code:

- The diagnostic question is "what is the deployment context, and is this code style appropriate for it?"
- The same code that would earn praise in a Python tutorial fails the same audit in a library codebase
- Calibration for AI-generated code involves separating "explanation-shaped" patterns from "production-shaped" patterns
- The five-entry coverage of this meta-family makes pedagogical-bias one of the most reliable signals for distinguishing AI-generated production code from human-written production code

For projects using AI-assisted development:

- Linters and CI checks against the specific AI-typical surfaces (`print` in non-CLI code, magic numbers in config-shaped values, WHAT-narrating comments, `requests` without `timeout=`, f-string logger calls) are the practical cure
- Codified guidance alone is insufficient (see [`codified-guidance-is-insufficient`](codified-guidance-is-insufficient.md)) — the cure is enforcement, not documentation
- The relevant lint rules — ruff `G004` (f-string logging), bandit `S113` (requests without timeout), ruff `B006` (mutable default argument), `PLC0415` (lazy imports), `BLE001` (broad except) — should be enabled at CI gate

For the project's calibration training:

- This meta-family is a useful onramp for readers learning to recognize AI-generated code. The patterns are individually subtle but together form a recognizable *pedagogical shape*.
- A reader calibrated for this meta-family can quickly assess "is this code production-fit or tutorial-fit?" by skimming a single file.
- The meta-family is now robust enough (5 entries, distinct surfaces, same root mechanism) to consider elevation to a primary organizing principle of the taxonomy at the eventual category-revisit.

## Promotion criteria

This observation is documented here rather than as an entry because the meta-mechanism is corpus-distribution-level, not defect-class-level. The defects themselves are documented by the five entries. The note exists to name the shared mechanism that connects them.

With 5+ entries now landed, the original promotion-trigger ("if the meta-family reaches five-plus entries, consider whether the underlying mechanism deserves elevation") is met. The next category-revisit pass should consider whether to:

- Add an "AI-pedagogical-bias" prefix or tag to each member entry for cross-referencing
- Promote the family to a named "school of defects" sibling to the typed-exception family already converged at four entries
- Restructure the taxonomy organization to group entries partly by mechanism (this being one) and partly by surface (the current categories)

If a sixth entry lands that demonstrates the same pedagogical-bias mechanism on a new surface, expand the table here with the additional entry.
