---
name: mutable-default-arguments
category: language-pitfall
difficulty: low
generation: evergreen
since_model: null
evidence_grade: observed
---

# Mutable Default Arguments

## Code example

```python
def append_to(item, items=[]):
    items.append(item)
    return items

# Hidden across many calls:
append_to(1)              # returns [1]
append_to(2)              # returns [1, 2]   <-- shared default
append_to(3)              # returns [1, 2, 3]
append_to(4, items=[])    # returns [4]      <-- pass-explicit clears it
append_to(5)              # returns [1, 2, 3, 5]
```

The function works correctly the first time. On the second call, the *same default list* is still attached to the function — `items=[]` was evaluated *once* at function definition time, and that one list object is reused on every call that omits `items`. Mutations to the default leak across calls.

The same pattern with a `dict`:

```python
def process(config, options={}):
    options.update(config.get("overrides", {}))
    return options

process({"overrides": {"a": 1}})        # options is now {"a": 1}
process({"overrides": {"b": 2}})        # options is now {"a": 1, "b": 2}  <-- "a" leaked
```

The Pydantic v2 form is the same trap with a slightly different surface:

```python
from pydantic import BaseModel
from typing import List

class State(BaseModel):
    errors: List[str] = []           # mutable default; can leak state across instances
```

The Pydantic-correct form uses `Field(default_factory=list)`:

```python
from pydantic import BaseModel, Field
from typing import List

class State(BaseModel):
    errors: List[str] = Field(default_factory=list)   # fresh list per instance
```

The tightened version of the function form replaces the mutable default with `None` and assigns a fresh container inside the body:

```python
def append_to(item, items=None):
    if items is None:
        items = []
    items.append(item)
    return items
```

The pattern has several visible sub-shapes in captured specimens:

- **Clustered same-template defaults across sibling methods** — multiple `static`/`def` methods in one class all have `Optional[dict] = {}` defaults; the model produced the same wrong template at each signature. Captured in hiyouga/LlamaFactory#10476 (4 instances of `input_kwargs: Optional[dict[str, Any]] = {}` in `HuggingfaceEngine`).
- **Pydantic field bare-default drift from sibling `Field(default_factory=...)` correct pattern** — a Pydantic model in a sibling state-class family uses bare `List[str] = []` while 4+ sibling models correctly use `Field(default_factory=list)`. Captured in JNK234/Quibo#25. Same-project-knows-right-pattern at the Pydantic-field-default layer.
- **Single literal `[...]` / `{...}` default in a utility function** — `def f(..., column_names=['metric', 'value'], ...)`. Latent (the body only reads, doesn't mutate), but the footgun remains. Captured in siege-analytics/siege_utilities#493 via "Hostile-review pass 10" framework.
- **`= dict()` as default** — variant form using the constructor instead of a literal; same trap. Captured as adjacent reference at CarsonBurke/dreamer4#8.

All sub-shapes share the same root mechanism: a mutable object is used as a parameter default, creating a single shared instance across all calls that don't override it.

## Mechanism

A language model generates each function signature in a local context. The training corpus contains both shapes:

- **Defective**: `def f(items=[]):` — the typical "I want a list parameter with default empty" naive form.
- **Correct**: `def f(items=None): if items is None: items = []` — the *None-sentinel + body-init* idiom; or in Pydantic, `Field(default_factory=list)`.

The defective shape is over-represented per-token in two distinct corpus segments:

**Tutorial code and Stack Overflow snippets**. Beginner Python guides routinely show `def f(x=[])` as the obvious way to give a parameter a default list. The defect is so well-known that Python style guides, books, and lint rules (ruff `B006` "mutable-argument-default", Pylint `dangerous-default-value`) all warn against it. The model has seen both the trap *and* the warnings in training data. What it has not internalized is the *judgment* about which to use at generation time.

**Stack Overflow Q&A pairs about the trap itself**. Many questions of the form *"why does my function remember values across calls?"* have answers showing the defective form (the asker's code) and explaining the fix. The asker's defective code, the Q&A title, and the answer's explanation all contain `def f(items=[]):` as text. From a token-prediction perspective, the defective form is heavily attested in the corpus *because* it is a well-known antipattern. Antipattern explanations contain the antipattern by necessity.

The model's token-prediction step produces the surface form that fits the prompt context: `def f(items=` is followed most commonly by `[]):` or `{}` in the corpus, and the model produces that completion. The structural decision to use `None` and initialize inside the body requires generating *more* tokens (the body's `if items is None:` line) and is structurally a larger choice than producing the defective shape. The local-attention generation step is biased toward the simpler-and-more-corpus-frequent completion.

A particularly diagnostic observation comes from the Quibo specimen: four sibling Pydantic state classes use `Field(default_factory=list)` correctly; the fifth class (`ContentParsingState`) uses bare `List[str] = []`. The model knew the right pattern at four sites and produced the wrong pattern at the fifth — *the same model in the same project*. This is the **same-project-knows-right-pattern** mechanism applied to the Pydantic-field-default layer.

The mechanism also explains the **clustering** observed in LlamaFactory: four static methods in one class all use the same wrong template (`Optional[dict[str, Any]] = {}`). When the model generated the first signature, the local attention context primed the same defective template for the next three. The sticky-local-pattern observation from [`unjustified-lazy-import`](unjustified-lazy-import.md), [`unreachable-defensive-guard`](unreachable-defensive-guard.md), and [`swallowed-exceptions`](swallowed-exceptions.md) applies at the function-signature layer.

There is also a form-specific signature in the LlamaFactory specimen: the parameter is annotated as `Optional[dict[str, Any]] = {}`. The annotation declares `Optional` (suggesting `None` was considered as a valid value) but the default is `{}` (not `None`). The model produced an *internally inconsistent* signature — the type hint and the default disagree about what the parameter's "empty" state should be. This kind of internal-inconsistency is structurally the same as the [`inconsistent-error-handling`](inconsistent-error-handling.md) entry's sibling-divergence mechanism, but applied within a single function signature.

This pattern is **AI-amplified, not AI-exclusive**. Human Python programmers write mutable defaults too — particularly beginners, particularly in tutorial-shaped code. The AI-amplified observation rests on three differential dimensions:

1. **Initial-state authorship**: AI-generated codebases produce the pattern *from the first commit*, not as accumulated legacy. The captured specimens are all from young AI-coded projects, not decade-old codebases drifting over time.
2. **Clustering**: 4 same-template defaults across sibling methods (LlamaFactory) or 14 across 9 files (NASA OnAIR; adjacent reference) at densities that human-paced development rarely produces.
3. **Internal annotation inconsistency**: `Optional[dict] = {}` (LlamaFactory) is a signature that asserts two incompatible things about the parameter's empty state. The annotation/default mismatch is form-evidence the model produced the signature without verifying internal consistency.

## Evidence / incident

Three captured specimens, each from a different AI-coded Python codebase. Detailed specimen notes are not included in the public repository.

- **[hiyouga/LlamaFactory#10476](https://github.com/hiyouga/LlamaFactory/issues/10476)** — clustered same-template defaults. Four `HuggingfaceEngine` static methods all use `input_kwargs: Optional[dict[str, Any]] = {}`. `_get_scores` calls `input_kwargs.pop("max_length", None)` — concrete drain path. Project CLAUDE.md (3930 bytes) confirms AI-assisted development. Fix PR [#10477](https://github.com/hiyouga/LlamaFactory/pull/10477) applies the `None`-default-with-body-init fix at all four sites uniformly. A separate earlier PR [#10297](https://github.com/hiyouga/LlamaFactory/pull/10297) ("fix: mutable default arg and bool comparison") shows the pattern recurring across multiple fixes.
- **[JNK234/Quibo#25](https://github.com/JNK234/Quibo/issues/25)** — Pydantic-field-default drift; same-project-knows-right-pattern. `ContentParsingState.errors: List[str] = []` while sibling state classes (`OutlineState`, `BlogDraftState`, `BlogRefinementState`, `CostTrackingState`) correctly use `Field(default_factory=list)`. Project CLAUDE.md (6595 bytes) is unusually expressive ("address me as 'Master Blogger'"); AI-blogging-assistant project domain. 15+ uses of `Field(default_factory=...)` across the codebase as ground-truth.
- **[siege-analytics/siege_utilities#493](https://github.com/siege-analytics/siege_utilities/issues/493)** — single literal default `column_names=['metric', 'value']` in `spark_utils.prepare_summary_dataframe`. Surfaced by "**Hostile-review pass 10**" — a maintainer-run multi-pass adversarial review framework. Project CLAUDE.md (603 bytes) is an AI-attribution policy, evidence the project works with AI assistants. Calibrated severity assessment: "leave a comment but don't block."

Three different scales (4-instances clustering / 1-instance with sibling-comparison / 1-instance latent), three different project domains (AI/ML training framework / AI blogging assistant / data-engineering utilities), three different audit framings (project bug report / project self-audit with Pydantic-aware fix / Hostile-review pass-10 calibrated review). All three projects have CLAUDE.md.

Supplementary references:

- **[CarsonBurke/dreamer4#8](https://github.com/CarsonBurke/dreamer4/issues/8)** — `PixelGymnasiumEnv.__init__` uses `env_kwargs: dict = dict()`. Adjacent shape (the constructor `dict()` produces a fresh-but-still-shared default).
- **[nasa/OnAIR#197](https://github.com/nasa/OnAIR/issues/197)** — 14 function signatures across 9 files in `onair/src/reasoning/` use mutable defaults; the audit explicitly flags concern in "AI reasoning interfaces where `_reasoning_plugins={}`, `_learner_plugins={}` are shared." Adjacent reference; AI-authorship of the underlying code is uncertain (the project predates modern LLMs and the AI in "AI reasoning interface" refers to the system's domain, not the authoring AI).
- **[pgmpy/pgmpy#2754](https://github.com/pgmpy/pgmpy/issues/2754)** — 15+ instances across a Python probabilistic-graphical-models library. Project has AGENTS.md (added 2026-02-17) but the codebase is 10+ years old; the mutable defaults likely predate AI-coding-assistant adoption. Captured as adjacent reference because the audit author used standard code-quality vocabulary (not an AI-tells frame), but the inclusion-rule differential (AI-authored vs legacy human-authored) cannot be cleanly established without per-file git-blame work.

Ruff has rule **B006** (`mutable-argument-default`) and Pylint has **W0102** (`dangerous-default-value`). Both are widely-adopted community lint rules, evidence the pattern is recognized as a defect class independent of AI authorship. The AI-amplified observation is that AI-generated codebases trigger these rules at unusual density and in unusual contexts (Pydantic model bare-defaults; clustered sibling-method signatures).

## Detection cues

What to look for in a diff or completion:

- **Function signature with `=[]`, `={}`, `=set()`, `=dict()`, `=list()`, or any object-constructor as a default value.** The most direct signal. The constructor variant (`=dict()`) is subtly worse because it looks like it should produce a fresh dict — but the constructor is also evaluated once at function-definition time.
- **A function signature with `Optional[<container>] = <empty_container>` (mismatch between type and default).** The annotation says the parameter is optional (admitting `None`) but the default is an empty container, not `None`. The model produced an internally-inconsistent signature; check whether the body assumes the parameter is `None` or assumes it is the empty container.
- **Pydantic model field with `<container_type> = <empty_container>`** (e.g., `List[str] = []`, `Dict[str, Any] = {}`). The Pydantic-correct form is `Field(default_factory=<callable>)`. In Pydantic v2 the bare-default form can produce shared state across instances depending on field configuration.
- **Clusters of same-template defaults across sibling methods.** Multiple `static` or `def` methods in one class all using the same parameter signature with a mutable default. The sticky-local-pattern signature.
- **Sibling state classes where most use `Field(default_factory=...)` but one uses bare `[]` / `{}`.** Same-project-knows-right-pattern; the drifting class is the suspect.
- **Function bodies that call `.pop()`, `.append()`, `.extend()`, `.update()`, or `.clear()` on a parameter that has a mutable default.** Direct drain path; the defect is *active*, not just latent.

The diagnostic question for any candidate: *if I call this function twice without passing the parameter, do I get the same object both times?* If yes, mutations leak. If the default is a literal `[]`, `{}`, `set()`, or `dict()`, the answer is yes.

The ruff B006 lint rule mechanically catches all the function-signature variants. Pydantic models require Pydantic-specific tools (`from_attributes`, `model_validator`, or `Field(default_factory=...)` enforcement via `extra='forbid'` schemas).

## Notes

**Category `language-pitfall`.** The category captures Python-specific footguns the AI inherits from tutorial corpus despite warnings being present in the same corpus.

**Difficulty rated `low`.** The visual cue is unambiguous — `[]` or `{}` after `=` in a parameter list is immediately recognizable. The diagnostic step (does the function mutate the default?) is mechanical. Once the reader knows the pattern, detection is essentially zero-effort. The reason this is in the taxonomy is *density and form*, not difficulty.

**The pattern is AI-amplified, not AI-exclusive.** Restated for emphasis: every Python beginner writes this defect at least once. The AI-amplified differential rests on initial-state authorship, clustering, and form (internal annotation/default inconsistency).

**False-positive shapes.** Be cautious before flagging:

- *Immutable defaults that happen to be containers.* `def f(items=()):` (empty tuple) — tuples are immutable; no shared-state risk. The default is a singleton across calls but cannot be mutated. Same for `frozenset()`.
- *Sentinels deliberately used as defaults.* `def f(x=DEFAULT):` where `DEFAULT = object()` is a sentinel intentionally used to detect "no argument passed." Legitimate; the body checks `if x is DEFAULT: ...` before using x.
- *Function-as-default patterns.* `def f(items=list):` (no parentheses!) — passes the `list` *constructor* itself as the default. Body would have to call `items()`. Rare but legitimate; check whether the body invokes `items` as a callable or treats it as a value.
- *Singletons by design.* Some libraries deliberately share state across calls (e.g., a registry, a singleton counter). The cue is whether the design explicitly documents shared state.

**Mutation operator hint.** A deterministic mutation that takes a clean function signature with `None`-default and converts to bare-mutable produces this pattern from clean code. Variants:

- Take `def f(items: Optional[list] = None): if items is None: items = []; ...` and replace with `def f(items: list = []): ...` (remove the None-init pattern)
- Take `Field(default_factory=list)` in a Pydantic model and replace with `[]`
- Take `Field(default_factory=dict)` and replace with `{}`
- Take a literal default in a function signature and remove it from a `dataclass`-style class default (similar trap with `field(default_factory=...)`)

These compose with [`near-identical-siblings`](near-identical-siblings.md) — a class with N sibling methods *each* having `Optional[dict] = {}` is the maximally AI-tell shape; the duplication is obvious *and* the defective default is reproduced N times. The LlamaFactory specimen is exactly this shape.

**Connection to [`same-project-knows-right-pattern`](../notes/same-project-knows-right-pattern.md) note.** The Quibo specimen is a clean instance of this cross-cutting observation at the Pydantic-field-default layer — four sibling state classes use the correct `Field(default_factory=list)`; one drifts to `List[str] = []`. The model's prior at the drifting class's generation step was independent of its prior at the four correct sites. This entry is one of ten in the cross-cutting note (joining [`swapped-args`](swapped-args.md), [`wrong-tool-for-job`](wrong-tool-for-job.md), [`sleep-based-synchronization`](sleep-based-synchronization.md), [`convention-drift`](convention-drift.md), [`print-instead-of-logging`](print-instead-of-logging.md), [`hardcoded-config-values`](hardcoded-config-values.md), [`missing-network-timeout`](missing-network-timeout.md), [`f-string-in-logger-call`](f-string-in-logger-call.md), [`async-await-mismatch`](async-await-mismatch.md)).

**Connection to [`codified-guidance-is-insufficient`](../notes/codified-guidance-is-insufficient.md) note.** Ruff B006 and Pylint W0102 are widely-adopted community lint rules against this pattern. The LlamaFactory project has CLAUDE.md mentioning ruff in its CI commands and *still produces the pattern* in inference-engine code. The Quibo project has CLAUDE.md and a 4-of-5 use of `Field(default_factory=list)` as its convention and *still produces the bare default* in one state class. The siege-analytics project's "Hostile-review pass 10" is a custom audit framework that surfaces the pattern despite lint rules being available. This is a 16+ entry observation now.

**Internal-inconsistency signature.** The LlamaFactory `Optional[dict[str, Any]] = {}` form is internally inconsistent — the type annotation declares `Optional` (admits `None`) but the default is `{}` (not `None`). This is a form-specific signature of AI-amplification: the model generated the type annotation anticipating `None` as a valid value, then defaulted to the wrong representation of the same idea. The same internal inconsistency can serve as a detection cue more broadly.
