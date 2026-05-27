---
name: print-instead-of-logging
category: observability
difficulty: low
generation: evergreen
since_model: null
evidence_grade: observed
---

# Print Instead Of Logging

## Code example

```python
# ergodic_insurance/batch_processor.py
import logging

logger = logging.getLogger(__name__)


class BatchProcessor:
    def run(self) -> None:
        pending = self._load_pending_scenarios()
        if not pending:
            print("All scenarios already completed.")
            return

        print(f"Processing {len(pending)} scenarios...")
        for scenario in pending:
            try:
                result = self._run_scenario(scenario)
                self._save(result)
            except Exception as e:
                print(f"Error running {scenario.id}: {e}")
                if self._should_stop():
                    print(f"Stopping batch: reached {self.max_failures} failures")
                    return

        print(f"Generated financial report at {self.output_path}")
```

The function works. Status messages appear when the user runs it. What is wrong is that `print()` is the wrong tool for every line here, even though the right tool — `logger` — is imported and configured at the top of the file. The class has the logging infrastructure in scope and still chose `print()` at every status site.

The defects compound:

1. **No suppression.** A library user calling `BatchProcessor().run()` from a notebook or pipeline sees the messages regardless of their logging configuration. There is no way to silence the status updates without monkey-patching stdout.
2. **No level filtering.** "Generated financial report" is informational; "Error running scenario" is a warning or error. `print()` collapses both onto stdout with no level metadata. Production observability tools cannot distinguish them.
3. **No structured logging.** The format string `f"Error running {scenario.id}: {e}"` is unstructured text. Log aggregation systems (Datadog, Sentry, CloudWatch Logs Insights) cannot index the scenario ID, the error type, or any other structured field. The text is human-readable and machine-unparseable.
4. **No timestamp / location metadata.** `print()` emits the message with no timestamp, no source-file context, no log level. A logger configured with a standard formatter emits all of that automatically.
5. **No redirection.** `print()` always goes to stdout. A logger can route INFO messages to a file, ERROR messages to a Slack channel, DEBUG messages nowhere.

A tightened version uses the logger that is already imported:

```python
class BatchProcessor:
    def run(self) -> None:
        pending = self._load_pending_scenarios()
        if not pending:
            logger.info("All scenarios already completed.")
            return

        logger.info("Processing %d scenarios", len(pending))
        for scenario in pending:
            try:
                result = self._run_scenario(scenario)
                self._save(result)
            except Exception:
                logger.exception("Error running scenario %s", scenario.id)
                if self._should_stop():
                    logger.warning("Stopping batch: reached %d failures", self.max_failures)
                    return

        logger.info("Generated financial report at %s", self.output_path)
```

Every print() became the appropriate `logger.*()` call. `logger.exception()` captures the traceback that the original code dropped. Format strings use `%`-style lazy interpolation, which the logging documentation recommends because the string is built only if the log level is enabled. The library user can now suppress, filter, redirect, or aggregate the output via standard logging configuration.

The pattern has several visible sub-shapes in captured specimens:

- **Per-file generation drift with extreme density** — `flow.py` has 51 `print()` calls and 0 `logger.` calls, while sibling `stage3_runner.py` in the same project uses `logger` throughout. The model's prior at each file's generation context produced one or the other, never mixed within a file. Captured in oviney/economist-agents#334.
- **Logger-in-scope-but-not-used** — the module has `import logging` and `logger = logging.getLogger(__name__)` at the top, but individual function bodies still use `print()`. The right tool was in scope; the generation step did not look up to find it. Captured in AlexFiliakov/Ergodic-Insurance-Limits#1188 (8+ prints with logger already imported).
- **Print-in-MCP-server-stdout-context** — `print()` in code that runs in an MCP server, where stdout is the protocol transport channel. Currently shielded by STDIO isolation but architecturally fragile. Captured in MarcusJellinghaus/mcp-tools-py#93.
- **Cluster across multiple files in one codebase** — the same project files multiple print()-related issues across different files (`batch_processor.py`, `progress_monitor.py`, `trajectory_storage.py`, `RiskMetrics.__init__`). The pattern is recognized as systemic. Captured as the multi-issue spread in Ergodic-Insurance-Limits.

All sub-shapes share the same root mechanism: the model used `print()` as the canonical "report status" primitive when `logging` would have been the correct tool for the project's context.

## Mechanism

A language model's prior for "how do I report status from my code" is heavily shaped by the training corpus's treatment of output primitives. The corpus contains millions of examples of `print()` because:

- **Tutorial code** uses `print()` to demonstrate program output, because the alternative (`import logging`, `logger = logging.getLogger(__name__)`, `logging.basicConfig(...)`, then `logger.info(...)`) is more code that distracts from the lesson.
- **Stack Overflow** answers use `print()` for quick examples; explaining when to use logging instead is a separate question with its own answers.
- **Beginner Python content** uses `print()` exclusively for output, because logging is presented as an intermediate-level concern.
- **REPL examples and Jupyter notebooks** rely on `print()` as the way to see values during exploration.
- **`__main__` script entry points** legitimately use `print()` for human-facing CLI output, which the corpus contains in volume.

What the corpus contains less of, per-token, is the principled discipline:

- Library code that uses `logger.*()` instead of `print()` because library users need to be able to suppress, filter, or redirect output
- Server code that uses logging because the deployment environment captures structured log output
- MCP-server / RPC-server code that *must not* print to stdout because stdout is the transport channel
- Production code that uses `logger.exception()` to capture stack traces with the error message

The model knows about logging in the abstract — it can write `import logging; logger = logging.getLogger(__name__); logger.info(...)` when asked directly. What it does not do reliably during a local generation step is *choose* the logger when the surrounding code's context calls for status output. The model's local-attention bias favors the simpler-and-more-corpus-frequent primitive (`print()`) over the more-elaborate-but-context-appropriate alternative (`logger.*()`).

Three concrete failure paths are visible in the captured specimens:

**Path 1: Per-file generation drift.** The model generates one file in a context where the surrounding code uses `logger` and produces `logger` calls in that file; it generates another file in a context where the surrounding code uses `print()` and produces `print()` calls. The two files share the project but not the prior. The economist-agents specimen captures this with 51-to-0 density in one file paired with logger-throughout in another.

**Path 2: Logger-in-scope-but-not-used.** The module's top imports include `import logging` and define `logger = logging.getLogger(__name__)`. The model put the setup at module scope correctly. Each function body then uses `print()` for status output because the function-body-generation context's local prior favors `print()` and the global module-level logger is not part of the function-body attention window. Ergodic-Insurance-Limits captures this exactly — `logger` is imported and configured; the 8+ prints in `batch_processor.py` were generated without consulting it.

**Path 3: Print-in-wrong-context.** The model generates code in a context where `print()` is not just suboptimal but *actively wrong*. MCP servers reserve stdout for the JSON-RPC transport channel; any `print()` output that reaches stdout corrupts the protocol. The mcp-tools-py specimen captures this — print() in the MCP server's pytest runner is currently shielded by STDIO isolation but architecturally fragile. The model writing this code did not consult the MCP protocol's stdout constraint.

The training corpus reinforces the failure mode in a subtler way as well: the corpus contains many examples of `if __name__ == "__main__": print(...)` patterns that *are* legitimate uses of `print()`. CLI scripts use print() correctly because their job is to produce human-facing output. The model has seen both legitimate-print and wrong-print, and at generation time it does not reliably distinguish "this is a CLI entry point" from "this is library/server code that should use logger."

The defect paths vary in severity:

1. **Library leakiness.** Library users cannot suppress, filter, or redirect the output. The library's surface is permanently noisy.
2. **Broken structured-log capture in CI.** CI pipelines that ingest structured logs (JSON-formatted, etc.) miss the print() output entirely. Observability is incomplete.
3. **No log level filtering.** Production deployments cannot run at WARNING-and-above to suppress chatty INFO output; everything goes to stdout.
4. **MCP transport corruption** (worst case). Print() in MCP servers can break the JSON-RPC protocol if STDIO isolation fails. Defect-direct.
5. **No timestamps, no source location.** Operators reading printed output don't know when an event occurred or what line emitted it. Logger output has both automatically.

This pattern is the **observability cousin of [`narrating-comments`](narrating-comments.md)**. Both stem from the model defaulting to communication patterns that are appropriate for tutorial/example code (visible output for learners; comments narrating each step) but wrong for production code (suppressible logging; comments for *why* not *what*). The two entries together describe an AI-typical *pedagogical bias* — the model treats production code as if it were tutorial code, producing patterns that prioritize human-readable explanation over machine-actionable behavior.

This pattern is **AI-amplified, not AI-exclusive**. Human developers reach for `print()` constantly, particularly during debugging, in scripts, and in CLI tools where print() is correct. The AI-amplified observation is the *frequency* and *consistency*: AI-generated codebases produce `print()` across library code, server code, and contexts where print() is wrong, at densities that suggest the model is treating "report status" as a single generic task with a single generic primitive rather than evaluating the deployment context. The 51-to-0 ratio in one file plus the cluster of 5 related issues in another project are both AI-amplified clustering signatures.

## Evidence / incident

Three captured specimens at three different defect-severity levels. Specimens live in `evidence/github-issues/`.

- **[oviney/economist-agents#334](https://github.com/oviney/economist-agents/issues/334)** — per-file generation drift with extreme density. `flow.py` has 51 `print()` calls and 0 `logger.` calls; sibling `stage3_runner.py` uses `logger` throughout. CI structured-log capture is broken. Multi-agent AI system project. Specimen: [oviney-economist-agents-334.md](../../evidence/github-issues/2026-05-15-oviney-economist-agents-334.md).
- **[MarcusJellinghaus/mcp-tools-py#93](https://github.com/MarcusJellinghaus/mcp-tools-py/issues/93)** — print-in-MCP-server-stdout-context. ~15 print() statements in a pytest runner that ships as part of an MCP server (where stdout is the JSON-RPC transport channel). Currently shielded by STDIO isolation but architecturally fragile. The most defect-direct version of the pattern. Specimen: [MarcusJellinghaus-mcp-tools-py-93.md](../../evidence/github-issues/2026-05-15-MarcusJellinghaus-mcp-tools-py-93.md).
- **[AlexFiliakov/Ergodic-Insurance-Limits#1188](https://github.com/AlexFiliakov/Ergodic-Insurance-Limits/issues/1188)** — logger-in-scope-but-not-used. `batch_processor.py` has `import logging` + `logger = logging.getLogger(__name__)` at module level AND 8+ `print()` calls in function bodies. Five related issues filed across the codebase for the same pattern in different files (#487, #980, #1060, #1062, #1188). Specimen: [AlexFiliakov-Ergodic-Insurance-Limits-1188.md](../../evidence/github-issues/2026-05-15-AlexFiliakov-Ergodic-Insurance-Limits-1188.md).

Three different defect surfaces (broken CI log capture, MCP protocol fragility, library leakiness), three different AI-related projects. Cross-context coverage is broad.

Supplementary references:

- **XRPLF/xrpl-py#952** — "print() Used Instead of logging in Production Code" with an `AI Triage` label. The adversarial verdict on this finding was *DISPROVED* — the print() calls are in `generate_faucet_wallet()`, a test-network-only utility, gated behind `if debug:`. Captured as a clean **false-positive example** demonstrating that the entry's "false-positive shapes" section is real: not every print() is the pattern; opt-in debug-flag-gated print() in a test utility is legitimate.
- **aabtzu/libertas-travel#48** AI-tells audit includes in its remediation list: *"Convert `print()` calls to `logging` (mapper.py has 17, several other files). Already in MEMORY/cleanup."* — independent identification of the pattern at the audit-summary level.

## Detection cues

What to look for in a diff or completion:

- **`print()` statements in any file that is not a `__main__` entry point.** Library code, server code, agent code, anything that runs as part of a larger system rather than as a standalone CLI script. The cure is `logger.info/warning/error`.
- **`print()` statements in code that imports `logging` or has a module-level `logger`.** Particularly diagnostic — the right tool is in scope and was not used. Grep for `^import logging` or `^logger = ` near the top of the file, then count `print(` calls in the rest of the file.
- **Multiple `print()` calls in one file with zero `logger.` calls.** A density ratio of N-to-0 is the cluster-shape AI-amplified signature. A density of N-to-M where N >> M is the partial-drift signature.
- **`print(f"...{e}")` to report an exception.** Lost the traceback; lost the structured error info. The cure is `logger.exception("...")` which captures both.
- **`print()` in an MCP server's source code.** Especially anything that could reach stdout at runtime. STDIO isolation is environmental, not architectural; print() in MCP servers is a protocol-corruption risk waiting for the shielding to fail.
- **`print()` in a server's request-handling code.** Web servers, RPC servers, async services. Every print() reduces observability and is functionally invisible in deployment environments that capture structured logs only.
- **Function bodies that mix `print()` and `logger.*()`.** A file or function that uses both is in the middle of an unfinished migration; the convention-drift pattern applies. Pick one and stick with it.

The diagnostic question for any candidate: *who is going to read this output, and how?* If the answer is "a human running this from a terminal" — print() may be correct. If the answer is "a CI log aggregator, a production monitoring system, an embedding application, or a deployed server's operators" — logger is required. The model's local generation step does not perform this analysis; the audit step has to.

## Notes

**Category `observability`** — new category. Previous entries have used `structure`, `testing`, `defensive-programming`, `error-handling`, `control-flow`, `documentation`, `library-usage`, `async`, `consistency`. The new category captures patterns about *how the program is observed in production*. Future entries about telemetry, metric exposure, tracing, or structured-error-context could fit here.

**Difficulty rated `low`.** Spotting `print()` in code that should use `logging` is visually unambiguous — the keyword is right there. The harder step is knowing when print() is legitimate (CLI scripts, `if __name__ == "__main__":` blocks, pre-logger-initialization bootstrap output) vs when it is the pattern (library code, server code, agent code, MCP servers). The XRPLF false-positive case (test-utility with explicit debug flag) demonstrates the legitimate exception.

**Pre-existing community recognition.** Python community guidance consistently warns against `print()` in production code in favor of `logging`. The PEP 8 style guide and most Python style references address this. The pattern is in the taxonomy because AI-generated code reproduces the anti-pattern despite the community guidance — another instance of the *codified-guidance-is-insufficient* observation now visible across the project's entries.

**The pattern is AI-amplified, not AI-exclusive.** Human developers default to `print()` constantly, particularly during quick prototyping and debugging. The AI-amplified observation is the *consistency* with which AI-generated production code uses print() — and the *blindness to the deployment context* (MCP server stdout, library API surface, CI structured-log capture). Human developers usually transition from print() to logger over a project's lifetime; AI-generated codebases produce the pattern across many files as initial state.

**False-positive shapes.** Be cautious before flagging:

- *CLI entry-point output.* `if __name__ == "__main__":` blocks legitimately use `print()` for human-facing terminal output. The XRPLF/xrpl-py specimen documents this as the disproved-finding case — opt-in debug-flag-gated print() in a test-network utility is correct.
- *Pre-logger-initialization bootstrap output.* `main.py` startup code that runs before `logging.basicConfig()` is called can legitimately use `print()`. The mcp-tools-py specimen explicitly flags this as a case-by-case decision.
- *Notebook / REPL / script output.* Code intended to be run in a Jupyter notebook or as an exploratory script can use print() because the output is part of the user's interactive workflow.
- *Performance-critical hot loops.* `print()` to a pre-opened file descriptor is sometimes the only practical choice in code where every microsecond matters. Rare in Python (where logging overhead is comparable), but legitimate when documented.
- *Test fixtures that print expected output for human inspection.* Pytest output, doctest examples, etc. legitimately use print().

**Mutation operator hint.** A deterministic mutation that takes clean logger-using code and replaces logger calls with print() produces this pattern from clean code. Variants:

- Replace `logger.info("Processing %d", n)` with `print(f"Processing {n}")`
- Replace `logger.exception("Failed")` with `print(f"Failed: {e}")` (drops the traceback)
- Replace `logger.debug(...)` with `print(...)` (no level filtering)
- Add `print()` debug statements without removing them
- Generate a new module with `import logging` at the top, define `logger = logging.getLogger(__name__)`, then write all function bodies using `print()` (the logger-in-scope-but-not-used shape)

These mutations compose with [`narrating-comments`](narrating-comments.md) — a function with both `# Step 1: Load data` narration AND `print("Loading data...")` status is doing the same defective communication pattern at two levels (comment for developer; print for operator).

**Connection to [`defensive-choice-with-justifying-comment`](../notes/defensive-choice-with-justifying-comment.md) note.** print() statements are often paired with comments like `# Status update for debugging` or `# Show progress to user`. The comment narrates the purpose; the code uses the wrong tool. This is the same comment-as-justification shape seen in [`swallowed-exceptions`](swallowed-exceptions.md), [`wrong-tool-for-job`](wrong-tool-for-job.md), and others — a justifying comment paired with a defensive or suboptimal primitive choice.

**Connection to [`same-project-knows-right-pattern`](../notes/same-project-knows-right-pattern.md) note.** The economist-agents specimen is a clean per-file instance (one file all-logger, another all-print). The Ergodic-Insurance-Limits specimen is a clean within-file instance (`logger` imported and configured at top, `print()` calls in function bodies below). Both demonstrate that the model's prior at each generation step is independent of nearby correct examples. This entry is one of nine in the same-project-knows-right-pattern observation.

**Connection to [`ai-pedagogical-bias`](../notes/ai-pedagogical-bias.md) note.** Tutorial code uses `print()` to demonstrate output because it is the simplest primitive; production code uses `logger.*()` because deployments need suppression, level filtering, redirection, and structured indexing. The model defaults to the tutorial-fluent form. This entry is one of five members of the AI-pedagogical-bias meta-family alongside [`narrating-comments`](narrating-comments.md), [`hardcoded-config-values`](hardcoded-config-values.md), [`missing-network-timeout`](missing-network-timeout.md), and [`f-string-in-logger-call`](f-string-in-logger-call.md).

**Connection to [`codified-guidance-is-insufficient`](../notes/codified-guidance-is-insufficient.md) note.** Python community guidance (PEP 8, most style references) explicitly recommends `logging` over `print()` in production code. AI-generated code reproduces the anti-pattern despite the community guidance — another instance of the codified-guidance-insufficient observation.
