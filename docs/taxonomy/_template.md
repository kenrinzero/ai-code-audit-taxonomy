---
name: <kebab-case-slug>
category: <a surface where the defect manifests; see existing categories — `structure`, `testing`, `defensive-programming`, `error-handling`, `control-flow`, `documentation`, `library-usage`, `async`, `consistency`, `observability`, `configuration`, `language-pitfall`, `reliability`, `security` — or introduce a new one when no existing category fits>
difficulty: <low | medium | high>
generation: <evergreen | current-model>
since_model: <only for current-model — e.g. "claude-opus-4-6"; null for evergreen>
evidence_grade: <reproduced | observed | reported | analogical>
---

# <Pattern name in Title Case>

## Code example

```<language>
# Minimal example. The bug should be visible to someone who knows the language
# and reads attentively — but not so obvious it can be spotted by skim.
```

## Mechanism

*Why* LLMs produce this. What about transformer training, tokenization, training-corpus
distribution, RLHF objectives, or corpus-prior behavior makes the pattern likely. One to
three short paragraphs.

Written for a reader who knows the language and reads attentively, not a CS researcher.
Gloss technical terms inline when needed.

## Evidence / incident

The strongest evidence in hand, linked. For `reproduced` or `observed` entries, link to
the original source and to any real-world incident (GitHub issue, postmortem URL,
security advisory, CVE, developer blog post). For `reported` entries, link to the report.
For `analogical` entries, link to the non-AI defect class this generalizes from and state
explicitly that no AI-specific specimen has been captured yet.

Show *where*. Not "this has happened in production."

## Detection cues

What to look for in a diff or completion:

- ...
- ...
- ...

## Notes (optional)

Anything else worth knowing — related patterns, common false-positive shapes,
why this is in the catalog at this difficulty level, related mutation operators
from mutmut / Stryker / PIT if applicable.

If this entry participates in any cross-cutting note (`taxonomy/notes/*.md`),
link to it here with a short statement of which observation/mechanism applies:

> **Connection to `<note-name>`.** Brief statement of how this entry fits the note's
> observation, plus the running entry count for that note after this addition.

This makes the dual axis (surface = `category`, mechanism = cross-cutting note)
navigable from any entry.
