---
name: swapped-args
category: control-flow
difficulty: medium
generation: evergreen
since_model: null
evidence_grade: observed
---

# Swapped Args

## Code example

```python
# main.py — defective call site
return geo.create_gpkg_datastore(workspace, name, file_path)
```

```python
# geoserver_rest.py — actual function signature
def create_gpkg_datastore(path: str, store_name: str, workspace: str) -> dict:
    """Upload a GeoPackage and register it as a datastore."""
    ...
```

The call passes `(workspace, name, file_path)` where the function expects `(path, store_name, workspace)` — first and third positional arguments swapped. All three arguments are strings, so Python does not error. The library code reaches into `path` expecting a file system path and gets a workspace name; it reaches into `workspace` expecting a routing parameter and gets a file path. The function does whatever it does with the wrong inputs — sometimes it errors loudly, but more often it produces a degenerate-but-non-crashing result that looks like the function ran but accomplished nothing.

A tightened version forces keyword arguments at the call site:

```python
return geo.create_gpkg_datastore(
    path=file_path,
    store_name=name,
    workspace=workspace,
)
```

The order at the call site is now irrelevant; the names carry the binding. PEP 3102 keyword-only arguments (declaring args after a bare `*` in the signature) are the stronger version of this defense — they make positional passing impossible, foreclosing the entire class of bug at the function-definition level rather than at each call site.

The pattern has several distinct sub-shapes in captured specimens:

- **Same-type 2-argument swap** — two arguments of the same type get swapped; the function runs with both in the wrong slots and produces a silently-wrong result. Captured in OrbFrontend/Orb#34, where two `list[dict]` arguments to a lorebook-injection function were swapped; the function returned an empty string because it scanned the wrong list for the wrong fields.
- **Different-type swap that Python's duck-typing tolerates** — a `list` is passed where a `str` was expected and a `str` where a `list` was expected; both are iterable, so the function does not crash but downstream consumers receive garbage. Captured in SuperAce100/websight#2, where the chat history and base64 image string were swapped on a VLM call.
- **Multi-argument permutation across positions** — three arguments in `(workspace, name, file_path)` order at the call site, library expects `(path, store_name, workspace)`. The "name" position happens to match, the first and third positions are swapped. Captured in mahdin75/geoserver-mcp#5.
- **Adjacent sibling functions repeating the same swap** — two MCP tool wrappers both call into the library with the same (wrong) ordering, because they were generated in adjacent generation contexts and share the same defective prior. Sticky-local-pattern observation, also captured in mahdin75/geoserver-mcp#5.
- **Same function called correctly at one site and incorrectly at another** — orchestrator.py uses the right order; main.py's context-size endpoint uses the wrong order. Captured in OrbFrontend/Orb#34. This is per-call-site-generation evidence: the model's prior about argument order is not a per-function constant but a per-context probability distribution.

All sub-shapes share the same root mechanism: the model produced a function call whose form is locally fluent (right name, right number of args, types that pass) but whose argument *order* does not match the function's actual signature.

## Mechanism

A language model generates each function call site in its own step. The form of a call — function name, parenthesis, comma-separated arguments — is highly fluent at the token level; the corpus contains millions of function calls and the model has learned the surface pattern with very high confidence. The order in which arguments are passed positionally is a semantic property tied to the *callee's signature*, not to the *caller's local context*. The model knows the function name and that some arguments are needed; the specific positional order requires looking up the callee's signature.

For popular library APIs in the model's training corpus, this works well: `requests.get(url, params=...)` is so over-represented that the model produces the right ordering effortlessly. For less-popular APIs, internal helper functions, recently-renamed parameters, or APIs whose convention differs from a similar-looking standard convention, the model falls back on priors — and the priors can disagree with the actual signature.

Three concrete failure paths are visible in the captured specimens:

**Path 1: The model carries the caller's variable order into the call.** The caller has variables `workspace`, `name`, and `file_path` in scope (because that is the MCP tool's signature). The model writes `geo.create_gpkg_datastore(workspace, name, file_path)` — preserving the caller's local ordering — without checking that the library's signature is `(path, store_name, workspace)`. The geoserver-mcp specimen shows this exactly: the MCP tool's signature dictates the local variable order, the model carried that order into the wrapped library call.

**Path 2: The model's prior for the function's convention disagrees with the actual function.** For a function like `compute_lorebook_injection_block(messages, entries, macros)`, the model may have multiple priors about which `list[dict]` goes first — `messages` first because "chat-message-first" is a common convention in chat APIs, or `entries` first because "data-first, configuration-second" is a different common convention. When two priors disagree, the model picks one at the moment of generation. The Orb specimen shows both priors active in the same codebase: orchestrator.py got it right, main.py got it wrong, the model was sampling from a distribution over both orderings.

**Path 3: Per-call-site generation produces different orderings for the same function.** Even within a single project, two call sites generated in different contexts can have different orderings, because the attention context of each generation step is different. The Orb specimen is the cleanest instance: one site correct, one site wrong, same function. This is the local-fluency-without-global-consistency mechanism applied at the function-call boundary — analogous to the sibling-divergence shape in [`inconsistent-error-handling`](inconsistent-error-handling.md), but at the call-order rather than at the error-shape level.

The training corpus reinforces the failure mode. APIs in real-world Python code do not have a single consistent convention for argument order. Some libraries put the resource first (`f.write(data)`); some put the action first (`copy(src, dst)` but `cp src dst`); some put the target last (`shutil.copy(src, dst)`); some put the target first (`os.rename(src, dst)` where `src` is the existing path and `dst` is the new path — and the order can flip depending on the operating system convention being mimicked). The model has seen all conventions; it cannot, from token prediction alone, know which the current library uses.

Static analysis cannot catch swapped-args bugs when the argument types are compatible. Python type checkers (mypy, pyright) verify that each argument's type matches the parameter's declared type — and if both arguments are `str`, both pass the type check. A swapped pair of compatible types is invisible to the type system. The bug manifests at runtime as silently-wrong output, not as an exception.

This pattern is the **third and final entry in the original project plan's named-evergreen trio** (alongside [`off-by-one`](off-by-one.md) and [`swallowed-exceptions`](swallowed-exceptions.md)). The trio shares the property of producing code that is *locally fluent at the token level but defective at the level of what the function is doing*. Off-by-one and swapped-args are the two cleanest "token-fluent but semantically defective" patterns; swallowed-exceptions is similar but operates at the control-flow level rather than the call-site level. With swapped-args landed, the named evergreens form a small recognizable cluster within the taxonomy.

The pattern is **AI-amplified, not AI-exclusive**. Human developers swap arguments constantly — particularly in unfamiliar libraries, under time pressure, or when using positional args for clarity-of-line-count rather than clarity-of-meaning. The AI-amplification claim rests on:

- *Volume*: AI-generated code makes many more positional-arg function calls than typical human-written code, because the model defaults to positional passing rather than keyword passing.
- *Consistency-across-call-sites*: A human writing a function call generally writes one call site at a time and looks at the signature; an AI generating multiple call sites in adjacent contexts can produce different orderings for the same function (Orb shape) or the same wrong ordering across adjacent siblings (geoserver-mcp shape) without noticing.
- *Invisibility to the model's self-checks*: When the AI runs a quick mental check by reading its own output, the call site *looks correct* because it has the right shape. The semantic bug requires comparing to the signature, which is not part of the local context of the call-site generation step.

## Evidence / incident

Three captured specimens, each from an AI-coded Python codebase, each demonstrating a different sub-shape. Specimens live in `evidence/github-issues/`.

- **[OrbFrontend/Orb#34](https://github.com/OrbFrontend/Orb/issues/34)** — same-type 2-argument swap with silent degenerate output. `compute_lorebook_injection_block(lorebook_entries, messages)` called instead of `(messages, entries)`. The function silently returns empty string when called wrong. *The same function is called correctly at another site* — per-call-site generation evidence. Audit framework: "Codex review during AGENTS.md audit." Specimen: [OrbFrontend-Orb-34.md](../../evidence/github-issues/2026-05-15-OrbFrontend-Orb-34.md).
- **[SuperAce100/websight#2](https://github.com/SuperAce100/websight/issues/2)** — different-type 2-out-of-3 positional swap across the agent/VLM boundary. `websight_call(next_action, history, image_base64)` called instead of `(prompt, image_base64, history)`. The VLM receives the chat history where an image was expected; Python's duck-typing tolerates the call, action prediction degrades silently. Browser agent project with custom fine-tuned VLM. Specimen: [SuperAce100-websight-2.md](../../evidence/github-issues/2026-05-15-SuperAce100-websight-2.md).
- **[mahdin75/geoserver-mcp#5](https://github.com/mahdin75/geoserver-mcp/issues/5)** — multi-argument permutation in adjacent sibling tool wrappers. `create_gpkg_datastore(workspace, name, file_path)` and `create_shp_datastore(workspace, name, file_path)` both pass arguments in the wrong order; the library expects `(file_path, name, workspace)`. Sticky-local-pattern shape — two adjacent MCP tools repeat the same swap. MCP server connecting LLMs to GeoServer. Specimen: [mahdin75-geoserver-mcp-5.md](../../evidence/github-issues/2026-05-15-mahdin75-geoserver-mcp-5.md).

Three different AI-related domains (LLM roleplay frontend; vision-language agent; MCP tool server), three different swap shapes (same-type-2-arg, different-type-2-of-3, multi-arg-permutation), three different identifier framings (Codex review against AGENTS.md; project-internal review; project-internal review). Cross-context coverage is strong.

Supplementary references:

- `matsengrp/phippery#197` — `load_from_csv` calls `dataset_from_csv(counts_matrix, peptide_table, sample_table)` but the function expects `(peptide_table_filename, sample_table_filename, counts_table_filename)` — three-argument cyclic permutation. Captured as adjacent shape; AI-authorship of the underlying code is not clearly established.
- `Git-on-my-level/codex-autorunner#899` (closed) — "Prevent swapped-argument bugs with keyword-contract enforcement for high-risk APIs" — *prescriptive* issue rather than a bug specimen, but worth noting because it represents a project explicitly building defenses against this pattern. The "keyword-contract enforcement for high-risk APIs" framing aligns with the entry's keyword-arguments cure.
- `crytic/slither#2947` — *security tooling enhancement request*: "add mutator to swap argument calling order if arguments are of the same type" — explicitly identifies this as a mutation-testing primitive worth implementing. Mutation testing tools are recognizing swapped-args as a defect-class worth fuzzing.

## Detection cues

What to look for in a diff or completion:

- **Function calls with multiple positional arguments of the same or compatible types.** Particularly suspect when the function takes multiple `str`, multiple `int`, multiple `list`, multiple `dict`, or multiple `Path` parameters. Static analysis cannot catch a swap between compatible types; manual review against the signature is the only check.
- **Call sites where local variable names match the function's parameter names in form but not in order.** A function `f(messages, entries)` called as `f(entries, messages)` because the local variables `entries` and `messages` were defined or accessed in that order. The cue: compare the order of named-similar variables at the call site to the order in the signature.
- **Adjacent sibling functions calling into the same library function.** If `create_gpkg_datastore` and `create_shp_datastore` both wrap a library call, check that both call sites use the same ordering — and that the ordering matches the library's signature. The sticky-local-pattern shape produces matching-wrong orderings in adjacent siblings.
- **The same external function called at multiple sites in the codebase.** If `prompt_builder.compute_X(a, b, c)` is called at five sites, all five should have the same ordering. A site where the ordering differs is either the bug or the lonely correct one. Per-call-site generation produces this divergence.
- **Function calls with positional args where the function could plausibly take its args in either order.** If `merge(a, b)` and `merge(b, a)` could both type-check, suspect the call. The diagnostic question is *which one is the function actually doing*?
- **Calls into less-popular libraries with three or more positional arguments.** Popular APIs have stable enough corpus presence that the model is unlikely to confuse the order. Less-popular libraries are the AI-amplified failure surface.

The diagnostic question for any candidate: *do the positions at the call site match the positions in the signature?* The fastest verification is a single jump-to-definition; the bug is visible the moment the two are read side by side. The cure for any project: prefer keyword arguments at function-call sites, especially for any function with 3+ args or with 2+ args of the same type. Keyword-only arguments (PEP 3102 `*`) are the strongest version of the cure, foreclosing the bug at the definition site.

## Notes

**Category `control-flow`.** Second entry in this category, joining [`off-by-one`](off-by-one.md). The fit is imperfect — swapped-args is technically a defect at the function-call boundary, not strictly a control-flow concern. The closer category would be something like `function-call` or `interface`, but the project plan calls for deferring category refactoring until ~10 entries. The `control-flow` umbrella is interpretable enough to cover "calling-convention defects" alongside iteration-and-indexing defects; the two patterns share the meta-theme of *token-fluent but semantically defective forms*. Worth revisiting at the category-refactor pass.

**Difficulty rated `medium`.** The surface is universal — any positional-arg call could in principle have its args swapped. The defect is visible only when the reader checks the call site against the function signature. A reader who only reads the call site and trusts the variable names will not flag it. Once the reader knows the pattern, the diagnostic step is mechanical (jump to definition). Same difficulty rating as [`off-by-one`](off-by-one.md), with which this pattern shares the meta-mechanism.

**This completes the original project plan's named evergreens.** CLAUDE.md identified three evergreens at the start: `swallowed-exceptions`, `off-by-one`, `swapped-args`. All three have now landed. The trio forms a small recognizable cluster within the taxonomy and shares the meta-property of being *the most well-known defect classes in Python development*. They serve as the taxonomy's anchor entries — readers familiar with the named evergreens will see the project covers the canonical pattern set before reaching the more AI-specific entries.

**The pattern is AI-amplified, not AI-exclusive.** Restated for emphasis: every human Python programmer has written a swapped-args bug, particularly in unfamiliar libraries. The AI-amplification dimensions are volume (the model defaults to positional args rather than keyword args), consistency-across-call-sites (different sites get different orderings, or adjacent siblings repeat the same wrong ordering), and invisibility to the model's self-checks (the call site *looks correct* because it has the right shape).

**False-positive shapes.** Be cautious before flagging:

- *Functions whose argument order is intentionally symmetric.* `max(a, b)`, `min(a, b)`, `set.union(a, b)` — order does not matter. Don't flag.
- *Functions with documented argument order conventions that differ from the call site's local naming.* If the call site has local variables `winner` and `loser` and calls `compare(loser, winner)`, that may be correct if the function's first argument is intentionally "the lower-priority one." The cue is whether the call site's choice is *documented* or *casual*.
- *Calls that use both positional and keyword arguments deliberately.* `connect(host, port=8080, timeout=30)` — `host` is positional because there is no ambiguity; `port` and `timeout` are kwargs because the order between them would be ambiguous. This is the right balance, not a bug.
- *Calls into functions that accept `*args` or `**kwargs`.* Variadic functions may legitimately accept arguments in any order or with flexible structure. Don't flag calls into them based on order alone.
- *Test fixtures or mock setups where order is intentionally illustrative.* `mock.return_value = expected_output` — these are not swapped args; they are assignments.

**Mutation operator hint.** A deterministic mutation that swaps two adjacent positional arguments of compatible types in a function call produces this pattern from clean code. Variants:

- Swap two `str` positional args at a random call site
- Swap two `int` positional args at a random call site
- Swap the second and third positional args (preserves the first, swaps the rest)
- Cyclically permute three+ positional args (the phippery shape)
- Find a function called at multiple sites and swap args at one site while leaving others correct (the Orb shape)
- Find two sibling functions wrapping the same library call and swap args identically at both (the geoserver-mcp shape)

These are particularly clean primitives for the v0.5 mutation playground because:
1. The mutation is purely local (one call site) and the diff is small (re-ordering args)
2. The mutation almost always preserves type-correctness, so static-analysis tooling can't catch the mutated version
3. The mutation has high probability of producing a behaviorally-different program (the function does something different with reordered args)

slither's #2947 issue ("add mutator to swap argument calling order if arguments are of the same type") explicitly identifies this as a mutation-testing primitive — the mutation-testing community is converging on the same operator independently.

**Connection to the named-evergreen trio.** [`off-by-one`](off-by-one.md), [`swallowed-exceptions`](swallowed-exceptions.md), and swapped-args together form the original project plan's anchor set. Off-by-one and swapped-args share *token-fluent-but-semantically-defective* as the meta-mechanism — both produce code that has the right shape but does the wrong thing. Swallowed-exceptions is slightly different — it's *token-fluent-and-syntactically-defensive-but-semantically-empty*. The three together provide a useful onramp for readers who already know the canonical Python anti-patterns; they can recognize the names before encountering the AI-specific entries.

**The fix prescription is unusually clean for this pattern: use keyword arguments.** Across all three captured specimens, the recommended cure converges: stop using positional arguments at the call site, use keyword arguments by name. This is a low-effort, high-impact convention that any AI-assisted Python codebase can adopt as a project-wide rule. Worth mentioning when discussing AI-assisted development practices: *"prefer keyword arguments for any function call with 2+ args of compatible types"* is a one-line guideline that prevents a meaningful class of bugs without forbidding any pattern entirely. PEP 3102 keyword-only arguments (`def f(*, a, b, c)`) are the strongest version of the same defense.

**Connection to [`same-project-knows-right-pattern`](../notes/same-project-knows-right-pattern.md) note.** The Orb specimen is the cleanest *per-call-site* instance of this cross-cutting observation: the same function is called correctly at `orchestrator.py:464` and incorrectly at `main.py:1611`. The model's prior about argument order is not a per-function constant but a per-context probability distribution. The note now spans 9 entries; swapped-args is one of its founding members.
