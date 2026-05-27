---
name: inconsistent-error-handling
category: error-handling
difficulty: medium
generation: evergreen
since_model: null
evidence_grade: observed
---

# Inconsistent Error Handling

## Code example

Three sibling client classes implementing the same `chat()` interface in a multi-provider LLM gateway. Two of them propagate exceptions; the third catches them and returns an error string.

```python
class OllamaGPTClient(GPTClient):
    def chat(self, prompt: str) -> str:
        try:
            return self._call_api(prompt)
        except Exception as e:
            return f"Error communicating with Ollama API: {str(e)}"


class ChatGPTClient(GPTClient):
    def chat(self, prompt: str) -> str:
        return self._call_api(prompt)


class ClaudeGPTClient(GPTClient):
    def chat(self, prompt: str) -> str:
        return self._call_api(prompt)
```

Each of the three classes is *correct in isolation*. `OllamaGPTClient.chat()` returns a string, signals errors as strings. `ChatGPTClient.chat()` returns a string, signals errors by raising. Both are reasonable interfaces a Python developer could pick. The defect is that they are *the same interface* — `GPTClient.chat()` — yet they have different error contracts. A caller of `MultiProviderGPTClient.chat()` cannot try/except some providers and check return values for others; they have to know which provider is active.

The diagnostic question is comparative, not local: each implementation looks fine on its own, but reading the three together exposes the divergence. The pattern is invisible at the function-level review that catches most defects.

Two adjacent shapes share the same root mechanism. **Sibling-handler divergence:** several Flask route handlers in one module use `return body_dict, status` tuples while sibling handler modules use `json_ok(...)` / `json_err(...)` helpers — both legitimate Flask shapes, but mixed without commitment. **Sibling-module divergence:** four backend implementation files use four different error strategies (swallow-and-return-empty, swallow-and-continue, raise-custom-exception, raise-builtin) for the same conceptual role of "handle errors during backend-specific data acquisition." All three sub-shapes are documented in the captured specimens; all share the same generation mechanism.

A consistency cure typically requires one of three commits: every implementation raises (the loud-failure-mode contract), every implementation returns a structured result (the explicit `Result` / `Either`-style contract), or every implementation returns a sentinel of a clearly-distinct type (`None` for absence, exception for failure). Any of the three is a reasonable choice; mixing them is the defect.

## Mechanism

A language model generates each function or class body in its own step, with attention concentrated on the immediately surrounding tokens — the docstring, the parameter list, the function signature, the few lines preceding it. The model does not have a global view of "what error contract this module has committed to." It produces a body that is locally plausible given the recent context.

When generating `OllamaGPTClient.chat()`, the relevant local context is the Ollama Python SDK's idiom. Ollama tutorials and example code in the training corpus frequently include a `try/except: return f"Error: {e}"` shape — partly because Ollama's local-server runtime can fail in many ways, and the tutorial author wants the example to be runnable. When generating `ChatGPTClient.chat()`, the local context is OpenAI's SDK, which raises exceptions; the model produces raise-on-error. When generating `ClaudeGPTClient.chat()`, the local context is Anthropic's SDK, which also raises; the model produces raise-on-error. Each implementation correctly reflects the conventions of its provider's training-corpus presence. What is missing is the cross-class consistency check.

Attention falls off with token distance even within a long context window — the model's predictions weight nearby tokens more heavily than far-away ones, even when both are technically visible. By the time the model is generating the third sibling class, the first one is many tokens away — the attention weights on the first class's choices are smaller than the attention weights on the immediate Ollama-tutorial-style context. The model is not literally "forgetting" the first class; it is allocating less of its predictive capacity to consistency-with-it than to local-plausibility-of-the-current-class. The result is each implementation being correct on its own, the set being inconsistent.

Two corollaries follow:

1. The pattern is most visible when sibling implementations live in *separate files* (different `windows.py`, `linux.py`, `pipewire_native.py`; different `ollama.py`, `openai.py`, `anthropic.py`). Each file is its own generation context. When the implementations are in *one file* close together, the model is more likely to reproduce the same shape across them — the local-attention force that drives the pattern when files are separate becomes a unification force when they are adjacent.
2. The pattern can survive when a project has an explicit consistency convention (CLAUDE.md, style guide). The convention exists in a different scope than the local-generation step; the model attends to nearby code more strongly than to global documentation. The captured aabtzu/libertas-travel specimen is exactly this case: the project's CLAUDE.md says "pick one and stick with it," and the generated code mixed two shapes within a single handler file anyway.

The training corpus reinforces the failure mode. Real-world Python code does often mix error-handling conventions in the same codebase — different teams, different historical periods, copy-paste-from-different-tutorials origins. So the model has seen the inconsistent pattern many times. What it has seen less of is the principled consistency commit: a single PR that imposes one error contract across a whole codebase. That kind of refactoring PR is rare in training data because it is rare in real life.

This pattern is the **API-shape cousin of [`near-identical-siblings`](near-identical-siblings.md)**. Both stem from the model producing parallel implementations locally without enforcing a global structure. Near-identical-siblings produces three blocks that should be one loop; inconsistent-error-handling produces three implementations that should share one error contract. The shared mechanism is *local generation without global consistency check*; the surface forms differ because the kind of repetition is different.

The pattern is **AI-amplified, not AI-exclusive**. Human developers also produce inconsistent error handling, especially when a codebase grows through contributions from multiple authors or when refactors are abandoned partway. The AI-amplified claim is that AI-generated codebases produce sibling implementations of one role with divergent error contracts *during initial authorship* — the inconsistency is present from the first commit, not introduced by drift over time. The captured specimens are all from young codebases where the inconsistency is the original generated state, not the result of historical accumulation.

## Evidence / incident

Three captured specimens, each from a different Python codebase, each at a different organizational granularity (handler, class, module). All confirmed AI-authored. Specimens live in `evidence/github-issues/`.

- **[aabtzu/libertas-travel#52 Section C](https://github.com/aabtzu/libertas-travel/issues/52)** — sibling-handler divergence. Four routes in `agents/trips/handler.py` return `(body, status)` tuples while sibling handler modules (`agents/auth/`, `agents/admin/`) use `json_ok` / `json_err` wrapper helpers. The project's CLAUDE.md says "pick one and stick with it" — the convention exists and the generated code violated it. Specimen: [aabtzu-libertas-travel-52-error-returns.md](../../evidence/github-issues/2026-05-15-aabtzu-libertas-travel-52-error-returns.md).
- **[netdevops/hier-config-gpt#10](https://github.com/netdevops/hier-config-gpt/issues/10)** — sibling-class divergence. Three LLM-provider client classes implement `chat()`. `OllamaGPTClient` swallows exceptions and returns an error string; `ChatGPTClient` and `ClaudeGPTClient` let exceptions propagate. Downstream `MultiProviderGPTClient` cannot distinguish a network failure from a valid response without string-matching the first few characters of the return value. Specimen: [netdevops-hier-config-gpt-10.md](../../evidence/github-issues/2026-05-15-netdevops-hier-config-gpt-10.md).
- **[m96-chan/ProcTap#32](https://github.com/m96-chan/ProcTap/issues/32)** — sibling-module divergence. Four backend implementation files in `src/proctap/backends/` use four different error strategies (Windows/Linux: swallow + `return b''`; core worker: swallow + `continue`; PipeWireNative: raise custom exceptions). Confirmed AI-authored via explicit "🤖 Generated with Claude Code" commit trailers. Specimen: [m96-chan-proctap-32.md](../../evidence/github-issues/2026-05-15-m96-chan-proctap-32.md).

Three different identifiers (one calibrated AI-tells reviewer, two general code-quality audits using the standard "inconsistent error handling" vocabulary), three different project domains (travel-app handlers, LLM-gateway client classes, audio-capture backend modules), three different organizational granularities. Cross-axis variance is broad — the same root mechanism produces the pattern across modes that look superficially unrelated.

## Detection cues

What to look for in a diff or completion:

- **Multiple files in one directory implementing the same conceptual role.** `backends/windows.py`, `backends/linux.py`, `backends/pipewire_native.py` — read the error-handling sections of each and compare. If three of them use `try/except: return sentinel` and one uses `raise custom_error`, the outlier is interesting; if all four use different shapes, you have the full pattern.
- **Adapter/client classes for heterogeneous backends.** `OllamaGPTClient`, `ChatGPTClient`, `ClaudeGPTClient`. Each class wraps a provider's SDK; each was likely generated in a context conditioned on that provider's tutorial style. Compare their error-shape choices.
- **Route handlers across files in a web app.** Flask blueprints often have `agents/X/handler.py`, `agents/Y/handler.py`, etc. The error-return shape (tuple vs wrapper, raise-and-let-Flask-handle vs catch-and-return-JSON) should be uniform; if it is not, the inconsistency was likely generated.
- **A single file mixing two error-return shapes.** Within `agents/trips/handler.py`, some routes return `(body, status)` tuples and others return `json_ok(...)`. This is the most local form of the pattern and the easiest to spot, because both shapes are visible in one view.
- **A codebase that has an explicit error-handling convention in CLAUDE.md or style guide that the code does not enforce.** A convention that is honored everywhere needs no audit; a convention that has been documented because the AI keeps drifting from it is a strong signal.

The diagnostic question for any candidate: *do the other implementations of this role agree?* If yes, the local code is fine. If no, you have the pattern. The next question is *which one is right?* — usually answered by the project's most-used surface (the rest of the codebase), the most loud-failing option (raise), or by the project's explicit convention if one exists.

## Notes

**Category `error-handling`** matches the template's example category list. First entry in this category for the project. The category fits cleanly — every captured specimen is about error-return contracts.

**Difficulty rated `medium`.** The pattern is invisible if you only look at one function or class. The diagnostic move requires reading the parallel implementations side by side, which is more work than line-level review. A reader who only inspects the function-under-review will not flag the divergence. Once the pattern is named and the reader knows to compare across siblings, the rate of detection should improve substantially — the pattern is *medium* in raw difficulty, *low* once you know to look.

**The pattern is AI-amplified, not AI-exclusive.** Human-written codebases produce this too, usually through historical drift or multi-author contributions. The AI-amplified claim rests on it being present from the first commit, generated as the initial state of the codebase rather than accumulated over time. The captured specimens are all from young codebases where the inconsistency was the original generated form.

**False-positive shapes.** Be cautious before flagging:

- *Genuine asymmetry between providers/backends.* If `OllamaGPTClient` has built-in retry-with-backoff and OpenAI's SDK does not, the Ollama client may legitimately need different error-handling shape to integrate with the retry logic. The signal is whether the asymmetry is *motivated by the upstream API* or is *just inconsistent.*
- *Adapter classes intentionally normalizing different upstream APIs to one contract.* This is the *opposite* of the pattern: the adapter classes look different on the inside but expose the same contract on the outside. Reviewing the public method's error shape is the key check.
- *Different versions of an interface during a migration.* If the project is in the middle of moving from old-style tuple returns to new-style wrapper helpers, the inconsistency is a known interim state and there is usually a tracking issue or a TODO comment. The pattern only fires when the inconsistency is *not* part of a documented migration.
- *Layered architecture where some layers raise and others catch.* It is normal for an internal helper to raise and an outer API handler to catch and translate. The inconsistency only matters within a layer of equivalent role.

**Mutation operator hint.** A deterministic mutation that takes a consistent set of N sibling implementations and randomly changes one's error contract produces this pattern from clean code. Variants:

- Take three sibling classes that all raise and add `try/except: return sentinel` to one of them
- Take four sibling modules that all return `None` on error and change one to return `b''` instead
- Take a route module that uses `json_ok` / `json_err` wrappers and replace one route's return with a bare tuple

These compose well with `near-identical-siblings` — a mutation that creates two near-identical siblings *and* makes one have inconsistent error handling produces the most dense AI-tell shape.

**Connection to [`surface-failure-modes-explicitly`](../notes/surface-failure-modes-explicitly.md) note.** This entry is one of four members of the typed-exception meta-family, alongside [`unreachable-defensive-guard`](unreachable-defensive-guard.md), [`brittle-error-detection`](brittle-error-detection.md), and [`swallowed-exceptions`](swallowed-exceptions.md). Across all three captured specimens for this entry, the prescribed fix moved toward raising exceptions and surfacing failures explicitly rather than returning sentinel values — the same advice the four entries converge on. The cross-cutting note formalizes the convergence.

**Adjacent patterns deferred.** The aabtzu#52 audit also flagged naming inconsistencies (`fla` comment violating project rule; inline SQL not following SCREAMING_SNAKE_CASE) and aabtzu calls all of these "AI follows rules locally but doesn't apply them broadly." The error-handling case is the most defect-producing and earns the entry. The naming-consistency variants are deferred — they are real instances of the same root mechanism but lower-impact, and consolidating them under one umbrella entry would dilute the specific defect path that the error-handling variant has.
