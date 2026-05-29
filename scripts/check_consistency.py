#!/usr/bin/env python
"""Consistency guard for the published taxonomy docs.

Fails (exit 1) if any regression we previously fixed creeps back in:

  A. Forbidden strings — wrong lint-rule code, placeholder links, orphaned
     references, and internal-only content that should have been stripped
     before publication.
  B. Cross-cutting-note count drift — each note states how many entries
     belong to it; this verifies the note's headline count matches the number
     of entries in its own table, and that every entry footer that cites the
     note agrees.

Run from the repo root:  python scripts/check_consistency.py
"""
import re
import sys
import pathlib

DOCS = pathlib.Path("docs/taxonomy")
errors = []


def add(path, msg):
    errors.append(f"{path}: {msg}")


# ---------------------------------------------------------------------------
# A. Forbidden-string guards (precise patterns to avoid false positives)
# ---------------------------------------------------------------------------
FORBIDDEN = [
    (re.compile(r"(?i)bandit[^\n]{0,40}\bS113\b"),
     "lint rule miscredited: bandit's code is `B113` (S113 is Ruff's code)"),
    (re.compile(r"#\?\]"),
     "placeholder issue reference `#?` in a link"),
    (re.compile(r"\]\(https?://[^)\s]*\?\)"),
     "placeholder issue URL ending in `?`"),
    (re.compile(r"\bmantis specimen\b"),
     "orphaned 'mantis specimen' reference"),
    (re.compile(r"evidence/patterns-draft"),
     "internal draft path leaked into published docs"),
    (re.compile(r"\d+(?:st|nd|rd|th) distinct (?:audit )?framework"),
     "internal audit-framework-count metric leaked into published docs"),
    (re.compile(r"v0\.5 mutation playground"),
     "internal roadmap reference ('v0.5 mutation playground')"),
]

# These must never appear in the *published* docs (evidence links are stripped
# from taxonomy/ when generating pub/docs/).
PUB_FORBIDDEN = [
    (re.compile(r"Specimen: \["),
     "un-stripped evidence-specimen link in published docs"),
    (re.compile(r"evidence/github-issues"),
     "evidence path leaked into published docs"),
    (re.compile(r"Specimens live in"),
     "internal evidence-intro leaked into published docs"),
]

for md in sorted(DOCS.rglob("*.md")):
    text = md.read_text(encoding="utf-8")
    for rx, msg in FORBIDDEN + PUB_FORBIDDEN:
        m = rx.search(text)
        if m:
            add(md, f"{msg} — found {m.group(0)!r}")


# ---------------------------------------------------------------------------
# B. Cross-cutting-note count consistency
# ---------------------------------------------------------------------------
WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
}


def to_int(tok):
    """Normalize a count token ('Sixteen+', 'nine-plus', 'ten', '10', '9+') -> int, or None."""
    if tok is None:
        return None
    t = tok.strip().lower().rstrip("+").replace("-plus", "")
    if t.isdigit():
        return int(t)
    return WORDS.get(t)


NOTES = DOCS / "notes"
PATTERNS = DOCS / "patterns"

# notes that carry an entry count
COUNT_NOTES = [
    "ai-pedagogical-bias",
    "same-project-knows-right-pattern",
    "codified-guidance-is-insufficient",
    "defensive-choice-with-justifying-comment",
]

# headline phrasings -> capture the count token
HEADLINE_RX = [
    re.compile(r"appears in \*\*([\w-]+)\*\* entries"),
    re.compile(r"^([\w+-]+) entries (?:currently )?demonstrate", re.M),
]

canonical = {}
for slug in COUNT_NOTES:
    note = NOTES / f"{slug}.md"
    if not note.exists():
        add(note, "expected count-note file is missing")
        continue
    txt = note.read_text(encoding="utf-8")

    # (1) distinct entry slugs listed in the note's table
    table_entries = set(re.findall(r"^\|\s*\[`([a-z0-9-]+)`\]\(\.\./patterns/", txt, re.M))
    table_n = len(table_entries)

    # (2) headline count
    headline_n = None
    for rx in HEADLINE_RX:
        m = rx.search(txt)
        if m:
            headline_n = to_int(m.group(1))
            break

    if headline_n is None:
        add(note, "could not parse the note's headline entry count")
        canonical[slug] = table_n
    elif headline_n != table_n:
        add(note, f"headline says {headline_n} entries but the table lists {table_n} distinct entries")
        canonical[slug] = table_n
    else:
        canonical[slug] = table_n

# Footer count claims in each pattern entry, associated with the note they cite.
# A "Connection to [`<slug>`](../notes/<slug>.md) note." paragraph cites a note;
# within it we extract any membership-count token.
CONN_RX = re.compile(r"\*\*Connection to \[`([a-z0-9-]+)`\]\(\.\./notes/[a-z0-9-]+\.md\)")
COUNT_IN_PARA = [
    re.compile(r"one of ([\w+-]+) members of the AI-pedagogical-bias"),
    re.compile(r"spans ([\w+-]+) surfaces"),
    re.compile(r"one of ([\w+-]+) in the (?:cross-cutting note|same-project)"),
    re.compile(r"(?:now spans|formalizes this at|documented in|now a) ([\w+-]+) (?:entries|entry observation)"),
    re.compile(r"spans ([\w+-]+) entries"),
]

for md in sorted(PATTERNS.rglob("*.md")):
    text = md.read_text(encoding="utf-8")
    for para in re.split(r"\n\s*\n", text):
        cm = CONN_RX.search(para)
        if not cm:
            continue
        slug = cm.group(1)
        if slug not in canonical:
            continue
        want = canonical[slug]
        for rx in COUNT_IN_PARA:
            for tok in rx.findall(para):
                got = to_int(tok)
                if got is not None and got != want:
                    add(md, f"footer cites {slug} as {tok!r} (={got}) but the note's count is {want}")

# ---------------------------------------------------------------------------
if errors:
    print("Consistency check FAILED:\n")
    for e in errors:
        print(f"  - {e}")
    print(f"\n{len(errors)} problem(s).")
    sys.exit(1)
print("Consistency check passed: lint codes, links, and cross-cutting-note counts are consistent.")
