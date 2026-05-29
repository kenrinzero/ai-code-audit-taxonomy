---
name: near-identical-siblings
category: structure
difficulty: low
generation: evergreen
since_model: null
evidence_grade: observed
---

# Near-Identical Siblings

## Code example

```python
def parse_bids_tokens(filename: str) -> dict[str, str]:
    parts = filename.split('/')

    sub_token = None
    for part in parts:
        if part.startswith('sub-'):
            sub_token = part[4:]
            break

    ses_token = None
    for part in parts:
        if part.startswith('ses-'):
            ses_token = part[4:]
            break

    sample_token = None
    for part in parts:
        if part.startswith('sample-'):
            sample_token = part[7:]
            break

    return {'sub': sub_token, 'ses': ses_token, 'sample': sample_token}
```

Each block is reasonable in isolation, and a reader who knows Python can step through any one of them without noticing anything wrong. The defect is not in any block — it is in the relationship between the blocks. The same scan-and-extract logic is unrolled three times with one varying string, when the canonical form is a single loop:

```python
def parse_bids_tokens(filename: str) -> dict[str, str]:
    parts = filename.split('/')
    prefixes = ('sub-', 'ses-', 'sample-')
    tokens: dict[str, str] = {}
    for prefix in prefixes:
        for part in parts:
            if part.startswith(prefix):
                tokens[prefix[:-1]] = part[len(prefix):]
                break
    return tokens
```

This pattern is not specific to loops. The same shape appears at the level of classes (multiple subclasses with near-identical method bodies that should live in a base class) and at the level of functions (several near-identical functions whose differences could be parameters). The common signature: a small variation is duplicated structurally instead of being lifted into a parameterized form.

## Mechanism

A language model generates code by **token-level prediction**: it picks one small piece at a time — roughly word-sized chunks called *tokens* — and commits to each before moving to the next. The unit it predicts well is the local pattern: given the start of a block that scans `parts` for `'sub-'`, the next tokens that match that prompt are exactly the body of such a block. The model can produce that block correctly and then, with very high probability, produce the next near-identical block when the next variable's name (`ses_token`) suggests another scan is starting.

What the model is *not* doing during this is recognizing that the three blocks share a structure that could be parameterized. Recognizing the shared structure requires noticing that the three blocks differ only in one varying piece — the prefix string — and stepping out of the unrolled form into a `for` loop over the varying piece. That step is structural; it is not a token continuation. The token continuation gives you the next unrolled block, not the abstract form.

There is a corpus reason behind this too. Training data contains both the unrolled and the abstracted forms, but **unrolled instances are over-represented at the token level**. Each unrolled case is its own piece of text in the corpus; the abstracted form is one compact piece of text that has to be induced as the abstract structure linking the unrolled cases. Token-level prediction can easily produce the unrolled version by following the visible repetition pattern in its own output. The abstraction step requires a structural recognition that token prediction alone does not surface.

The pattern is not exclusive to AI. Human-written code also lacks abstraction sometimes — under deadline, during early exploration, or when the duplication is just easier than the lift. The honest claim of this taxonomy entry is that AI assistants produce this with distinctive frequency and at distinctive scale (the captured specimens range from 3 to 10 near-identical sibling structures). It is AI-amplified, not AI-exclusive.

## Evidence / incident

Three captured specimens, all from real Pull Requests in public open-source projects, with author-confirmed refactors. Detailed specimen notes are not included in the public repository.

- **[dandi/dandi-schema#409](https://github.com/dandi/dandi-schema/pull/409)** — Claude Opus 4.7 authored Python code for BIDS metadata schema. Three sequential blocks for parsing `sub-`, `sample-`, and `ses-` prefixes from filename parts. Reviewer (`yarikoptic`) flagged: *"too aisloppy -- easier to HI compose the logic but first potentially even generalize 2 prior blocks into a 'for' loop"*. Author refactored in commit `cdb37ee` to a single loop over an `entities` list.
- **[dandi/dandi-archive#2794](https://github.com/dandi/dandi-archive/pull/2794)** — OpenAI Codex authored TypeScript code for citation conversion. Six near-identical "no authors" handling blocks across BibTeX/APA/MLA/Chicago citation formatters. Reviewer (`yarikoptic`) flagged: *"uff, my duplication allergies kicking in"*. Author's own follow-up commit message described it as "**six near-identical workarounds**" and refactored to per-format early returns. (Cross-language reference; the primary code example for this entry is from the Python specimens.)
- **[oliverhaas/django-cachex#96](https://github.com/oliverhaas/django-cachex/pull/96)** — maintainer (`oliverhaas`) self-audit of AI-assisted Python package. Five compressor subclasses (`gzip`, `lz4`, `lzma`, `zlib`, `zstd`) and five serializer subclasses (`json`, `msgpack`, `orjson`, `ormsgpack`, `pickle`) each had near-identical `try: <lib>.decompress(data); except: raise CompressorError from e` blocks. The PR consolidated the duplicated wrapping logic into base-class hooks. Maintainer's own framing: *"drops the AI-style mannerisms and inconsistencies flagged in #86"* — the audit issue explicitly used an "AI-smell checklist."

The three specimens vary across all five identification-side axes documented during capture: AI model (Claude / Codex / unspecified-AI-assisted), language (Python / TypeScript / Python), repo (different ecosystems), reviewer (yarikoptic / yarikoptic / oliverhaas-self-audit), and reviewer vocabulary ("aisloppy" / "duplication allergies" / "AI-smell checklist"). Scale of the duplication ranges from 3 sibling blocks to 10 sibling classes.

**Independent identification.** A fourth source — [p-to-q/wittgenstein#288](https://github.com/p-to-q/wittgenstein/issues/288), an architecture-audit issue by user `Jah-yee` on a TypeScript repo — explicitly lists this pattern in its rationale for the audit: *"AI ... may duplicate local patterns instead of extracting the right boundary."* This is unsolicited cross-source confirmation from a separate calibrated reviewer doing independent audit work; no specific code specimen captured from wittgenstein since the audit deliberately operates above the line-by-line level.

**Academic cross-validation.** Zhu, Tsantalis, and Rigby (2026) ["AI-Generated Smells: An Analysis of Code and Architecture in LLM- and Agent-Driven Development"](https://arxiv.org/abs/2605.02741) provides a statistical study of structural code smells in AI-generated Python code, using the PyExamine static-analysis tool across multiple LLMs (Gemini-2.5-pro, Qwen-coder series, Llama-3.3, deepseek-coder-v2). The paper identifies **Potential Improper API Usage (PAU) / Redundant Implementation** as a prevalent AI-introduced defect: *"the agent repeatedly rewrites invocation logic inline, mirroring a 'copy-paste' coding style that inflates code volume."* That description and the paper's accompanying frequency analysis cross-validate the mechanism underlying near-identical-siblings: the model produces unrolled multi-instance code where the abstracted form would be canonical. The paper does not use the same name for the pattern, and its scope is the structural / architectural level rather than the line-level instances captured in our specimens, but the underlying mechanism is the same and the academic statistical evidence strengthens the inclusion claim beyond what GitHub specimens alone provide.

## Detection cues

What to look for in a diff or completion:

- Three or more sequential code blocks at the same indentation level that differ only in one identifier, string literal, or constant. The variation can almost always be lifted into a loop variable, a function parameter, or a class member.
- Multiple class definitions or method definitions with the same overall shape and near-identical method bodies — particularly if the only variation across them is a library call or a class attribute.
- Long parallel `if/elif/elif/elif` chains that test against a fixed list of constants and execute structurally identical bodies in each branch. Often a dictionary lookup or a small table would replace the chain.
- Multiple separate `try/except` blocks at the same indentation level that catch the same exception type and perform similar handling. Often the wrapper logic belongs in a base class or a decorator.
- Code where introducing a `for` loop, a helper function, or a base class would shorten the file substantially without changing behavior — and where the surrounding code provides no reason against doing so.

The cue that distinguishes this pattern from intentional duplication: the sibling structures share the same *bug* or the same *style choice* in each instance, not just the same shape. When duplication is intentional (manual loop unrolling for performance, deliberately divergent behavior masked as similar) the siblings will have meaningful differences beyond the one varying piece; in the AI-amplified version they typically do not.

## Notes

**Category `structure`.**

**The pattern is AI-amplified, not AI-exclusive.** Human-written code also produces unabstracted parallel logic — under time pressure, during early prototyping, or when the duplication is locally easier than the lift. The inclusion claim is that AI-generated code shows this with notable frequency and at notable scale (3 to 10 sibling structures is high for a single function or module). A taxonomy entry is not an accusation; it is a fluency aid.

**False-positive shapes.** Be cautious before flagging:

- *Intentional unrolling for performance.* SIMD code, low-level numeric kernels, and some hot-path scripts manually unroll loops because the abstraction has runtime cost. These specimens will usually be marked with a comment explaining the unrolling.
- *Sibling structures with meaningfully divergent semantics.* Three citation-formatter functions can look near-identical but actually differ in subtle formatting rules; lifting them into a shared template may degrade output quality. The decision to abstract is judgment, not mechanical.
- *Test code.* Parameterized tests are good practice but it is also reasonable for parallel test cases to be written out individually for readability when they are exercising distinct named scenarios.

**Mutation operator hint.** A deterministic mutation that generates this pattern from clean code: take a loop over a small iterable, unroll it into N sequential blocks with one variable substituted in each, and rename any intermediate-state variable per iteration. This produces the AI-amplified form deterministically from a known clean form.
