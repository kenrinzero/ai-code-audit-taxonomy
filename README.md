# AI Code Audit Taxonomy

A curated taxonomy of **24 code defect patterns that AI assistants produce with distinctive frequency, form, or mechanism** in Python. Each entry documents the defective shape, explains *why* language models produce it, links to real-world incidents, and provides mechanical detection cues.

The patterns are AI-amplified, not AI-exclusive. Most are ordinary defects — swallowed exceptions, off-by-one errors, missing timeouts — that human programmers also write. What makes them worth cataloging separately is that AI-generated code produces them at characteristic densities, in characteristic forms, and through mechanisms tied to how language models generate code. The honest claim is *AI-shaped*, not *AI-only*.

## Why this exists

AI coding assistants produce correct code most of the time. The difficult part is staying alert across hundreds of correct outputs and catching the broken one. Knowing what to look for helps.

This taxonomy is a reference for anyone who reads AI-generated code: reviewers, auditors, developers using AI assistants, or teams building review workflows. It is organized around two questions:

1. **What does the defect look like?** Detection cues you can grep for or spot on visual scan.
2. **Why does the model produce it?** Mechanism explanations that connect the defect to how language models work — not just *what* to look for, but *why* it keeps appearing.

Each entry also documents **false-positive shapes** — what looks like the pattern but isn't — so you can triage confidently rather than over-flag.

## How language models generate code — a brief primer

The Mechanism sections use a small vocabulary from how language models work. Three ideas cover most of it.

**Token-level prediction.** A language model writes code one small piece at a time — roughly word-sized chunks called *tokens* — picking the most likely next token given what it has just produced. It commits as it goes; it does not draft a whole function and then refine.

**The training corpus.** The body of text the model learned from: Stack Overflow answers, tutorials, GitHub repositories, documentation, blog posts. Shapes the corpus contains most often *per token* are the shapes the model produces most fluently. Under-represented shapes are under-produced even when they are the right answer for the situation.

**Local attention.** The model decides each next token mostly from the surrounding code — recent lines, the current function signature, nearby imports — not by re-reading the whole file or project. Conventions documented elsewhere (style guides, lint rules, project docs) sit *outside* this local window unless they are explicitly pulled in.

Most defects in the taxonomy come from these three forces together: the corpus-fluent shape wins the per-token decision, and consistency that would require looking outside the local window is not enforced at generation time. No further ML background is needed.

## The 24 entries

### By surface (category)

| Category | Entries |
|----------|---------|
| **error-handling** | [swallowed-exceptions](taxonomy/patterns/swallowed-exceptions.md), [inconsistent-error-handling](taxonomy/patterns/inconsistent-error-handling.md), [brittle-error-detection](taxonomy/patterns/brittle-error-detection.md) |
| **structure** | [near-identical-siblings](taxonomy/patterns/near-identical-siblings.md), [unjustified-lazy-import](taxonomy/patterns/unjustified-lazy-import.md) |
| **control-flow** | [off-by-one](taxonomy/patterns/off-by-one.md), [swapped-args](taxonomy/patterns/swapped-args.md) |
| **security** | [string-built-sql](taxonomy/patterns/string-built-sql.md), [shell-true-subprocess-injection](taxonomy/patterns/shell-true-subprocess-injection.md), [tarfile-extractall-without-filter](taxonomy/patterns/tarfile-extractall-without-filter.md) |
| **observability** | [print-instead-of-logging](taxonomy/patterns/print-instead-of-logging.md), [f-string-in-logger-call](taxonomy/patterns/f-string-in-logger-call.md) |
| **reliability** | [missing-network-timeout](taxonomy/patterns/missing-network-timeout.md), [resource-leak-no-context-manager](taxonomy/patterns/resource-leak-no-context-manager.md) |
| **async** | [async-await-mismatch](taxonomy/patterns/async-await-mismatch.md), [sleep-based-synchronization](taxonomy/patterns/sleep-based-synchronization.md) |
| **language-pitfall** | [mutable-default-arguments](taxonomy/patterns/mutable-default-arguments.md), [assert-for-runtime-validation](taxonomy/patterns/assert-for-runtime-validation.md) |
| **configuration** | [hardcoded-config-values](taxonomy/patterns/hardcoded-config-values.md) |
| **consistency** | [convention-drift](taxonomy/patterns/convention-drift.md) |
| **documentation** | [narrating-comments](taxonomy/patterns/narrating-comments.md) |
| **testing** | [weak-test-assertion](taxonomy/patterns/weak-test-assertion.md) |
| **defensive-programming** | [unreachable-defensive-guard](taxonomy/patterns/unreachable-defensive-guard.md) |
| **library-usage** | [wrong-tool-for-job](taxonomy/patterns/wrong-tool-for-job.md) |

### By mechanism (cross-cutting notes)

Each entry has a category (the *surface* where the defect appears) and may participate in one or more cross-cutting notes (the *mechanism* connecting it to other entries). The two axes are independent.

| Note | What it observes | Entries |
|------|------------------|---------|
| [ai-pedagogical-bias](taxonomy/notes/ai-pedagogical-bias.md) | Model treats production code as tutorial code | 6 entries |
| [same-project-knows-right-pattern](taxonomy/notes/same-project-knows-right-pattern.md) | Same codebase uses the right pattern at one site, wrong at another | 10 entries |
| [codified-guidance-is-insufficient](taxonomy/notes/codified-guidance-is-insufficient.md) | Documented conventions don't prevent the violations; enforcement is the cure | 16+ entries |
| [surface-failure-modes-explicitly](taxonomy/notes/surface-failure-modes-explicitly.md) | Typed-exception meta-family: surface failure modes through the type system | 4 entries |
| [defensive-choice-with-justifying-comment](taxonomy/notes/defensive-choice-with-justifying-comment.md) | Defensive choices paired with comments justifying constraints that don't survive verification | 9+ entries |
| [partial-fix-propagation](taxonomy/notes/partial-fix-propagation.md) | A prior fix addressed some sites; sibling sites retain the wrong pattern | 3 entries |

## Entry format

Each taxonomy entry follows the same structure:

- **Code example** — minimal defective code; the bug should be visible to someone who knows Python.
- **Mechanism** — why a language model produces this shape. Connects to the primer above.
- **Evidence / incident** — real-world GitHub issues, PRs, or CVEs where the pattern was found in AI-generated code. Every entry requires concrete evidence of an AI-vs-human frequency or form differential.
- **Detection cues** — what to grep for or spot on visual scan. Mechanical enough to use as a checklist.
- **Notes** — false-positive shapes, connections to cross-cutting notes, difficulty rating.

## What this is (and isn't)

This is a reference taxonomy — a structured catalog of patterns with evidence and mechanism. It is **not**:

- An exhaustive list. 24 entries is a starting point, not a ceiling.
- A claim that AI is bad at coding. The stance is neutral and practical: assistants are useful tools with characteristic distributional properties.
- A frozen document. The patterns AI produces will shift as models change; the taxonomy is meant to be updated alongside them.

## Inclusion rule

A pattern enters the taxonomy only if there is concrete evidence of a frequency or form differential between AI-generated and human-written code — not just a plausible mechanism story. Each entry carries an evidence grade: `reproduced` (independently verified), `observed` (captured from real projects), `reported` (documented by others), or `analogical` (structurally predicted from a confirmed mechanism).

## Evidence methodology

The taxonomy's evidence base draws from three streams:

1. **GitHub issues and PRs** from AI-coded open-source projects — identified by CLAUDE.md/AGENTS.md presence, AI-attributed commit trailers, or bot-authored audit frameworks. 72 specimens across 24 entries capture the pattern at multiple scales and in multiple audit frameworks.
2. **Community lint rules** (ruff, bandit, pylint, SonarCloud) that independently flag the same patterns — evidence that the broader Python community recognizes these as defect classes regardless of authorship.
3. **Academic cross-validation** — Zhu, Tsantalis & Rigby (2026), "AI-Generated Smells" (arXiv:2605.02741), provides statistical evidence on structural code smells in AI-generated Python code, cross-validating the `near-identical-siblings` entry and the broader claim that AI-generated code has measurable distributional properties.

Evidence specimens referenced in entries link to the original GitHub issues. Local specimen files (detailed research notes) are not included in this repository.

## Sources and background

- **Zhu, Tsantalis & Rigby (2026):** [AI-Generated Smells: An Analysis of Code and Architecture in LLM- and Agent-Driven Development](https://arxiv.org/abs/2605.02741). Concordia University. Complementary scope: production-code structural smells via static analysis.
- **Community lint ecosystems:** ruff, bandit, pylint, SonarCloud — the rules these tools enforce against many of the same patterns are cited throughout the entries.

## License

MIT — see [LICENSE](LICENSE).

