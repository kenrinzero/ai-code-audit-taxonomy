# Surface-failure-modes-explicitly

Four taxonomy entries — covering unneeded defenses, divergent error contracts, fragile error discrimination, and outright exception swallowing — converge on the same advice: **surface failure modes explicitly through the type system. Do not paper over them with defensive shapes that look like error handling but accomplish nothing.**

The four entries form a small recognizable cluster within the taxonomy. The common thread is *defensive shape disconnected from defensive substance* — code that has the surface form of risk-handling but does not actually handle the risks it appears to address.

## Where the observation appears

| Entry | Defective shape | Cure |
|-------|-----------------|------|
| [`unreachable-defensive-guard`](../patterns/unreachable-defensive-guard.md) | `if x is None: return None` for inputs the caller cannot produce | Document precondition; trust caller; fail loudly if the invariant is ever violated |
| [`inconsistent-error-handling`](../patterns/inconsistent-error-handling.md) | Sibling implementations of one role disagree on error contract (one swallows + returns string, others raise) | Pick one contract uniformly; prefer raising over sentinel returns; enforce across siblings |
| [`brittle-error-detection`](../patterns/brittle-error-detection.md) | `if "already exists" in str(exc):` to discriminate failure modes from a bare exception class | Typed exception classes at the throw site; catch by type, not by message substring |
| [`swallowed-exceptions`](../patterns/swallowed-exceptions.md) | `except Exception: pass` indiscriminately, sometimes with `# Memory is optional` justification | Catch specific exception types known to be recoverable; log; let unexpected exceptions propagate |

All four sit in the `error-handling` and `defensive-programming` categories.

## Mechanism

A language model generates each defensive construct in a local attention context. The training corpus contains heavy examples of defensive idioms:

- `if x is None: return None` — beginner-Python's "don't crash on missing input"
- `try: ...; except Exception: pass` — Stack Overflow's "make it not crash" recipe
- `if "<message>" in str(e):` — legacy bridges to non-typed exception sources
- `try: ...; except: return False` — predicate-shaped failure absorption

These shapes are corpus-fluent. They are what the model produces when it needs to *appear* to handle a risk without doing the structural work of typed exceptions, contracts, or principled propagation.

What the corpus contains less of, per-token, is **typed-exception discipline**:

- Custom exception classes that encode failure modes at the throw site
- `raise SpecificError(...) from cause` chains preserving context
- `except SpecificError:` catches that name the failure they recover
- Documented preconditions that the caller is responsible for
- `logger.exception(...)` for failures the caller should know about
- Principled refactoring PRs that introduce typed-exception hierarchies across whole modules

The principled forms require more *structural* tokens — defining a new class, updating multiple throw sites and catch sites, threading a contract through the program — than the defensive shortcuts. The local-attention generation step is biased toward the shape that fits the immediate context. The structural alternative requires reasoning across the function's role, the caller's invariants, and the module's contract — operations the model does not perform during local token prediction.

Across the four entries, the *same* generation-step shortcut produces *different* surface defects:

- At the input-validation site: the shortcut is to add a defensive guard, even when the caller cannot produce the invalid input
- At the sibling-implementation site: the shortcut is to pick a locally-plausible error contract, even when sibling implementations have chosen a different contract
- At the failure-discrimination site: the shortcut is to substring-match the message, even when a typed exception would do the work cleanly
- At the failure-handling site: the shortcut is to swallow the exception with `pass`, even when the calling code needs to know something broke

## A meta-principle: surface failures, don't paper over them

The four cures converge on a single piece of advice:

> Surface failure modes explicitly through the type system. Do not paper over them with defensive checks, string matching, sentinel returns, or silent swallows.

This is consistent with the `swallowed-exceptions` evergreen and is the implicit theme of half the taxonomy. Defensive code that *actually* handles failures looks structurally different from defensive code that *appears* to handle failures:

- Real defensive code defines a typed exception, or returns a structured Result/Either type, or raises with a clear cause chain.
- AI-amplified defensive code adds a guard, a substring check, a sentinel value, or a `try/except: pass` — shapes that *look* defensive but cannot actually distinguish or convey the failure.

The cure prescription is the same across all four entries: replace the *shape* with the *substance*. Define the typed exception, raise it at the throw site, catch it by type, let it propagate when the calling code should respond.

## Why this is a note, not an entry

Each of the four entries documents a distinct defect class with its own evidence, mechanism, and detection cues. The convergence is **about how those defects relate**, not about a new defect. Promoting the meta-principle to an entry would either duplicate the four existing entries or create an umbrella entry whose evidence is the four entries themselves — a kind of double-counting.

The note exists to name the shared mechanism and the converging cure. Readers benefit from seeing the family explicitly: a reader who recognizes one of the four shapes can use the family connection to look for the others in the same codebase.

## Implications

For readers of AI-generated code:

- When you see one defensive shape from the family, look for the others in the same codebase. The local-attention bias that produced one tends to produce the rest.
- The fastest audit move on a defensive-looking construct: *trace the failure mode it claims to handle*. If you cannot identify a concrete failure path the construct addresses, the defense is shape without substance.
- Typed-exception discipline is a useful global check: grep the codebase for custom exception classes; classes that are *defined but never raised at the source* indicate the half-implemented typed-exception form (where the cure is to push the raise into the throw site).

For projects using AI-assisted development:

- Define typed exception classes at the boundaries where failure modes need to be discriminable.
- Configure lint rules: `BLE001` for broad excepts, custom rules for `if .* in str(.*):` patterns inside `except` blocks.
- Code-review checklist: "is this defensive shape actually doing the defensive work it appears to do?"

For the calibration training:

- This family is one of the project's most-tested mechanism convergences. A reader calibrated to recognize "defensive shape without defensive substance" can audit four distinct surfaces efficiently.
- Drills that ask "what concrete failure mode does this construct handle?" train the audit step directly.

## Promotion criteria

This note exists because four entries converge on the same advice. The convergence has been visible since the swallowed-exceptions entry landed (its Notes section first named the four-member family). The note formalizes that observation.

If a fifth entry lands that demonstrates the same defensive-shape-without-substance mechanism on a new surface (e.g. a `weak-validator-that-cannot-reject` pattern, or a `mock-as-defensive-stand-in` pattern), expand the table here. The token-fluent-but-semantically-defective cluster ([`off-by-one`](../patterns/off-by-one.md) + [`swapped-args`](../patterns/swapped-args.md), with swallowed-exceptions as a partial fit) is structurally adjacent — both families produce code that has correct surface form and incorrect substance. They could be reconciled at the eventual category-revisit if a richer note structure emerges.
