---
name: swallowed-exceptions
category: error-handling
difficulty: low
generation: evergreen
since_model: null
evidence_grade: observed
---

# Swallowed Exceptions

## Code example

```python
def init_memory_system(config_path: Path) -> Memory | None:
    try:
        memory = Memory.from_config(config_path)
        return memory
    except Exception:
        pass  # Memory is optional -- don't break agent init
    return None
```

The function tries to initialize a memory system from a config file. If anything fails — a corrupt config, a permissions error, an upstream library change, a typo in an attribute name — the `except Exception: pass` swallows the failure entirely. The function returns `None`. The agent runs without persistent memory. The user has no signal that anything is wrong.

The comment "Memory is optional" is doing the work of *explaining the intent* — "we don't want this to crash the agent if memory isn't configured." That intent is reasonable. The implementation conflates two failure modes:

1. **The user did not configure memory.** Returning `None` silently is correct.
2. **The memory system was supposed to work but broke.** Returning `None` silently is wrong — the operator needs to know.

The bare `except Exception: pass` cannot distinguish them. Both produce the same surface behavior: the agent acts as if memory was not configured. A renamed attribute in `Memory.from_config`, a missing dependency, or a schema migration that didn't run — none of these reach the operator's attention. The agent is silently degraded.

A tightened version:

```python
def init_memory_system(config_path: Path) -> Memory | None:
    if not config_path.exists():
        return None  # Memory was not configured -- expected case
    try:
        return Memory.from_config(config_path)
    except (FileNotFoundError, json.JSONDecodeError, MemoryConfigError) as e:
        logger.warning("Memory init failed (non-fatal): %s", e)
        return None
```

The two failure modes are now distinct. The "not configured" case is detected explicitly (config file doesn't exist) and returns `None` cleanly. The "configured but failed" case logs and returns `None`, so the operator sees the failure even though it does not crash the agent. The `except` clause catches *specific* exceptions known to be recoverable; an unexpected exception (like a renamed attribute) propagates.

The pattern has several visible sub-shapes in captured specimens, all sharing the same root mechanism:

- **Bare `except: pass`** — the maximally compact form, catches `KeyboardInterrupt` and `SystemExit` as well as ordinary exceptions
- **`except Exception: pass`** — slightly less aggressive but still catches everything ordinary code can raise
- **`except Exception: pass` with justifying comment** — `# Memory is optional`, `# Best-effort cleanup`. The comment explains intent without changing behavior
- **Catch + log-at-debug + continue** — `except Exception as e: logger.debug(...)`. The log is invisible in production
- **Catch + return False / None / bare-default** — predicates and queries that collapse all failures into a single sentinel, removing the caller's ability to distinguish "not ready" from "broken"
- **Fire-and-forget lambda discarding exceptions** — async tasks created via `asyncio.create_task` without a result/exception handler

All six sub-shapes are documented in the captured specimens.

## Mechanism

A language model generates each `try/except` body in its own step. The `try` block is generated to express the operation being attempted; the `except` block is generated to express what to do if it fails. The model's prior for "what to do if a thing fails" is heavily shaped by the training corpus, and the training corpus has a strong bias toward defensive `except Exception: pass` shapes — because tutorial code, Stack Overflow snippets, beginner Python guides, and many published examples use this shape as a "make it not crash" recipe.

When the model is uncertain what the function should do in the failure case, the swallow-and-return-default shape is the most readily available pattern. It satisfies the surface goal ("don't crash") without requiring the model to reason about what specific failure modes the call could have, which of them are recoverable, what the caller should be told when a recoverable failure occurs, or whether the broader program can meaningfully continue. The model does not perform that reasoning during the local generation step; it produces a shape that *looks* like error handling and moves on.

Stack Overflow is the most concentrated reinforcement. Questions of the form *"My script crashes on bad input, how do I handle this?"* have answers that frequently take the form *"Wrap it in try/except and `pass`."* The answer is technically correct for the asker's narrow need (the script no longer crashes) and gets upvoted. The model has seen this many times. What the model has seen less of is the principled refactor: a PR that replaces a swallowed exception with specific-exception handling, logging, and a typed error return. That kind of cleanup PR is rare in the training corpus because it is rare in the wild.

The defensive shape compounds locally. Once one `try/except: pass` is generated in a function, the next function in the same generation session is biased to use the same defensive shape — the local-attention bias of transformer generation makes the recent pattern sticky. Captured specimens show this dramatically:

- 8 locations in two files (hermes-agent#4058) — modest cluster
- 125 instances across 49 files (marianne-ai-compose#308) — "cultural drift" framing
- 1,066 instances across one src/ tree, 278 in one file (pollypm#1355) — maximally compounded

The pollypm case is the cleanest demonstration of how far the pattern can compound: the project enabled ruff's `BLE001` rule (which exists specifically to prevent this pattern), and instead of fixing the offending code, the developer (or the AI) added `# noqa: BLE001` annotations to every instance. The *suppression of the rule* became the convention. The lint rule was silenced into irrelevance.

The pattern is **AI-amplified, not AI-exclusive**. Human-written codebases produce swallowed exceptions too, particularly in:

- Hot-path code where adding logging would have measurable overhead (rare in Python, common in C)
- Cleanup paths where the caller has already decided to discard the result (`finally`-equivalent shutdown logic)
- Best-effort retry loops where each individual failure is uninteresting
- Bridges to non-Python systems where the only available signal is "did it work or not"

The AI-amplified observation is *scale and lack of justification*. AI-generated codebases produce the pattern at densities that human authorship rarely reaches (1,066 sites in one project), apply it to operations that have no plausible best-effort justification (one-line dict access, library initialization), and reproduce it across hundreds of unrelated functions without architectural reason. The single UI file `pollypm/cockpit_ui.py` accounts for 278 of those instances alone — the AI wrapped essentially every event handler in a defensive `try/except: pass`.

This pattern is **the closing entry in the typed-exception / fail-loud meta-family**. Three earlier entries — [`unreachable-defensive-guard`](unreachable-defensive-guard.md), [`inconsistent-error-handling`](inconsistent-error-handling.md), and [`brittle-error-detection`](brittle-error-detection.md) — each touch a different surface of the same underlying advice: surface failure modes explicitly, do not paper over them. Swallowed-exceptions is the most direct and recognized instance of the principle's violation. The four entries together describe a coherent school: typed exceptions, raised at the right boundary, caught by class not by message, with no defensive shape catching everything indiscriminately.

## Evidence / incident

Three captured specimens at three different scales (8 instances, 125 instances, 1,066 instances), each from a different AI-coded Python codebase. Detailed specimen notes are not included in the public repository.

- **[NousResearch/hermes-agent#4058](https://github.com/NousResearch/hermes-agent/issues/4058)** — comment-justified swallow. Eight initialization paths in `cli.py` and `run_agent.py` use `except Exception: pass` with comments like "Memory is optional -- don't break agent init." Session DB, memory system, gateway config loading, and skills file reads all fail silently. Severity rated High by the audit because silent failures make debugging "impossible." Confirmed Claude Sonnet 4.6 co-authorship in repo. Same project as the [`brittle-error-detection`](brittle-error-detection.md) specimen at hermes-agent#21861.
- **[Mzzkc/marianne-ai-compose#308](https://github.com/Mzzkc/marianne-ai-compose/issues/308)** — systemic / cultural drift. 125 instances across 49 files; flagged by "quality-triage 4-persona synthesis" framework with three of four personas triangulating the finding. Project has explicit `constraints.yaml` MN-007: *"NEVER silence errors without explanation."* — codified constraint that the AI-generated code violates 125 times. Four sub-shapes captured in one finding (bare swallow; config deserialization swallow; predicate returning False on error; fire-and-forget lambda discarding exceptions).
- **[samhotchkiss/pollypm#1355](https://github.com/samhotchkiss/pollypm/issues/1355)** — maximally compounded scale. 1,066 sites of `except Exception: pass` across the src/ tree, including 278 instances in a single UI file. Almost all annotated `# noqa: BLE001` — the ruff lint rule that exists specifically to prevent the pattern has been universally suppressed rather than the underlying code fixed. Audit framing: "Defensive coding has metastasised."

Three different audit frameworks (project-internal UX audit; multi-persona quality-triage; maintainer self-audit), three different scales (8 / 125 / 1,066), three independent codebases. The cross-context coverage is broader than for any prior entry in the project.

Supplementary references:

- The home-assistant/core repo has a batch of 40+ open issues titled "Fix swallowed exceptions in `<integration>` action handlers" all filed within hours of each other on 2026-05-14. The batch suggests a systematic audit (likely AI-driven) but the underlying code in question (velbus, sinch, simplepush, mailgun, etc.) is long-standing community-authored integration code. Captured as a supplementary audit observation rather than a primary specimen, because the AI-authorship of the code being audited is uncertain — the audit pattern is real but the inclusion-rule differential (AI vs human) cannot be cleanly established for these.
- ruff's `BLE001` (`blind-except`) rule exists with broad community adoption — the broader Python community has codified the pattern as a hygiene concern independent of AI authorship. The AI-amplified observation is that the rule fires at unusual density on AI-generated code (pollypm at 1,066 sites; marianne-ai-compose at 125 sites with explicit MN-007 violation).

## Detection cues

What to look for in a diff or completion:

- **`except Exception: pass` or `except: pass`.** The maximally compact form. Almost always defective; the few legitimate cases (best-effort cleanup in a `finally`-equivalent context) tend to be commented with a specific reason.
- **`except Exception: pass` with a comment that justifies the swallow.** `# Memory is optional`, `# Best effort`, `# Don't crash on edge case`. The comment is doing the work the code should do — distinguishing "expected absent" from "broken." Treat the comment as the cue, not the justification.
- **A function that returns `None`, `False`, or an empty default from inside an `except` block.** Particularly suspect when the function is a predicate (`is_ready()`, `is_valid()`) or a query that should not be able to return ambiguous results. The caller cannot distinguish the legitimate-false case from the something-broke case.
- **`# noqa: BLE001` annotations.** Direct evidence the linter is being silenced rather than the code fixed. A few of these in legacy code are normal; a codebase-wide pattern is the AI-amplified form.
- **`logger.debug(...)` from inside an `except` block.** DEBUG-level logging is invisible in most production deployments. A failure logged at DEBUG is functionally swallowed.
- **`asyncio.create_task(coro)` with no exception handler attached.** Async fire-and-forget where exceptions never reach `await`-ing code. The marianne-ai-compose specimen's FE-025 case.
- **Clusters of swallowed exceptions.** If you see one bare `except: pass` in a file, look at the rest of the module — the captured specimens show 8, 21, 30, 57, 125, 278 instances clustered in single files. The sticky local pattern observation from [`unjustified-lazy-import`](unjustified-lazy-import.md) applies.

The diagnostic question for any candidate: *what failure modes can the `try` block actually produce, and which of them is the `except` clause meant to recover from?* If the answer is "I don't know, all of them, just don't crash," the clause is reflexive defensive coding. The fix is to enumerate the failure modes the code legitimately recovers from and catch each by type, letting the rest propagate.

## Notes

**Category `error-handling`.** Alongside [`inconsistent-error-handling`](inconsistent-error-handling.md) and [`brittle-error-detection`](brittle-error-detection.md), this forms the typed-exception meta-family within the error-handling category.

**Difficulty rated `low`.** The visual cue is unambiguous — `except Exception: pass` is one of the most recognized anti-patterns in Python. Difficulty is `low` rather than `none` because the *legitimate* cases (genuine best-effort cleanup, narrow predicate over a controlled domain) require a reader to know the distinction, and many beginners will not. Once a reader knows the pattern, detection is essentially zero-effort.

**This is one of three named evergreens** in the taxonomy, alongside [`off-by-one`](off-by-one.md) and [`swapped-args`](swapped-args.md). The trio covers the most well-established defect classes in Python development — pattern classes so canonical that they anchor the taxonomy as familiar starting points for readers.

**Connection to [`surface-failure-modes-explicitly`](../notes/surface-failure-modes-explicitly.md) note.** With swallowed-exceptions, four entries ([`unreachable-defensive-guard`](unreachable-defensive-guard.md), [`inconsistent-error-handling`](inconsistent-error-handling.md), [`brittle-error-detection`](brittle-error-detection.md), and this one) converge on the same advice: surface failure modes explicitly through the type system; do not paper over them with defensive checks, string matching, sentinel returns, or silent swallows. The cross-cutting note formalizes the typed-exception meta-family. Swallowed-exceptions is the most direct instance of the principle's violation — the other three are at the discrimination, sibling-contract, and unneeded-defense surfaces.

**False-positive shapes.** Be cautious before flagging:

- *Genuine best-effort cleanup in shutdown paths.* `try: store.close(); except Exception: pass` inside a `__del__` or signal handler is sometimes the only safe option — raising during cleanup can mask the original error. The cue is whether the swallow is in a path that *cannot* raise without compounding problems (signal handlers, finalizers, context-manager `__exit__` after exception). Look for the *necessity* of the swallow.
- *Narrow predicate over a controlled domain.* `try: int(maybe_int); return True; except ValueError: return False` is a legitimate predicate. The cue is that only one specific exception is caught (not `Exception`) and the function's purpose is exactly to distinguish "valid" from "invalid."
- *Optional-dependency loading at module level.* `try: import torch; except ImportError: torch = None` is the standard optional-dependency pattern. The cue is that the catch is narrow (`ImportError`) and the absence is explicit (`torch = None`), making the optionality visible in the rest of the module.
- *Re-raising after logging.* `except Exception as e: logger.exception(...); raise` is correct — the exception propagates, the log helps diagnose. Not this pattern.
- *Best-effort retry inside a loop.* `for attempt in range(3): try: ... except Exception: continue` is sometimes correct, when each attempt is independent and the loop's purpose is to absorb transient failures. The cue is whether the loop has a *terminating* condition that distinguishes "exhausted retries" from "succeeded."

**Mutation operator hint.** A deterministic mutation that takes a clean function with no error handling and adds an unjustified swallow produces this pattern from clean code. Variants:

- Wrap a function body in `try: ... except Exception: pass`
- Take an `except SpecificError:` clause and broaden to `except Exception:` while keeping the same `pass` body
- Take a function that raises on error and add `try: ... except: return None` at the call site
- Take a function that logs at warning and downgrade to `logger.debug`
- Add `# noqa: BLE001` to a flagged bare except instead of fixing it

The last variant is particularly diagnostic: it is the specific suppression-of-the-rule shape observed in pollypm at scale.

**The "linter silenced rather than code fixed" sub-shape** observed in pollypm is itself a notable failure mode. When a codebase universally `noqa`s the rule that should prevent an anti-pattern, the convention has inverted — the rule's existence is now read as a nuisance rather than a constraint. This is a specific failure mode of AI-assisted development where the AI generates rule-violating code and is asked to "make the linter happy," which it does by adding the suppression rather than fixing the underlying code.

**Adjacent sub-shapes.** Several swallowed-exception sub-shapes captured in the marianne-ai-compose#308 specimen (predicate-returning-bare-False, validator-returning-False-on-error, fire-and-forget exception discard) are documented under this umbrella rather than as separate entries. The predicate-returning-False shape specifically — where the function's name promises a truthy/falsy answer but the falsy case secretly means "broke" — is worth particular attention.

**Connection to [`codified-guidance-is-insufficient`](../notes/codified-guidance-is-insufficient.md) note.** This entry contributes two distinct instances to the cross-cutting note: (1) Mzzkc/marianne-ai-compose's `constraints.yaml` MN-007 ("NEVER silence errors without explanation") violated 125 times; (2) samhotchkiss/pollypm's enabled ruff `BLE001` rule silenced 1,066 times via `# noqa: BLE001` annotations rather than fixed. The pollypm case is the canonical *rule-silenced-rather-than-fixed* sub-shape and the highest-volume codified-guidance-insufficient instance captured.

**Connection to [`defensive-choice-with-justifying-comment`](../notes/defensive-choice-with-justifying-comment.md) note.** The hermes-agent specimen's `# Memory is optional` is the canonical comment-as-justification instance — the comment narrates an intent (memory is optional) that the code (`except Exception: pass`) does not actually fulfill (the swallow cannot distinguish "memory was not configured" from "memory broke"). This entry is one of 9+ in the cross-cutting note.
