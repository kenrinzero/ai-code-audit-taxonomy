---
name: brittle-error-detection
category: error-handling
difficulty: medium
generation: evergreen
since_model: null
evidence_grade: observed
---

# Brittle Error Detection

## Code example

```python
def create_plan(self, slug: str, goal: str, tasks: list, issue: int) -> Plan:
    try:
        plan = query.create_plan(...)
    except ValueError as exc:
        msg = str(exc)
        if "already exists" in msg:
            raise PlanExistsError(f"P{plan_number}") from exc
        m = _TASK_VALIDATION_RE.search(msg)
        ...
```

The function distinguishes a duplicate-plan error from a task-validation error by checking whether the substring `"already exists"` appears in the stringified exception. The check works today. If a future refactor reworded the underlying error message — to `"already present"`, or to `"Plan P42 collision"`, or to a translated version — the substring match would silently fail, and the caller would route duplicate-plan errors as if they were validation failures. No test would fail; the wrong exception type would simply be raised. The bug surfaces only when a user encounters the now-misclassified failure mode in production.

The defect has three components:

1. **The throw site raises an untyped exception class.** `query.create_plan` raises bare `ValueError` for two distinct failure modes (duplicate plan, invalid task). The exception class itself does not encode which mode occurred.
2. **The catch site reconstructs the failure mode by parsing the message.** `if "already exists" in msg` is the substitute for what would have been `except DuplicatePlanError` if the throw site had been typed.
3. **The typed alternative often already exists.** In the example above, `PlanExistsError` is defined in `exceptions.py`; it just is not raised by the query layer directly. The infrastructure for the typed-exception form is half-built; the caller's substring check papers over the gap.

A tightened version:

```python
class DuplicatePlanError(ValueError):
    """Raised when query.create_plan would collide with an existing plan."""


def create_plan(self, slug: str, goal: str, tasks: list, issue: int) -> Plan:
    try:
        plan = query.create_plan(...)
    except DuplicatePlanError as exc:
        raise PlanExistsError(f"P{plan_number}") from exc
    except ValueError as exc:
        m = _TASK_VALIDATION_RE.search(str(exc))
        ...
```

The discriminator is now the exception class, not the message. Renaming the user-facing message text becomes a routine refactor that cannot break the dispatch logic. Tests assert against the *type* of exception raised, not its wording.

The pattern has several visible sub-shapes in captured specimens:

- **Collision-vs-validation discrimination on bare `ValueError`** — the canonical form, where two distinct failure modes share one exception class and the caller uses message substring to discriminate.
- **API-error-code dispatch by message substring** — a Flask/FastAPI handler decides which `error_code` to return in the response envelope by checking substrings of the underlying store helper's exception message. Captured at meridianiq#117, where the audit explicitly flags this as the bug class surviving inside its own fix PR.
- **External-API call result discrimination** — `except Exception as e: if "disabled_client" in str(e).lower():` to distinguish OAuth disabled-client from scope-insufficient from network failure. Captured at hermes-agent#21861, where the misclassification produces a misleading user-facing message.
- **Backend-error string matching** — `if "no such key" in str(e):` to distinguish a Redis-side missing-key error from other backend errors. Captured as a supplementary observation in oliverhaas/django-cachex#86 ("brittle — depends on server English").

## Mechanism

A language model generates each `try/except` body in its own step, drawing on the structural patterns it has seen in the training corpus. The corpus includes both kinds of error handling: typed exception hierarchies (the modern Pythonic form) and string-matched message discrimination (the older form, surviving especially in legacy code, in bridges to non-Python systems, and in tutorial/example code where defining custom exception classes would be overkill for a small snippet).

When the model needs to distinguish two failure modes that originate from a single exception class, the substring-match shape is fluently available — it matches a token pattern (`if "..." in str(...)`) that appears thousands of times in the training corpus. The typed-exception shape requires the model to also generate a new class definition at the throw site, which is structurally a bigger change to the program. The local-generation step that produces the catch block is naturally biased toward the cheaper, in-place fix.

Stack Overflow reinforces this. Many answers to questions about *"how do I tell a duplicate error apart from a validation error if my function raises `ValueError`?"* take the form: *"You can check `'duplicate' in str(e)` if you don't want to define a custom exception."* The answer is technically correct and gets upvoted because it works for the asker's immediate need. The model has seen this kind of advice many times in its training data, weighted by Stack Overflow's high token-presence. What the model has seen less of is the principled refactor — a PR that introduces a typed exception hierarchy across a whole module precisely to *avoid* this fragility.

The deeper mechanism is the same local-fluency-without-global-consistency force that drives [`inconsistent-error-handling`](inconsistent-error-handling.md). In a single generation step, the model sees the call site of the function it is generating; it does not necessarily see the throw site or the broader module's exception-class definitions. It does not check whether a typed exception already exists that would do the discrimination cleanly. It does not check whether the message it is matching against is *the contract* (intentionally stable) or *the user-visible string* (refactorable). The substring check is locally plausible; the fragility is only visible when reading the throw site and the catch site together.

A particularly diagnostic observation comes from the meridianiq#117 specimen: the bug class *survived inside its own fix PR*. The PR that introduced structured `error_code` fields to the response envelope still uses string substring matching internally to decide which `error_code` to assign. Even a developer consciously trying to eliminate this bug class reintroduced it at a different layer. The reflexive availability of the substring-match shape is strong enough that conscious effort at one boundary does not prevent its reappearance at another.

This pattern is the **discrimination-side cousin of [`inconsistent-error-handling`](inconsistent-error-handling.md)**. Inconsistent-error-handling produces sibling implementations with divergent contracts; brittle-error-detection produces a caller that papers over a single class's overloaded use. Both stem from the model not enforcing the typed-exception discipline that makes Python's exception system robust to refactoring.

The pattern is **AI-amplified, not AI-exclusive**. Legacy Python codebases — particularly those written before structured exceptions were idiomatic, or those bridging to non-Python systems (Rust via PyO3, C extensions, foreign-API responses where the only signal is a message string) — contain plenty of human-authored string-matching error checks. The AI-amplified claim is that AI-generated code produces the pattern *as the initial form* of new code, in contexts where typed exceptions would be natural, and reproduces it across the codebase rather than only at the legitimate language-boundary cases. The captured specimens are all from young codebases producing the pattern at points where typed exceptions either already exist (Jamie-BitFlight) or are the recommended fix (meridianiq, hermes-agent).

## Evidence / incident

Three captured specimens, each from a different Python codebase, each at a different layer of the system. All confirmed AI-coded. Detailed specimen notes are not included in the public repository.

- **[Jamie-BitFlight/claude_skills#1514](https://github.com/Jamie-BitFlight/claude_skills/issues/1514)** — collision-vs-validation discrimination. `LocalYamlTaskProvider.create_plan` catches `ValueError` from `query.create_plan` and uses `"already exists" in str(exc)` to distinguish duplicate-plan errors from task-validation errors. A typed `PlanExistsError` exists in `exceptions.py` but is not raised at the throw site. The audit framework ("QG T1 code review of P912") explicitly forbids `cast()`, `Any`, or message parsing in the fix.
- **[VitorMRodovalho/meridianiq#117](https://github.com/VitorMRodovalho/meridianiq/issues/117)** — API-error-code dispatch by message substring. `src/api/routers/revisions.py:215-217` uses `"cap" in message.lower()` to assign `cap_reached` vs `unique_collision` error codes. Identified by "DA exit-council" as the bug class surviving inside PR #116, which itself was supposed to close the bug class by introducing structured error codes at the response boundary. The test path inherits the production path's fragility (`"cap" in detail["message"].lower()`) — connecting observation with [`weak-test-assertion`](weak-test-assertion.md).
- **[NousResearch/hermes-agent#21861](https://github.com/NousResearch/hermes-agent/issues/21861)** — external-API call result discrimination. `check_auth_live()` in a Google Workspace OAuth setup script catches `Exception` and uses `"disabled_client" in err_str or "invalid_client" in err_str` to distinguish OAuth client/account disabled from other failures. Misclassifies the legitimate scope-insufficient (403) case, producing a misleading user-facing message. Confirmed Claude Sonnet 4.6 co-authorship in repo commits.

Three different audit frameworks (QG-T1 review; DA exit-council; follow-up coverage analysis), three different domains (Claude plugin codebase; project-schedule app; AI-agent skill tool), three different layers (data-layer collision detection; application-layer error-code dispatch; external-API call result handling). Cross-axis variance is broad.

Supplementary audit-framework convergence: oliverhaas/django-cachex#86's remaining-work comment lists *"`client/default.py:947-953, 1004-1014` and `client/rust.py:647-694` — string-matching on `'no such key'` Redis error message text. Brittle (depends on server English)"* — an independent identification of the pattern, in a Redis-client backend boundary context. Not captured as a primary specimen because the audit references the pattern abstractly rather than quoting the defective code, but the convergence supports the cross-context claim.

## Detection cues

What to look for in a diff or completion:

- **`if "<some-string>" in str(e)` or `if "<some-string>" in str(exc).lower()` inside an `except` block.** The most direct signal. Particularly suspect when the string is in English and the failure mode being discriminated could plausibly come from non-English-locale code paths (Redis-server messages, OS error messages, third-party SDK errors).
- **Multiple cascading substring checks against one stringified exception.** `if "disabled_client" in err_str or "invalid_client" in err_str: ...` — three or more substring checks against the same message is a strong signal that what should be three exception types or a structured-attribute dispatch has been collapsed into the message layer.
- **A typed exception class that exists in the module but is not raised at the relevant throw site.** Grep for the class's definition; check `git log -S` on the class name. If the class was defined and is only raised by a *catcher* (a re-raise) rather than at the source of the underlying error, the half-implemented form of this pattern is present.
- **An `except Exception` clause that contains substring discrimination.** The `except Exception` catch-all is itself a partial signal (catching everything is rarely the intent); the *combination* of catch-all + substring discrimination strongly suggests the model produced this rather than a structured try/except hierarchy. The hermes-agent specimen has this shape.
- **A test that asserts the same substring the production code matches against.** A test like `assert "cap" in response.detail["message"].lower()` paired with production code that uses `"cap" in message.lower()` is the meridianiq#117 shape: the test agrees with itself; a refactor of the wording breaks both at once and the test cannot warn you.

The diagnostic question for any candidate: *what is the contract that this substring is matching against?* If the answer is "the underlying message text, which could change in any future refactor," the dispatch is fragile. If the answer is "a structured field (`e.resp.status`, `e.error_code`, an enum) that is part of the API contract," the check is structurally sound. The fix is typically to (1) introduce a typed exception class or surface a structured attribute at the throw site, and (2) catch by that type/attribute instead of by message substring.

## Notes

**Category `error-handling`.** Same category as [`inconsistent-error-handling`](inconsistent-error-handling.md); the two are sibling patterns within the same error-handling family. The categories list will be revisited as the taxonomy grows.

**Difficulty rated `medium`.** Spotting the surface (`if "..." in str(e):`) is low-effort; understanding *why* it is brittle requires knowing that error messages are not part of most APIs' stable contracts. A Python beginner who reads the code may not flag it. Once a reader knows the pattern, the diagnostic is mechanical — grep the message text in the throw site's module and ask whether it is intentionally stable.

**The pattern is AI-amplified, not AI-exclusive.** Legacy Python codebases produce this pattern routinely, especially at the boundary with non-Python systems (Rust via PyO3, foreign APIs that only return string messages, SQL drivers that originally only had message-based error reporting). The AI-amplified observation is the *spread* of the pattern: AI-generated code reproduces it across codepaths where typed exceptions would be natural and where the typed-alternative is already in scope. The bug class surviving inside its own fix PR (meridianiq#117) is the diagnostic instance of this — humans corrected the boundary case and the AI-generated dispatch code reinvented the bug.

**False-positive shapes.** Be cautious before flagging:

- *Genuine bridging to a non-typed source.* If an exception originates from a C extension or a foreign-system error envelope whose only signal is a string, substring matching may be the only available signal. A Redis client receiving a `(error) ERR no such key` line from the wire has no typed-exception alternative until the *client library* introduces one. The fix is to push the discrimination into the lowest layer that can introduce a type; the substring match at the boundary is unavoidable.
- *Defensive duplicate of a typed check.* Some code does `except SpecificError: ...` and also `except Exception as e: if isinstance(e, SpecificError) or "..." in str(e): ...` as a belt-and-suspenders. The first form is correct; the second is over-defensive but not exactly this pattern (it's adjacent to [`unreachable-defensive-guard`](unreachable-defensive-guard.md)).
- *Logging-only substring use.* `logger.error(f"Auth failed: {e}"); if "disabled_client" in str(e): metrics.increment("oauth.disabled")` — the substring is used only for metrics/logging differentiation, not for control flow. Less severe; the defect path requires control-flow misrouting.
- *Asserting against documented stable error wording.* Some APIs explicitly document specific error messages as part of their public contract (rare, but it happens — particularly in old protocols where status codes were not available). Matching against documented stable wording is fine, *if* the document is real and the match is exact (not a substring of a possibly-internationalized prefix).

**Mutation operator hint.** A deterministic mutation that takes a clean typed-exception dispatch and rewrites it into substring matching produces this pattern from clean code. Variants:

- Take an `except SpecificError:` clause and replace with `except SuperType as e: if "<message>" in str(e):`
- Take a function that raises a typed exception and change the raise site to `raise ValueError(f"Message about <thing>")`, then update one caller to discriminate by substring
- Add a third overload to a typed exception so the same class now signals two distinct failure modes, then add a substring check at one call site to discriminate

These compose well with `inconsistent-error-handling` — a mutation that introduces three sibling adapters where one uses typed exceptions and two use substring matching produces the most dense AI-tell shape.

**Connection to [`surface-failure-modes-explicitly`](../notes/surface-failure-modes-explicitly.md) note.** This entry is one of four members of the typed-exception meta-family, alongside [`unreachable-defensive-guard`](unreachable-defensive-guard.md), [`inconsistent-error-handling`](inconsistent-error-handling.md), and [`swallowed-exceptions`](swallowed-exceptions.md). The four converge on a single piece of advice: surface failure modes explicitly through the type system; do not paper over them with defensive checks, string matching, sentinel returns, or silent swallows. The cross-cutting note formalizes the convergence. The mechanism shared across the family is *defensive shape disconnected from defensive substance* — code with the surface form of risk-handling that does not actually handle the risks.

**Connection to [`defensive-choice-with-justifying-comment`](../notes/defensive-choice-with-justifying-comment.md) note.** Brittle substring checks (`if "already exists" in str(exc):`) are often paired with comments explaining what the substring means — the comment carries the *contract* that the code should be enforcing through a typed exception. When the substring changes in a future refactor, the comment's promise is broken silently. This entry is one of 7+ in the cross-cutting note.

**The "tests agree with themselves" failure mode** observed in meridianiq#117 is worth flagging as a recurring connecting observation between this pattern and [`weak-test-assertion`](weak-test-assertion.md). A test that asserts the same string the production code matches against can break in lockstep with the production code — both pass against the current wording, both break when the wording changes. The fix (assert against typed exceptions, not against wording) is the same on both sides.
