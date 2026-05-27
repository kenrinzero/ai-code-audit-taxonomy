---
name: narrating-comments
category: documentation
difficulty: low
generation: evergreen
since_model: null
evidence_grade: observed
---

# Narrating Comments

## Code example

```python
def encrypt_file(path: Path, password: str, output: Path) -> None:
    """Encrypt a file using AES-CBC with a password-derived key.

    Args:
        path (Path): The path to the file.
        password (str): The password for key derivation.
        output (Path): The path where the encrypted file will be written.
    """
    # Read binary file
    with open(path, 'rb') as f:
        data = f.read()

    # Generate salt
    salt = os.urandom(16)

    # Key derivation
    key = derive_key(password, salt)

    # Generate IV
    iv = os.urandom(16)

    # Encryption
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    encryptor = cipher.encryptor()
    encrypted = encryptor.update(data) + encryptor.finalize()

    # Save IV to file
    with open(output, 'wb') as f:
        f.write(iv)
        f.write(salt)
        f.write(encrypted)
```

The function works correctly. The comments are also correct in the sense that they accurately describe what the next line does. What is wrong is that they convey no information the code does not already convey to a Python reader who can see the names.

- `# Read binary file` precedes `with open(path, 'rb') as f: data = f.read()`. The line already says "read binary file" in code.
- `# Key derivation` precedes `key = derive_key(password, salt)`. The function's name is `derive_key`.
- `# Encryption` precedes the cipher block. The variable is named `encryptor`.
- The `Args:` section describes `path (Path): The path to the file.` — the type is in the annotation; the description is the parameter name in lowercase prose.

A tightened version keeps only the WHY-comments and trusts the names to do the WHAT-work:

```python
def encrypt_file(path: Path, password: str, output: Path) -> None:
    """Encrypt `path` to `output` using AES-CBC with a password-derived key.

    The IV and salt are stored as a header in the output file; readers must
    consume the first 32 bytes before decrypting the remainder.
    """
    with open(path, 'rb') as f:
        data = f.read()

    salt = os.urandom(16)
    key = derive_key(password, salt)
    iv = os.urandom(16)

    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    encryptor = cipher.encryptor()
    encrypted = encryptor.update(data) + encryptor.finalize()

    # IV and salt are prepended so the decryption side can recover them.
    with open(output, 'wb') as f:
        f.write(iv)
        f.write(salt)
        f.write(encrypted)
```

The remaining comment explains a non-obvious correctness constraint (the file format) — what Uncle Bob's *Clean Code* calls a "useful" comment, what Karpathy's published guidelines call a comment about a "non-obvious constraint, workaround, or subtle invariant." A reader who scans the new version learns more from less surface.

The pattern has several visible sub-shapes in captured specimens:

- **WHAT-narration before each line** — `# Read binary file` / `# Key derivation` / `# Encryption`. Captured in Slice-N-Dice#12.
- **Step-by-step enumeration** — `# Step 1: Load data` / `# Step 2: Process each question` / `# Step 3: ...`. Captured in bird-bench#13. Particularly AI-typical because tutorial code uses this scaffolding heavily.
- **WHAT-narrating function docstrings** — `def handle_event(...): """Handle an incoming event."""`. The docstring says what the function name already said. Captured in battle-city-clone#139.
- **WHAT-restating class docstrings** — class-level docstrings that re-describe the class's already-self-evident role.
- **Redundant `Args:` sections** — `Args: file_path (str): The path to the file.` — name + type + lowercase-prose-restating-the-name. Captured in Slice-N-Dice#12.
- **`# Section Banner` comments** — `# Controller registry` / `# Event dispatch` / `# Menu action queue`. Pedagogical-textbook scaffolding that divides a file into named sections without adding information beyond what the code structure already conveys. Captured in battle-city-clone#139.

All sub-shapes share the same root mechanism: the model produced documentation that *describes what the code does* when the code's names, signatures, and structure already do that work. The cure across all sub-shapes converges: delete the WHAT-narration; keep only the WHY-explanations; if a WHAT-narration would be useful, that is a signal the *code* is not self-documenting enough and the right fix is better names rather than more comments.

## Mechanism

A language model generates documentation by predicting tokens that have appeared near similar function bodies in the training corpus. The corpus is overwhelmingly dominated by *pedagogical code*: tutorials, Stack Overflow answers, blog posts, course materials, library documentation written for users-who-don't-know-the-library, README examples written for new contributors. In all of these contexts, narrating each line is *appropriate* — the reader is being taught what each operation does, and the comment is the teaching surface.

Production code is the opposite. In production code, the reader already knows what `with open(path, 'rb') as f: data = f.read()` does; what the reader does *not* know is why this specific file is being read at this specific point in the program, what assumptions hold about the file's content, or what should happen if the read fails. Production-code comment conventions (Clean Code, Karpathy guidelines, most modern Python style guides) explicitly distinguish "comments that explain WHAT the code does" (anti-pattern, almost always wrong) from "comments that explain WHY the code is structured this way, or what non-obvious constraint applies" (useful, sometimes essential).

The model has been trained on both kinds of code. It cannot tell, from local context alone, whether the function it is generating will be read by a learner (where WHAT-narration helps) or by a maintenance engineer (where WHAT-narration is noise). The model's prior is *pedagogically inflected* because the training corpus is heavy on pedagogical material. So the default behavior is to over-document toward the tutorial style.

Three concrete failure paths are visible in the captured specimens:

**Path 1: Pre-line narration on routine operations.** The model produces a sequence of operations with a one-line WHAT-narration above each: `# Read binary file`, `# Key derivation`, `# Encryption`. Each comment is technically correct; together they form the pedagogical scaffolding of a tutorial walkthrough rather than the terse logic of a production function. Slice-N-Dice#12 captures this on AES-CBC encryption code.

**Path 2: Step-N enumeration scaffolding.** The model imposes a top-level structural narrative on the function: `# Step 1: Load data`, `# Step 2: Process each question`, `# Step 3: ...`. This is the AI-typical scaffolding shape — the function is being narrated as a procedure with named steps. Bird-bench#13 captures this. Humans sometimes do this too in long scripts, but the multi-line "Step N: <verb>" form is much more common in AI-generated code because the training corpus contains many tutorials that use exactly this structure.

**Path 3: Decorative docstrings.** The model fills out the function's docstring with a full Google-style or NumPy-style template — Summary, Args, Returns, Raises — even when the function is a 3-line internal helper where the signature already conveys everything the template would say. Battle-city-clone#139 captures multiple instances. Slice-N-Dice#12 captures the `Args:` shape specifically (`file_path (str): The path to the file.`). The model has internalized "good code has docstrings" as a token-level pattern; the question of *what scale of function deserves a full docstring template* is not part of that pattern.

The training corpus also reinforces a subtler shape: **the model's own next generation step uses the existing narration as context**. If the existing code in the file has WHAT-comments, the model generating new code in that file is more likely to produce WHAT-comments to match the local style. The pattern compounds within a session — and across the codebase as adjacent files share the same defective convention. This is the same sticky-local-pattern observation that drives [`unjustified-lazy-import`](unjustified-lazy-import.md) clusters and [`unreachable-defensive-guard`](unreachable-defensive-guard.md) clusters, applied at the comment layer.

The defect path here is *not* a direct correctness defect. Narrating-comments do not crash the program; they do not return wrong values; they do not silently fail. The defect paths are:

1. **Visual noise reduces review effectiveness.** A reader scanning a function for a bug skips over WHAT-comments (their attention has learned that the comment doesn't add information). When a WHY-comment appears, it is also skipped — the reader's filter has been calibrated against the volume of WHAT-narration. Bugs that a WHY-comment would have surfaced are missed.
2. **Comment-code drift produces lies.** A WHAT-comment is correct at the moment of generation. The code is later refactored — the operation changes, the names change. The comment stays. Now the comment *describes what the code used to do*, which is a lie. The lie is harder to detect than the absence of a comment would have been.
3. **API documentation becomes harder to browse.** A docstring that describes the function's signature in prose forces the reader to read the prose to learn what the signature already shows. Browsing 20 such docstrings is much slower than browsing 20 terse one-liner docstrings paired with informative signatures.

This pattern is in the taxonomy primarily as a **calibration tell** rather than as a defect-direct concern. A reader of AI-generated code who knows the WHAT-narration / step-enumeration / decorative-docstring shapes can skim past them without slowing down — and can pause appropriately on the rare WHY-comment that genuinely conveys information. A reader who is not calibrated for the pattern will either be slowed by the noise or will train themselves to skip all comments, including the useful ones.

The pattern is **AI-amplified, not AI-exclusive**. Human developers also write WHAT-comments, particularly in code they expect novices to read, or in code where they are unsure of the names they chose. The AI-amplification claim rests on frequency and consistency: AI-generated code produces WHAT-narration at densities (multiple per function) that are uncommon in human-written production code, and it applies the pattern uniformly across files in ways human style-drift does not. The three captured specimens all reference *pre-existing style guidelines* (CLAUDE.md, Karpathy, Uncle Bob) that the AI-generated code violates — codified human guidance against the pattern exists; the AI continues to produce it.

## Evidence / incident

Three captured specimens, each citing a different documentation style guideline as the basis for the audit. Specimens live in `evidence/github-issues/`.

- **[StefanBS/battle-city-clone#139](https://github.com/StefanBS/battle-city-clone/issues/139)** — CLAUDE.md-codified-but-violated. Issue body directly quotes the project's CLAUDE.md ("default to writing no comments. Only add one when the WHY is non-obvious... Don't explain WHAT the code does"); audit then enumerates violations across three files, including WHAT-narrating function docstrings, WHAT-restating class docstrings, and `# Section Banner` comments. Captured during cleanup after an SDL GameController migration. Specimen: [StefanBS-battle-city-clone-139.md](../../evidence/github-issues/2026-05-15-StefanBS-battle-city-clone-139.md).
- **[incendiary/Slice-N-Dice#12](https://github.com/incendiary/Slice-N-Dice/issues/12)** — karpathy-guidelines audit. Six WHAT-comments on routine cryptographic operations (`# Read binary file`, `# Key derivation`, `# Encryption`, `# Save IV to file`, etc.) plus redundant `Args:` sections in docstrings restating type information. Contains the cleanest WHAT-vs-WHY contrast in the project's evidence (one comment kept because it explains a non-obvious correctness constraint; six dropped because they restate the code). AI-authorship signals are weaker than other specimens but the pattern-content is consistent. Specimen: [incendiary-Slice-N-Dice-12.md](../../evidence/github-issues/2026-05-15-incendiary-Slice-N-Dice-12.md).
- **[matsonj/bird-bench#13](https://github.com/matsonj/bird-bench/issues/13)** — Uncle Bob Clean Code audit. Identifies the canonical step-by-step enumeration shape (`# Step 1: Load data` / `# Step 2: Process each question`). Project has CLAUDE.md and MotherDuck MCP context. Audit cites Clean Code's exception list (legal, informative, warning, TODO, public-API docstrings) as the false-positive shapes. Specimen: [matsonj-bird-bench-13.md](../../evidence/github-issues/2026-05-15-matsonj-bird-bench-13.md).

Three different documentation-style guidelines all cited against AI-generated narration:

| Specimen | Guideline cited | Era |
|----------|----------------|-----|
| StefanBS/battle-city-clone | project's CLAUDE.md ("Don't explain WHAT") | AI-era project convention |
| Slice-N-Dice | Karpathy guidelines | AI-era developer convention |
| bird-bench | Uncle Bob's *Clean Code* (2008) | pre-AI-era style classic |

The convergence is itself diagnostic: a 17-year-old style guide (Clean Code), an AI-era developer's published guidance (Karpathy), and a project-specific CLAUDE.md all describe the same defect class. The pattern is well-recognized; the AI keeps producing it anyway.

Additional supplementary reference:

- `aabtzu/libertas-travel#48` (the AI-tells audit referenced for [`unreachable-defensive-guard`](unreachable-defensive-guard.md) and other entries) lists in its AI-tells table: *"Docstrings on 3-line functions — Pros write `"""Format date."""` and move on. AI writes paragraphs."* — independent identification of the same pattern at the audit-summary level (not captured as a primary specimen for this entry because the audit references the pattern abstractly rather than quoting specific code).

## Detection cues

What to look for in a diff or completion:

- **A comment immediately above a line that restates the line in English.** `# Read binary file` above `with open(path, 'rb')`. If you can predict the comment from reading the code, the comment is doing no work.
- **Step-by-step enumeration scaffolding.** `# Step 1: Load data`, `# Step 2: Process each question`. Particularly suspect when the steps are obvious from the function structure (a function called `process_questions(data)` does not need a comment saying "Step 1: load the questions").
- **Function docstrings that paraphrase the function name.** `def handle_event(...): """Handle an incoming event."""`. If the docstring is one sentence and that sentence is the function name in prose, the docstring is decorative.
- **`Args:` sections where each parameter description is the parameter name in prose.** `Args: file_path (str): The path to the file.` is decorative. `Args: file_path: Must be readable; the caller is responsible for ensuring it exists.` is informative.
- **`# Section Banner` style comments.** `# ====== Event dispatch ======` or `# --- Controller registry ---`. These divide a file into named sections; sometimes useful in very long files, almost always noise in normal-length files.
- **Class docstrings that restate the class name's role.** `class PlayerInput: """Represents a player's input."""` adds nothing beyond the class name.
- **Multiple consecutive WHAT-comments.** One narration on a tricky line is sometimes fine; three or four in a row strongly indicates the pattern.

The diagnostic question for any candidate: *if I deleted this comment, what would the reader lose?* If the answer is "nothing — the code says the same thing," the comment is WHAT-narration. If the answer is "they would not know about this hidden constraint / this workaround / this design rationale," the comment is WHY-explanation and should stay.

The cure is rarely "delete and leave." Often it is "delete the comment and rename the operation to be self-explanatory" (Uncle Bob's *Clean Code* prescription, surfaced in the bird-bench specimen). Sometimes the comment is hiding a request for a better name.

## Notes

**Category `documentation`** — new category. Previous entries have used `structure`, `testing`, `defensive-programming`, `error-handling`, `control-flow`. This is the first entry that does not fit any of those cleanly; documentation-quality concerns are a real category of AI-typical pattern that the existing list did not anticipate. The category-revisit deferred to ~10 entries (per CLAUDE.md) is approaching; with this entry the category list grows to six and the revisit becomes more concretely useful.

**Difficulty rated `low`.** Spotting a WHAT-comment is visually immediate — read the comment, read the next line, compare. A reader who knows the WHAT-vs-WHY distinction can scan AI-generated code very quickly and recognize the pattern on a single line of context. The diagnostic step is more mechanical than for any other entry in the taxonomy.

**Defect grade.** This is in the taxonomy as a **calibration tell** more than as a defect-direct pattern. Narrating-comments do not crash, do not return wrong values, do not silently fail. They reduce review effectiveness and produce comment-code drift over time. The entry is included because:

1. It is one of the **most consistent AI-tells** — readers calibrated for this pattern can quickly distinguish AI-generated from human-written code in production contexts
2. The frequency differential between AI and human-generated code is large (AI produces this at much higher density)
3. The pattern is referenced explicitly in multiple AI-tell audits (aabtzu#48, the three specimens cited here), demonstrating community-level recognition

Future entries may include patterns with similar "calibration tell" profiles. The project's design supports this: the framing is calibration training, not exclusively defect prevention.

**The pattern is AI-amplified, not AI-exclusive.** Human developers write WHAT-comments, particularly in tutorial code, in code-for-novices, or when uncertain about naming. The AI-amplified claim rests on density and consistency: AI applies the pattern uniformly across functions where humans would not, and at line-by-line densities humans rarely reach.

**False-positive shapes.** Be cautious before flagging:

- *Legal comments.* `# Copyright 2026 ...` is required by license terms in many contexts.
- *Informative comments on non-obvious code.* `# This regex matches RFC 5322 email-addr-spec, see https://...` explains a non-obvious construction. Keep.
- *Warning comments.* `# DO NOT remove without filing a release-note — downstream depends on this attribute name` is essential context.
- *TODO / FIXME / HACK comments.* Temporary markers for known unfinished work. Keep until the work is done.
- *Docstrings on public API surfaces.* A library function exposed to external users genuinely benefits from a full Google-style docstring; a private helper does not. The cue is whether the function is part of the package's `__init__.py` exports or its documented API.
- *Comments above non-obvious algorithmic code.* `# Floyd's cycle-finding: tortoise+hare; O(1) space, O(n) time` is naming an algorithm whose presence in the code is not obvious from the variable names. Keep.
- *Comments above operations that look obvious but encode a subtle invariant.* `# Must read salt and IV before key derivation — derive_key reads them as side effects` documents a hidden coupling. Keep.

**Mutation operator hint.** A deterministic mutation that takes a function with terse / no comments and adds WHAT-narration produces this pattern from clean code. Variants:

- Add a `# <verb> <noun>` comment above every non-trivial statement in a function
- Wrap a function body in step-by-step `# Step N: <description>` scaffolding
- Expand a one-line docstring into a full Google-style Summary + Args + Returns block
- Insert `# Section Banner` comments to divide a file into named sections
- Add an `Args:` section to a docstring that restates the parameter names in prose

These compose with [`near-identical-siblings`](near-identical-siblings.md) and [`unjustified-lazy-import`](unjustified-lazy-import.md) — a file that has near-identical siblings *each* decorated with full WHAT-narration docstrings is the maximally AI-tell shape; the duplication is obvious *and* the decoration confirms the pedagogical generation mode.

**Connection to [`codified-guidance-is-insufficient`](../notes/codified-guidance-is-insufficient.md) note.** This entry contributes the canonical instance of "project CLAUDE.md says 'Don't explain WHAT the code does' and the AI-generated code keeps narrating each line anyway" (StefanBS/battle-city-clone#139). The codified convention is correct and known to the project; the model's local-generation step does not consult the convention strongly enough to comply. The note now spans ten+ entries.

**Connection to [`ai-pedagogical-bias`](../notes/ai-pedagogical-bias.md) note.** This entry is one of five members of the AI-pedagogical-bias meta-family alongside [`print-instead-of-logging`](print-instead-of-logging.md), [`hardcoded-config-values`](hardcoded-config-values.md), [`missing-network-timeout`](missing-network-timeout.md), and [`f-string-in-logger-call`](f-string-in-logger-call.md). The corpus's pedagogical-heavy distribution makes the model produce WHAT-narrating comments by default; the production-appropriate alternative is WHY-comments (non-obvious constraints) or no comments at all.

**Connection to [`defensive-choice-with-justifying-comment`](../notes/defensive-choice-with-justifying-comment.md) note.** Narrating comments are themselves the comment-as-justification shape *meta-applied* — the comment narrates an intent the code's structure does not need (the operation is already self-evident from the line below). The comment is generated alongside the code by the same local-attention context, not as an independent verification step. This entry is one of 7+ in the cross-cutting note; it sits inside the note as the canonical "the comment IS the defect" instance.
