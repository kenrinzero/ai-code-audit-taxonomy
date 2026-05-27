---
name: resource-leak-no-context-manager
category: reliability
difficulty: low
generation: evergreen
since_model: null
evidence_grade: observed
---

# Resource Leak: No Context Manager

## Code example

```python
def transcribe_audio(audio_path: str) -> str:
    audio_file = open(audio_path, "rb")
    transcript = OpenAIClient(...).audio.transcriptions.create(file=audio_file, ...)
    return transcript.text
```

The function works in tests. The file is read; the transcript is returned. What is wrong is that `audio_file` is never closed. Every call leaks one file descriptor. In a long-running agent that transcribes audio repeatedly, the descriptor count climbs until the OS limit is hit: `OSError: [Errno 24] Too many open files`. If `OpenAIClient` raises, the file leaks regardless (no try/finally either).

The fix is the canonical Python context-manager idiom:

```python
def transcribe_audio(audio_path: str) -> str:
    with open(audio_path, "rb") as audio_file:
        transcript = OpenAIClient(...).audio.transcriptions.create(file=audio_file, ...)
    return transcript.text
```

The pattern has several visible sub-shapes in captured specimens:

- **`open()` without `with` or `close()`** (canonical). Three sites in agno-agi/agno: `tools/openai.py:90` (audio file), `utils/pickle.py:15` (pickle write), `utils/pickle.py:27` (pickle read). Each is a one-liner that leaks per-call.
- **One-liner-with-side-effect chain.** `pickle.dump(obj, file_path.open("wb"))` — the `open()` is the side effect inside the larger call expression, with no name binding to close later. The fluent shape is what the model produces; the multi-line `with` form requires breaking the chain.
- **Streaming-with-noqa-justification** (legitimate constraint, discipline-risk). Streaming writes that span lifecycles beyond a single `with` block legitimately hold open file handles as instance variables. The `noqa: SIM115` annotation is justified, but cleanup must be enforced separately. Captured in HomericIntelligence/ProjectScylla#1877 (3 file handles in `executor/capture.py` for stdout/stderr/agent-log streams).
- **Producer-consumer-cleanup-split.** A function returns an open file handle that the caller is expected to close, but no caller does. The function's *return-type contract* is itself the defect: returning ownership of a resource without an explicit cleanup contract. Captured in emerzon/litellm#56 (`get_audio_file_for_health_check()` returns open handle; consumers leak per health-check call).

All sub-shapes share the same root mechanism: the model produced resource acquisition (open, connect, allocate) without the corresponding cleanup, or split the lifecycle between producer and consumer without a clear ownership contract.

## Mechanism

A language model generates each resource-acquiring call in a local context. Python's idiomatic resource management uses *context managers* (`with` statement) — the canonical correct form is `with open(...) as f: ...` for files, `with conn.cursor() as cur: ...` for database cursors, `with lock: ...` for locks. The training corpus contains *both* the idiomatic form *and* the bare-acquisition form:

- **Idiomatic (correct)**: `with open(path) as f: data = f.read()` — explicit ownership, automatic close on scope exit (even under exception).
- **Bare (defective)**: `f = open(path); data = f.read()` — convenient one-liner; no automatic close.

The defective shape is over-represented per-token in three corpus segments:

**Tutorial code that demonstrates *what files can do*** uses bare `open(...)` because the example is showing API usage (`f.read()`, `f.write()`, `f.seek()`), and the file-handle lifecycle is a separate concern that distracts from the lesson. The example also typically calls `f.close()` at the end, which the model has seen — but the pattern is incomplete: real production code is interrupted by exceptions, conditional returns, and other control-flow paths that the explicit `close()` won't cover.

**One-liner Python idioms.** `pickle.dump(obj, open("file", "wb"))` is a fluent one-liner that appears in many places — the `open()` is inlined as the argument. The model has seen this form. The principled alternative (`with open(...) as f: pickle.dump(obj, f)`) is two lines and breaks the chain. Token-level fluency favors the one-liner.

**Stack Overflow answers about *what* an API does** vs. *how to use it safely*. A question about "how do I read a binary file in Python" gets an answer using `f = open(...); data = f.read()`. The follow-up question "what about exception safety" is a separate Q&A with its own corpus. The model has seen both but doesn't reliably connect them at generation time.

The training corpus also has Python *idiom guides* warning against bare-open patterns (PEP 343 about context managers; many "Python best practices" articles). The model has seen the warnings; the local-generation step doesn't consult them when producing the bare form.

Three concrete failure paths are visible in the captured specimens:

**Path 1: Same-template clustering across multiple files.** agno-agi/agno has 3 file-handle leak sites within one project, all from the same template (`open()` without `with`). The audit explicitly identifies the long-running-agent failure mode: *"On long-running agents or applications with many tool calls, leaked file handles accumulate. Can hit OS file descriptor limits."* The sticky-local-pattern observation applies at the resource-acquisition layer — once the model produced one bare-open, the next two sites used the same defective template.

**Path 2: Justified-noqa with cleanup-discipline-risk.** ProjectScylla's `capture.py:118-122` opens three streaming file handles as instance variables and annotates each with `noqa: SIM115`. The justification is *valid* (streaming writes require persistent open handles that span beyond a single `with` block). The audit acknowledges the constraint but flags the discipline-risk: *"If the class's cleanup method raises an exception, handles may leak."* This is the legitimate-but-fragile sub-shape — the suppression is principled, but the cleanup must be enforced separately.

**Path 3: Producer-consumer-cleanup-split contract.** emerzon/litellm's `get_audio_file_for_health_check()` returns an open file handle. Every consumer (the health-check function) is expected to close it; no consumer does. The defect is in the function's *return-type contract* — it returns ownership of a resource without an explicit lifecycle. The audit's structured BUG_CONFIRMED workflow reproduced fd-count growth from 4 to 9 after 5 calls. The fix recommendation: return bytes/BytesIO instead, transferring lifecycle to the producer.

The pattern is **AI-amplified, not AI-exclusive**. Human Python programmers also write bare-open code, particularly when prototyping or when the file handle is *intended* to outlive the current scope. The AI-amplified differential rests on:

1. **Initial-state authorship in deployment-context-sensitive code**: AI-generated agent frameworks, MCP servers, and long-running services produce the pattern from initial commit at sites that *will* be called repeatedly in production.
2. **One-liner-with-side-effect clustering**: AI produces the fluent `pickle.dump(obj, path.open("wb"))` form across multiple sites; humans tend to write the multi-line form because it's clearer (and the model has been trained on tutorial fluency, not production clarity).
3. **Producer-consumer split contracts**: AI-generated helper functions return open handles without explicit cleanup contracts; consumers reproduce the defect at every call site.

## Evidence / incident

Three captured specimens, each from a different AI-coded Python codebase, each illustrating a distinct sub-shape. Specimens live in `evidence/github-issues/`.

- **[agno-agi/agno#7405](https://github.com/agno-agi/agno/issues/7405)** — canonical `open()` without `with`/`close()` at three sites. AI agent framework with CLAUDE.md (7145 bytes). Sites: `tools/openai.py:90` (audio transcription), `utils/pickle.py:15` (pickle write), `utils/pickle.py:27` (pickle read). The pickle sites use the one-liner-with-side-effect shape (`pickle.dump(obj, file_path.open("wb"))`). Long-running-agent failure mode named explicitly. Specimen: [agno-agi-agno-7405.md](../../evidence/github-issues/2026-05-16-agno-agi-agno-7405.md).
- **[HomericIntelligence/ProjectScylla#1877](https://github.com/HomericIntelligence/ProjectScylla/issues/1877)** — streaming-with-noqa-justification, discipline-risk. Three file handles in `executor/capture.py:118-122` annotated `# noqa: SIM115`. CLAUDE.md (21286 bytes). The audit framework is "repo-analyze-strict v3.0.0 (ProjectHephaestus skill)" — 18th distinct framework, multi-section weighted scoring with anti-inflation grading. Specimen: [HomericIntelligence-ProjectScylla-1877.md](../../evidence/github-issues/2026-05-16-HomericIntelligence-ProjectScylla-1877.md).
- **[emerzon/litellm#56](https://github.com/emerzon/litellm/issues/56)** — producer-consumer-cleanup-split contract. `get_audio_file_for_health_check()` returns an open file handle that callers never close. CLAUDE.md (14619 bytes); structured "BUG_CONFIRMED-..." validated-report audit workflow with explicit reproduction (`/proc/self/fd` count grows 4→9 after 5 calls). 19th distinct audit framework. Specimen: [emerzon-litellm-56.md](../../evidence/github-issues/2026-05-16-emerzon-litellm-56.md).

Three different sub-shapes (canonical bare-open / streaming-with-noqa / producer-consumer-split), three different audit framings (project bug report / repo-analyze-strict skill / BUG_CONFIRMED validated report), three different defect surfaces (long-running agent tool calls / streaming class cleanup discipline / health-check fd growth).

Supplementary references:

- **[invesalius/invesalius3](https://github.com/invesalius/invesalius3)** — "Resource leaks from file handles opened without context managers" (2026-03-08). Established medical-imaging project; AI-authorship of underlying code uncertain.
- **[mlcommons/inference](https://github.com/mlcommons/inference)** — "Codebase Refactor: Fix Unclosed File Handles" (2026-02-09). ML benchmark; multiple unclosed file handles.
- **[KimiNewt/pyshark](https://github.com/KimiNewt/pyshark)** — "file handle leak in livecapture.py" (2026-03-19).
- **[saifmsaleh/SDM_Telemetry](https://github.com/saifmsaleh/SDM_Telemetry)** — "Bug fixes: NameError on non-Mac, thread leak, file handle leak, shutdown crash" (2026-04-10). Multi-defect issue.

Ruff has rule **SIM115** (`open-file-with-context-handler`); flake8 has equivalent via plugins. Widely-adopted community lint rules; the AI-amplified observation is that the rule fires at notable density in young AI-coded projects.

## Detection cues

What to look for in a diff or completion:

- **`open(...)` not inside a `with` statement.** The most direct signal. Particularly suspect when no explicit `close()` follows or when the call is inside an expression (one-liner side-effect).
- **`f = open(...)` followed by use, with no `close()` on every control-flow path.** Even if there's an explicit `close()` at one return path, exception paths and other returns may leak.
- **`pickle.dump(obj, path.open(...))` / `json.dump(obj, path.open(...))`** etc. — the one-liner-with-side-effect shape. The `open()` is fluently inlined; no `with` wrapper.
- **Functions that return an open file handle.** A function whose return type is `IO[bytes]` or `TextIO` (or just returns the result of `open()`) creates an ownership-handoff problem. Verify every caller closes it; consider returning `bytes`/`BytesIO` / using a context-manager-returning function instead.
- **Streaming file handles held as instance variables.** If `self._stream_file = open(...)` is in `__init__`, the class is taking ownership of the file's lifetime. Verify the class has a `close()` / `__del__` / `__exit__` that releases it, *and* that the cleanup runs even under exception.
- **`# noqa: SIM115` annotations** that don't have an accompanying justification comment. The suppression may be principled (streaming use cases) or reflexive (just shut up the linter); a comment names the constraint.
- **Other resource types**: `sqlite3.connect(...)`, `socket.socket()`, `tempfile.NamedTemporaryFile(delete=False)`, `threading.Lock().acquire()` — all are context-manageable. The pattern generalizes beyond file handles to any allocate-must-release primitive.

The diagnostic question: *if this code raises in the middle, does the resource get released?* If yes, the pattern is safe (try/finally, with, registered cleanup). If no, every exception path is a leak.

Ruff `SIM115` catches the file case mechanically. `tracemalloc` and `resource.getrusage()` can reveal accumulated leaks at runtime. `/proc/self/fd` count is the most direct measurement on Linux.

## Notes

**Category `reliability`.** Joins [`missing-network-timeout`](missing-network-timeout.md) as the second entry in this category. Both stem from the model's tutorial-corpus inheritance: missing-timeout omits a defensive parameter; resource-leak omits a cleanup primitive. Both produce *production-time-only* defects that don't surface in test/example contexts.

**Difficulty rated `low`.** Spotting `open(...)` without `with` is visually trivial — `SIM115` catches it mechanically. The reason this is in the taxonomy is *density and form* (AI-generated code produces the bare form in deployment-context-sensitive paths), not difficulty. The harder cases are the producer-consumer-split contract (where the visible call site looks fine but the function's return-type-contract is the bug) and the streaming-with-noqa-justification (where the suppression is valid but cleanup must still be enforced).

**The pattern is AI-amplified, not AI-exclusive.** Restated: every Python developer writes bare-open code occasionally. The AI-amplified differential rests on initial-state authorship in long-running services, one-liner-with-side-effect clustering, and producer-consumer split contracts that propagate leaks across every call site.

**False-positive shapes.** Be cautious before flagging:

- *Genuinely-streaming files held by a class for its lifetime.* The ProjectScylla case — the class owns the file for the lifetime of the stream; closing inside a `with` block would close prematurely. The principled solution is to make the class itself a context manager. The cue is whether the class implements `__enter__` / `__exit__` or has a documented `close()` method.
- *Temporary files with `delete=False` for cross-platform reasons.* `tempfile.NamedTemporaryFile(delete=False)` is intentionally not auto-cleaned because on Windows the file can't be opened twice. The cue is whether the lifecycle is documented and the cleanup is enforced elsewhere.
- *Files passed to APIs that take ownership.* Some APIs (`tarfile.open(fileobj=f)`, certain `subprocess` use cases) accept a file object and take ownership of closing it. The cue is whether the API documents ownership transfer.
- *Files held open as sentinels.* PID files, lock files, file-based mutexes — these are intentionally held open for the process lifetime. The cue is whether the file's *purpose* is the open state itself.
- *Test fixtures with manual setup/teardown.* `setUp` / `tearDown` pairs are an acceptable alternative to `with` in test code, though context managers are usually cleaner.

**Mutation operator hint.** A deterministic mutation that introduces the pattern from clean code:

- Replace `with open(path) as f: data = f.read()` with `f = open(path); data = f.read()` (drop the with)
- Replace `with open(path, "w") as f: json.dump(obj, f)` with `json.dump(obj, open(path, "w"))` (one-liner-with-side-effect)
- Take a function that returns `bytes` (closing the file internally) and change it to return the open file handle (producer-consumer split)
- Take a streaming class with `__enter__`/`__exit__` and remove the context-manager protocol, leaving callers to remember `.close()`
- Wrap a streaming `open(...)` call in `# noqa: SIM115` without justification (silenced-rather-than-fixed)

These compose with [`swallowed-exceptions`](swallowed-exceptions.md) — a bare `open()` followed by `try: ...; except Exception: pass` produces resource-leak + silenced-error, the maximally-defective combination. The leak is invisible (no exception surfaces to logs) and accumulates per failure.

**Connection to [`codified-guidance-is-insufficient`](../notes/codified-guidance-is-insufficient.md) note.** Ruff `SIM115` and PEP 343 (context managers, 2005) are mature community-recognized guidance. AI-generated codebases reproduce the pattern despite the guidance — agno (CLAUDE.md present, 3 sites), litellm (CLAUDE.md present, 1 critical site). The ProjectScylla case is a *legitimate-suppression* variant where the lint rule was suppressed with justification, but the suppression itself becomes a discipline-risk surface.

**Connection to [`defensive-choice-with-justifying-comment`](../notes/defensive-choice-with-justifying-comment.md) note.** The ProjectScylla `# noqa: SIM115` annotations are a *legitimate* form of comment-as-justification — the comment names a real constraint (streaming writes require persistent handles), the constraint survives verification, and the suppression is principled. Notably distinct from the typical comment-as-justification shape where the justification doesn't survive verification.

**Connection to long-running-service deployment context.** This entry, [`missing-network-timeout`](missing-network-timeout.md), [`async-await-mismatch`](async-await-mismatch.md), and [`assert-for-runtime-validation`](assert-for-runtime-validation.md) all surface defects that are invisible in tutorial / test contexts but accumulate in long-running production services (agents, MCP servers, web servers). The cross-cutting observation: AI-generated code lacks deployment-context-sensitivity in its default behavior; the cure is mechanical enforcement (CI lint rules) rather than documentation.
