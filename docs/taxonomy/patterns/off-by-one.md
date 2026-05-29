---
name: off-by-one
category: control-flow
difficulty: medium
generation: evergreen
since_model: null
evidence_grade: observed
---

# Off-By-One

## Code example

```python
def measured_fps(frames: list[Frame], duration_s: float) -> float:
    """Return frames per second observed over the capture interval."""
    return len(frames) / duration_s
```

With N frames, there are N-1 *intervals* spanning the duration. The function returns N/duration_s; the correct value is (N-1)/duration_s. For 60 frames over 1.0 second, this returns 60.0 fps when the true rate is approximately 59.0 fps. The error grows more significant at low frame counts.

The form is obviously correct if you read it as "frames per second: count the frames, divide by seconds." The form is wrong because what FPS actually measures is *the rate of frame-events*, which is intervals/second, not events/second. The off-by-one is at the level of *what is being counted*, not at the level of arithmetic. It is a fence-post error: between N posts there are N-1 spans.

A tightened version, with a precondition guard:

```python
def measured_fps(frames: list[Frame], duration_s: float) -> float:
    """Return frames per second observed over the capture interval.

    Precondition: len(frames) >= 2. With fewer than 2 frames there are
    no intervals to measure.
    """
    if len(frames) < 2:
        return 0.0
    return (len(frames) - 1) / duration_s
```

The pattern has several distinct sub-shapes in captured specimens:

- **N-events-vs-N-1-intervals fence-post** — the canonical form, where a measurement function counts events and divides by the span instead of counting the spans. Captured in aetherflow#38.
- **Display-width-vs-code-point off-by-one** — `len(s)` returns code points but a terminal renders CJK and emoji characters in 2 columns each, and emoji variation sequences are zero-width. A panel-rendering function that uses `len()` for box width works for ASCII but breaks at the boundaries the moment any extended character appears. Captured in hermes-agent#20621.
- **Index-offset off-by-one in a generator function** — a single off-by-one in a function that emits a sequence (stage-to-team mappings, page indices, cycle assignments) compounds across the entire generated output. Captured in Backyard-Capitalism-9000#6, where one off-by-one in cadenza generation produced 903 wrong-team assignments across the build.
- **`pathlib.Path.parents[N]` miscounting** — confusion about whether `parents[0]` is the immediate parent (yes) or the file itself (no), or whether counting includes `src/` and `package/` segments. Documented as an adjacent specimen reference (ClimateVision#54) where `parents[4]` should have been `parents[3]`.

All four sub-shapes share the same root mechanism: the model produced a form that is locally plausible at the token level but does not match what the function is conceptually counting.

## Mechanism

Off-by-one is universal in human-written code. The honest framing for this taxonomy entry is that the pattern is *AI-amplified at certain forms*, not *AI-exclusive*. Humans hit fence-post errors constantly; the AI-amplification claim is narrower than for the typed-exception family.

The amplification has three distinct paths in AI-generated code:

**Path 1: Token-level fluency of `len()` and `range()`.** The training corpus contains thousands of correct usages of `len(items)`, `range(n)`, `arr[0:n]`. The model produces these forms with high token-level fluency. The question of whether the right form is `len(arr)` or `len(arr) - 1`, `range(n)` or `range(n+1)`, `arr[0:n]` or `arr[0:n-1]`, is a question of arithmetic semantics that is *not* solved by token-level prediction. The model produces the canonically-shaped form; whether the form is off by one for the current context is a local-reasoning problem that follows generation, not a token-prediction problem solved during generation.

**Path 2: English-centric default assumptions.** When the model generates code that operates on strings, the implicit assumption is the English ASCII case where `len(s)` happens to equal display-column-count. The hermes-agent#20621 specimen documents this beautifully: five cascading width calculations in panel-rendering code all use `len()`. The model has internalized "len returns the length of a string" without distinguishing the three quantities that are usually equal for English text (code point count, byte count, display column count) but diverge at CJK, emoji, and variation selectors. A model trained on a more multilingually-balanced corpus would still produce `len()` in many contexts because the training data does. The AI-amplification is that the buggy assumption fires *consistently across all related code paths* — the model produces the same `len()` shape in five different functions because the shape is locally fluent, not because the model concluded it was correct for each context.

**Path 3: Compounding through generator functions.** A single off-by-one in a function that emits a sequence is one bug, but when that function runs hundreds of times in an automated pipeline, the bug instantiates hundreds of times. The Backyard-Capitalism-9000#6 specimen captures this at 903 misassignments from one off-by-one in cadenza generation. In a human-paced codebase, a developer would notice the first wrong team-label assignment on the first manual check and fix the generator. In an AI-paced build pipeline that compiles the output once and uses it, the bug compounds before any human review sees a sample. The amplification is not that AI generates more off-by-ones; it is that AI-driven build pipelines amplify the consequences of any one off-by-one that does occur.

The training corpus also contains both correct and incorrect off-by-one usages. Stack Overflow answers, tutorial code, and example snippets contain plenty of `range(0, len(arr))` (correct) and plenty of `range(0, len(arr) - 1)` (correct or incorrect depending on intent) and plenty of `range(1, len(arr))` (likely a bug but sometimes intended). The model has seen all forms. It cannot, from token-prediction alone, decide which is right for the current function — that decision requires reasoning about what the function is conceptually counting (frames vs intervals, items vs spans, indices vs positions). The model's prior often defaults to the "obvious count" form (`len(arr)`) when the intent is the "spans between counts" form (`len(arr) - 1`).

This pattern is one of the taxonomy's **three named evergreens** alongside [`swapped-args`](swapped-args.md) and [`swallowed-exceptions`](swallowed-exceptions.md) — pattern classes so well-established that they anchor the taxonomy as familiar starting points for readers.

The pattern is **AI-amplified, not AI-exclusive**. The inclusion-rule case here is genuinely weaker than for the typed-exception family or the structure patterns, because the underlying defect class is universal. The differential evidence is in *form* (CJK/emoji width assumption is more AI-typical than human-typical), *clustering* (five cascading width calculations all sharing one assumption), and *compounding* (903 misassignments from one bug in a generator function). Off-by-one in isolation is not strong evidence of AI-authorship; off-by-one with these specific shapes is.

## Evidence / incident

Three captured specimens, each from an AI-coded Python codebase, each demonstrating a different sub-shape. Detailed specimen notes are not included in the public repository.

- **[NousResearch/hermes-agent#20621](https://github.com/NousResearch/hermes-agent/issues/20621)** — display-width-vs-code-point off-by-one. Five cascading width calculations in panel-rendering code all use `len()` (code-point count) instead of terminal display width. CJK content overflows the box because `len("⚠️ 危险命令")` returns 7 but terminals render it as ~12 columns. An additional nested off-by-one exists for emoji variation sequences (VS16 is zero-width but `wcwidth` returns 2). Confirmed Claude Sonnet 4.6 co-authorship in repo.
- **[Mzzkc/Backyard-Capitalism-9000#6](https://github.com/Mzzkc/Backyard-Capitalism-9000/issues/6)** — index-offset compounded through a generator function. One off-by-one in cadenza generation produced **903 wrong-team assignments** across the 37-cycle, 4-team score build. Every team's stages received the previous team's context files. Bug discovered by "Mozart score-reviewer agent" (another AI agent in the project's review workflow). Same owner (Mzzkc) as the marianne-ai-compose project that produced the [`swallowed-exceptions`](swallowed-exceptions.md) specimen.
- **[jparson2389/aetherflow#38](https://github.com/jparson2389/aetherflow/issues/38)** — N-events-vs-N-1-intervals fence-post in measurement. `_measured_fps()` returns `len(frames) / duration_s`, overstating FPS by a factor of N/(N-1). Caught in PR review by AI reviewers (`@chatgpt-codex-connector` and `@Copilot`) — a notable counter-observation that AI reviewers *can* detect AI-generated off-by-one when the math is explicit enough to verify symbolically.

Supplementary references:

- `Climate-Vision/ClimateVision#54` — `_PROJECT_ROOT = Path(__file__).resolve().parents[4]` should have been `parents[3]`, producing an output directory outside the repo. The `pathlib.Path.parents[N]` indexing convention is subtle and is a frequent off-by-one site for any author, AI or human. The repo's AI-authorship is not clearly established, so this is referenced as an adjacent shape rather than a primary specimen.
- `home-assistant/core` had a batch of off-by-one issues filed alongside the swallowed-exceptions batch in mid-May 2026 with similar automated-audit shape; the underlying code is community-authored so the AI-authorship of the *code* (rather than the audit) is uncertain.

Three primary specimens span three sub-shapes (display width, index offset in generator, fence-post in measurement), three projects, three AI-authorship signals (explicit Claude co-authorship, same-owner-as-AI-development-practice, AI-reviewers-in-the-loop). Cross-context coverage is reasonable for the pattern, with the honest caveat that off-by-one is the most universal defect class in the taxonomy and the AI-amplification claim rests on *form and compounding* rather than on raw frequency.

## Detection cues

What to look for in a diff or completion:

- **`len(collection)` where the function is computing a rate, average-over-spans, or rate-of-change.** The rate quantity often needs *intervals* between samples, not count of samples. The canonical question: "Is the unit of this quantity events-per-second or intervals-per-second?" If intervals, you need `len() - 1` somewhere.
- **`len(string)` used for display width.** Particularly suspect in any code that builds borders, columns, panels, padding, or text wrapping. The defect surfaces only on CJK, emoji, combining characters, RTL text, or variation selectors. ASCII works; the moment the user types Chinese into the system prompt or adds an emoji to a label, the layout breaks. The fix is `wcwidth` (with the caveat that `wcwidth` itself has nested off-by-ones for emoji variation sequences).
- **`range(0, len(arr) - 1)` or `range(1, len(arr))`.** The standard iteration is `range(len(arr))` or `enumerate(arr)`. When you see one of the offset forms, ask why the first or last element is being skipped — sometimes correct (sliding windows, comparisons of adjacent items) but often a sign that the model produced one of the wrong-by-one forms.
- **`arr[0:n-1]` or `arr[1:n]`.** Same question as above: Python's slice convention is half-open, so `arr[0:n]` is the full first-n elements. Offset forms are sometimes correct (excluding boundaries) but often defective.
- **`pathlib.Path.parents[N]` with N > 1.** The indexing convention is: `parents[0]` is the immediate parent directory, `parents[1]` is the grandparent, and so on. Counting how many `parents[...]` calls you need to reach the repo root is a place where a single miscount becomes a path-outside-the-repo. Walk the parents explicitly and check.
- **A generator function that emits a sequence of (label, value) pairs.** Cycle-stage-team mappings, pagination cursors, batch-index-to-item mappings. A single off-by-one here compounds across every invocation. The diagnostic move is to print the first three outputs and check the labels against expectations manually.
- **A function that "happens to work" for the current test values.** Trim algebra that works for the current `frames_per_inference` constants but whose boundaries do not line up with the intent is a representative instance. If a small change to the constants would expose a defect, the code has an off-by-one waiting to fire.

The diagnostic question for any candidate: *what is this code conceptually counting, and does the arithmetic match the conceptual unit?* If the code says "frames per second" but counts frames not intervals, the form does not match. If the code says "panel width in columns" but counts code points not display columns, the form does not match.

## Notes

**Category `control-flow`.** Off-by-one is conventionally a control-flow defect (loop bounds, indexing), but the captured specimens span loops, indexing, slicing, arithmetic, and assumption-encoding. The category fits the loop/iteration sub-shape best; the other sub-shapes share the root mechanism but are not strictly control-flow.

**Difficulty rated `medium`.** The surface form is often universal (`len()`, `range()`, `arr[i:j]` — all look correct in isolation). The defect is only visible when the reader maps the arithmetic to the conceptual unit being counted. A reader who only checks "does this look like Python code" will not flag it. Once the reader knows to ask "what is this counting and what is the right unit?", detection is mechanical. Higher than `low` because the diagnostic step requires understanding what the function is *for*, not just what it *does*.

**The inclusion-rule case is honestly weaker than for prior entries.** Off-by-one is universal — humans hit it constantly. The pattern is in the taxonomy because:

1. It is one of the taxonomy's **three named evergreens** (alongside swapped-args and swallowed-exceptions).
2. The captured specimens demonstrate **AI-typical FORMS** (CJK/emoji width-vs-len assumption, compounding through generators, fence-post in derived measurements) that are more characteristic of AI-generated code than of human-generated code.
3. The captured specimens demonstrate **AI-typical scale/compounding** (903 misassignments from one bug; five cascading width calculations in one function family).
4. The pattern fits the taxonomy's calibration-training goal even at universal-defect-frequencies, because the AI-typical forms are what a reader of AI-generated code should be calibrated to spot.

The honest framing: off-by-one as a pattern class is in the taxonomy as a named evergreen; the AI-amplification dimensions are *form and compounding*, not raw frequency. Some other entries have stronger AI-vs-human frequency differentials. This entry trades some of that strength for completeness — off-by-one is too canonical to omit from a defect taxonomy aimed at AI-generated code.

**The pattern is AI-amplified, not AI-exclusive.** Restated for emphasis: every human Python programmer has shipped off-by-one bugs. The AI-amplification dimensions are the three paths in the Mechanism section: token-level fluency of canonical forms, English-centric default assumptions, and compounding through generator functions in AI-paced pipelines.

**False-positive shapes.** Be cautious before flagging:

- *Slices and ranges that are correct for the function's intent.* `arr[1:]` to skip the first element, `range(1, n+1)` to produce 1-indexed values for user display, `arr[:-1]` to drop the last element. All legitimate; the cue is whether the function's docstring or context makes the intent clear.
- *N-vs-N-1 patterns that are correct for the measurement.* Computing a population variance uses N in the denominator; sample variance uses N-1. Both are correct for their respective statistical contexts.
- *Half-open intervals where the off-by-one is part of the convention.* Python slices, C++ iterator ranges, mathematical interval notation — half-open intervals deliberately have a "boundary that is not included." The cue is whether the function uses the half-open convention consistently.
- *Sliding-window operations where adjacent pairs are intended.* `for i in range(len(arr) - 1): pair = (arr[i], arr[i+1])` correctly produces adjacent pairs. The `- 1` is intended, not a bug.

**Mutation operator hint.** A deterministic mutation that takes a correct boundary-aware function and shifts one of its boundaries by ±1 produces this pattern from clean code. Variants:

- Take `range(0, len(arr))` and replace with `range(0, len(arr) - 1)` or `range(1, len(arr))`
- Take `arr[0:n]` and replace with `arr[0:n-1]` or `arr[1:n]`
- Take `(len(items) - 1) / duration` and replace with `len(items) / duration`
- Take `parents[3]` and replace with `parents[2]` or `parents[4]`
- Take a width calculation using `_display_width(text)` and replace with `len(text)`

These compose with other patterns: an off-by-one in a generator that also has [`swallowed-exceptions`](swallowed-exceptions.md) on the validation step produces a particularly invisible compounded defect — the off-by-one generates wrong data, the swallowed-exception hides the validation failure, the user sees plausible-looking but wrong output.

**Connection to [`swapped-args`](swapped-args.md).** The other token-fluent evergreen shares with off-by-one the property of producing code that is *locally plausible at the token level* but defective at the level of *what the function is doing*. Both are token-prediction-fluent failures. Together with [`swallowed-exceptions`](swallowed-exceptions.md), the three evergreens form a "token-fluent but semantically defective" cluster within the taxonomy.

**Compounding through AI-paced build pipelines** (observation from Backyard-Capitalism-9000#6). Off-by-one bugs that would be caught by manual review on the first sample compound across pipeline runs that don't include human checkpoints. The same dynamic likely applies to other low-frequency defects — they get amplified by automation in ways they don't by hand.
