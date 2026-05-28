---
name: unjustified-lazy-import
category: structure
difficulty: low
generation: evergreen
since_model: null
evidence_grade: observed
---

# Unjustified Lazy Import

## Code example

```python
def fetch_document(source: str) -> bytes:
    import hashlib
    import aiohttp

    digest = hashlib.sha256(source.encode()).hexdigest()
    async with aiohttp.ClientSession() as session:
        ...
```

`hashlib` is in the Python standard library. `aiohttp` is a heavy network library, but in this function it is used unconditionally on every call. Neither import is deferred for a circular-dependency reason; neither is an optional dependency the function might want to handle the absence of. Both should be at the top of the module.

A function-scope import is justified in roughly three situations:

1. **Breaking a real circular import** — module A needs something from module B which needs something from A. Moving the import inside the function lets Python finish loading both modules before the import is evaluated. This case should be documented with a comment (`# circular`, or similar) so the next reader knows it is intentional.
2. **An optional dependency** — the function only runs when a feature is enabled, and the dep should not be required for everyone using the package (`import torch` inside a function that only runs in GPU mode).
3. **Slow-import deferral for CLI startup** — a heavy import is moved out of the module's top-level scope so `cli --help` runs in <100ms. This is rare and tends to be obvious in context (a CLI tool's entry-point module).

The AI-typical shape is none of these. The import is a stdlib module, or a dependency that is already required everywhere else, or a module that is not in any import cycle with the current one. The lazy form is reflexive — the model has learned that "imports go inside functions" is a thing that happens in Python code, and produces it without checking whether the situation calls for it.

A tightened version:

```python
import hashlib
import aiohttp


def fetch_document(source: str) -> bytes:
    digest = hashlib.sha256(source.encode()).hexdigest()
    async with aiohttp.ClientSession() as session:
        ...
```

Dependencies are now visible at the top of the file; `ModuleNotFoundError` (if `aiohttp` is missing) surfaces at import time, not the first time `fetch_document` is called; tooling like grep or static analysis can find the dependency without inspecting function bodies.

The pattern has several visible sub-shapes in captured specimens:

- **Reflexive lazy stdlib imports** — `datetime`, `sys`, `hashlib` deferred to function scope for no plausible reason. Pure noise.
- **Same module imported many times in one file** — `from x import y` repeated inside five different functions with overlapping symbol lists, when one top-level import would cover all uses.
- **Clustered lazy imports** — 6+ lazy imports back to back in one function or in adjacent functions, the "sticky local pattern" shape.
- **Failure-mode deferral** — a heavy dependency lazily imported so its `ModuleNotFoundError` becomes a runtime call-site error rather than a startup error. Particularly costly in long-running servers.

## Mechanism

A language model generates each function body locally. When it writes an `import` statement inside a function, it is reproducing a real pattern that exists in the training corpus — function-scope imports do appear in published Python code, in all of the legitimate cases listed above. The training data carries the surface form but not the diagnostic reasoning that distinguishes a legitimate lazy import from a reflexive one.

The Stack Overflow and tutorial corpus reinforces the failure mode. Questions of the form *"I'm getting a circular import error, what do I do?"* have answers that frequently include *"Move the import inside the function that uses it"* as a quick fix. The model has seen this pattern many times. What it has not seen as often is the follow-up — the careful work of actually diagnosing whether a cycle exists, whether the cycle is necessary, and whether restructuring the module dependency graph would be cleaner. The shortcut shows up far more in training data than the principled fix does.

There is also a self-reinforcing local pattern within a single generation session, the same one that drives clusters of unreachable defensive guards in [`unreachable-defensive-guard`](unreachable-defensive-guard.md). Once the model has generated one function with a lazy import, the next few functions are more likely to also have lazy imports — the local-attention bias of transformer generation makes the recent pattern sticky. The captured specimens show this clearly: `seaberger/rag-lab` has 9 lazy imports in one file and 6-11 in adjacent files; `markus-michalski/vidcraft` has 5 lazy imports of the *same* module across one server file; `aabtzu/libertas-travel` flags `agents/admin/handler.py:182-187` for 6+ back-to-back lazy imports.

The training corpus may also be slightly biased toward function-scope imports relative to a representative production-code sample — tutorial code and minimal reproducer examples often place imports near their use sites for pedagogical clarity, even when the same code in a real codebase would not. The model's prior for "where does an import go" is consequently softer than it would be in a corpus dominated by production code.

This pattern is the **import-topology cousin of the [`swallowed-exceptions`](swallowed-exceptions.md) evergreen** — both involve defensive-shaped code disconnected from purpose. Swallowed exceptions paper over an unknown failure mode; unjustified lazy imports paper over an unknown import topology. In both cases the surface form is recognizable, the underlying diagnostic step is the one the model skipped.

The pattern is **AI-amplified, not AI-exclusive**. Human-written codebases also contain lazy imports — sometimes for legitimate reasons, sometimes from cargo-cult Stack Overflow advice. The honest claim is volume and clustering: AI-generated codebases tend to produce many lazy imports without justification (101 instances in one rag-lab codebase; 12 in aabtzu's; clusters of 5-9 in single files) where human-written codebases produce them sparsely, at architectural seams. Ruff's `PLC0415` lint rule exists precisely because the broader Python community has recognized this pattern as a hygiene concern independent of AI authorship; the AI-amplified observation is that the rule fires at significantly higher density on AI-generated code.

## Evidence / incident

Three captured specimens, each from a different audit framework across three different Python projects. Detailed specimen notes are not included in the public repository.

- **[aabtzu/libertas-travel#52](https://github.com/aabtzu/libertas-travel/issues/52)** — AI-tells audit follow-up; ~12 spots where `import` lives inside a function body, including `agents/admin/handler.py:182-187` (6+ lazy imports back to back) and `agents/itinerary/geocoding_worker.py` (lazy `datetime`, `sys`, `requests`). The project has an explicit CLAUDE.md convention "lazy import only for breaking real circular dep + `# circular` comment" — the convention exists *because* the AI keeps producing the pattern.
- **[seaberger/rag-lab#68](https://github.com/seaberger/rag-lab/issues/68)** — ruff PLC0415 lint cleanup framework; **101 instances** across the codebase, ~59 in pipeline_v3 core files, with single files containing 9, 7, 6, 11, 8 lazy imports each. Performance + readability + testing impact all named explicitly.
- **[markus-michalski/vidcraft#54](https://github.com/markus-michalski/vidcraft/issues/54)** — "Health Audit 2026-04-30 — Epic #51" framework; 7 lazy imports in one MCP server file, 5 of them importing the *same* `document_parser` module with different overlapping symbol lists. Audit explicitly names the deferred-failure-mode shape: "If the concern is that `pypdf`/`pdfplumber` may not be installed, that should fail at **server startup** with a clear error message, not silently at the call site."

Three independent audit frameworks (AI-tells audit; PLC0415 lint cleanup; Health Audit Epic) on three independent Python projects identifying the same pattern under different vocabularies — strong cross-context coverage. The patterns-draft notes also mention aabtzu's original AI-tells table at libertas-travel#48 ("Lazy imports inside functions everywhere — Reads as 'AI dodged a circular import without understanding it.' Some are real, most aren't necessary."), which is the abstract identification preceding the concrete enumeration in #52.

## Detection cues

What to look for in a diff or completion:

- **An `import` or `from X import Y` statement inside a function or method body.** The simplest, most reliable cue. Particularly suspect when the import is for a standard-library module (`datetime`, `sys`, `os`, `hashlib`, `json`) — there is essentially no legitimate reason to defer a stdlib import.
- **The same module imported in multiple function bodies in one file.** If `from tools.document_parser import parse_document` appears inside five different functions, the right place is one top-level import.
- **Clusters of lazy imports.** Two or more in adjacent functions, or several in one function — strongly suggests the "sticky local pattern" shape rather than independent architectural decisions.
- **No comment or annotation explaining the lazy form.** Legitimate lazy imports tend to be commented (`# avoid circular`, `# optional dep`, `# slow import for CLI startup`). A bare lazy import with no context is the AI-typical shape. The convention is not universal, but its *absence* combined with no plausible reason is the signal.
- **A lazy import in a long-running-server entry point.** The "fail at runtime, not startup" sub-shape is most damaging in code that runs continuously — MCP servers, web servers, daemons. The user-visible failure mode is *the tool call fails minutes after server startup*, not *the server fails to start with a clear error*.

The diagnostic question for any single lazy import: *why is this import inside the function?* If the answer is "to break a circular dependency" — verify the cycle actually exists (try moving the import to the top and see if it errors). If the answer is "optional dependency" — verify the function genuinely is only called in the opt-in code path. If the answer is "the LLM put it there and the developer didn't push back" — that is the unjustified lazy import.

## Notes

**Category `structure`.** Lazy imports are a module-level structural concern (import topology, dependency graph). The fit is reasonable but not perfect — they also have a defensive-programming flavor (deferring a possible failure) that lines them up with [`unreachable-defensive-guard`](unreachable-defensive-guard.md).

**Difficulty rated `low`.** The visual cue is unambiguous — an `import` keyword inside a function body is immediately visible. The diagnostic step (does a real circular dep exist?) is mechanical: try moving the import to the top and run the test suite. The reason this is not zero-effort is the false-positive cases below; a reader needs to know which lazy imports are legitimate.

**The pattern is AI-amplified, not AI-exclusive.** Humans write lazy imports too. The AI-amplified claim rests on volume and clustering — 101 instances in one codebase, 9 in one file, 5 imports of the same module in one server — at densities that are uncommon in human-written code. The ruff PLC0415 rule exists independent of AI; the new observation is that it fires much more densely on AI-generated code.

**False-positive shapes.** Be cautious before flagging:

- *Genuine circular-import breaks.* Module A and module B truly need each other; one of them defers a function-scope import to make Python's import machinery happy. These are real, and the right fix is usually a comment (`# circular`) on the deferred import. The pattern only fires when the cycle does *not* exist — verify by attempting to hoist the import to the top.
- *Optional dependencies.* `import torch` inside a function that only runs in GPU mode, where the package is intended to work without torch installed. The signal is whether the rest of the module also handles the dep being absent (try/except around the import, feature flag, etc.). A lone lazy import of a ubiquitous dep is unjustified; a lazy import of an opt-in heavy dep that is part of a documented optional-extra pattern is legitimate.
- *Slow-import-for-CLI-startup.* Small CLI tools sometimes defer heavy imports so `cli --help` is fast. Usually obvious from context (you are in a CLI entry-point module, the import is for a known-slow library like `pandas` or `torch`). Real, but rare.
- *Imports inside `if TYPE_CHECKING:` blocks.* The mypy / pyright convention for type-only imports that should not exist at runtime. Different shape (block-level, not function-level), but worth noting because it can superficially look similar.

**Mutation operator hint.** A deterministic mutation that takes a clean function and inserts an unjustified lazy import produces this pattern from clean code. Variants:

- Take a top-level `import X` and move it inside the function that uses it (no comment)
- Add an in-function `import X` for a module already imported at the top of the file (creating redundancy)
- Cluster: lazy-import 3+ unrelated stdlib modules in adjacent functions
- Take a top-level `from X import a, b, c` used in multiple functions and replace with per-function `from X import a` / `from X import b` / `from X import c` (the vidcraft sub-shape)

These compose well with `swallowed exceptions` — a lazy import wrapped in a bare `try/except: pass` produces a particularly nasty deferred-failure shape where the missing dep is silently swallowed.

**Ruff PLC0415 cross-validation.** The Python community has already codified this pattern as a lint rule (`import-outside-top-level`). That the rule exists with broad adoption is evidence that human reviewers consider unjustified lazy imports a hygiene concern; that AI-generated codebases trigger the rule at unusually high density is the AI-amplified observation. A reasonable workflow for any AI-assisted Python codebase is to enable PLC0415 in ruff and review the firings periodically.

**Adjacent patterns.** The aabtzu libertas-travel#52 specimen also covers Section C ("Mixed error-return styles") which is a separate candidate pattern — the local-fluency-without-global-consistency family. That candidate is documented but not yet promoted.

**Connection to [`codified-guidance-is-insufficient`](../notes/codified-guidance-is-insufficient.md) note.** aabtzu's CLAUDE.md states "lazy import only for breaking real circular dep + `# circular` comment"; the audit's ~12 captured instances violate this convention. ruff `PLC0415` is a widely-adopted community lint rule that exists precisely because the pattern is widespread. The combination of project-internal CLAUDE.md + community lint rule + persistent violations is the multi-form codified-guidance-insufficient shape. This entry is one of 10+ in the cross-cutting note.
