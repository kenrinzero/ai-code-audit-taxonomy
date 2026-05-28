---
name: tarfile-extractall-without-filter
category: security
difficulty: low
generation: evergreen
since_model: null
evidence_grade: observed
---

# Tarfile Extractall Without Filter

## Code example

```python
import tarfile

def install_archive(archive_path: str, install_dir: str) -> None:
    with tarfile.open(archive_path, "r:gz") as tar:
        tar.extractall(install_dir)
```

The function looks fluent. The archive is opened with the canonical `with` block; the extraction is one line. For trusted archives the function works perfectly.

The defect is invisible until the archive is attacker-controlled. A malicious tar file can contain entries with paths like `../../etc/passwd` (relative traversal) or absolute paths like `/root/.ssh/authorized_keys`. `tarfile.extractall(install_dir)` writes each entry to its declared path — *outside* `install_dir` if the declared path traverses up. This is **CVE-2007-4559**, also known as "zip slip" (though the original CVE is for tar). The CVE has been open in Python's tarfile module for nearly 20 years.

Python 3.12 (PEP 706, 2024) added `tarfile.data_filter` as the recommended safe-extraction approach. The tightened version becomes a one-line fix:

```python
def install_archive(archive_path: str, install_dir: str) -> None:
    with tarfile.open(archive_path, "r:gz") as tar:
        tar.extractall(install_dir, filter='data')   # rejects path-traversal entries
```

The `filter='data'` argument (also `'tar'` and `'fully_trusted'` exist) tells Python to apply the data-filter rules: members must not have absolute paths; relative paths must not contain `..` components that escape the destination; special files (devices, fifos) are rejected; symlinks are sanitized.

On pre-Python-3.12 (the codebase may need to support older versions), the cure is a manual safe-extract wrapper:

```python
def safe_extract(tar: tarfile.TarFile, path: str = ".") -> None:
    abs_dest = os.path.realpath(path)
    for member in tar.getmembers():
        member_path = os.path.realpath(os.path.join(path, member.name))
        if not member_path.startswith(abs_dest + os.sep) and member_path != abs_dest:
            raise ValueError(f"Path traversal in archive: {member.name}")
    tar.extractall(path)
```

The pattern has several visible sub-shapes in captured specimens:

- **Established MLOps platform** — the defect exists in long-established Python projects that haven't migrated to the Python 3.12 data_filter idiom. Captured in mlrun/mlrun (Bandit B202 HIGH; part of a 2026-03-16 batch-audit across 5+ Python repos).
- **AI/research tooling** — arXiv source-archive extractors operating on user-supplied untrusted archives. The defect is particularly costly here because the trust boundary is *paper author → automated pipeline*. Captured in kpollz/daily_papers_tool (Critical; AGENTS.md 23KB).
- **Cross-platform desktop utility** — auto-installers extracting binaries from internet downloads. Captured in iAmGiG/FFmpeg-AutoToolkit (HIGH; references CVE-2007-4559 explicitly; provides both Python 3.12+ and pre-3.12 fix recipes).

All sub-shapes share the same root mechanism: the model produced `tar.extractall(path)` without the `filter='data'` argument that Python 3.12 added.

## Mechanism

A language model generates archive-extraction code from local context. The training corpus contains:

- **Pre-Python-3.12 form** (the corpus's dominant shape): `with tarfile.open(path) as tar: tar.extractall(dest)`. This is the canonical "how to extract a tar archive in Python" Stack Overflow answer, tutorial example, and library README. The vast majority of training-data examples use this form because (a) Python 3.12 is recent (2024) and (b) the corpus weight of pre-3.12 Python content dwarfs post-3.12 content.

- **Post-Python-3.12 form** (the corpus's emerging shape): `with tarfile.open(path) as tar: tar.extractall(dest, filter='data')`. PEP 706 (2024) added the argument; community guidance is migrating; the corpus is slowly catching up.

- **Manual safe_extract wrapper** (the corpus's hand-rolled shape): security-conscious projects wrote their own member-validation function before Python 3.12 made it built-in. The wrapper code appears in security blog posts and CVE-2007-4559 remediation guides.

The defective shape is over-represented per-token in two corpus segments:

**Python's own tarfile documentation, pre-Python-3.12.** The Python docs themselves used `tar.extractall(path)` as the canonical example for years. The model has seen the canonical Python-docs form, often without the surrounding CVE-2007-4559 context.

**Stack Overflow answers about "how to extract a tar in Python."** Questions like "how do I extract a .tar.gz in Python" get answers using the bare `extractall(dest)` form because the asker's question is *what does the API look like*, not *how do I extract safely*. Security-conscious follow-ups exist in separate Q&A threads.

The model knows about the `filter='data'` argument in the abstract — it can describe what it does when asked directly. What it does not do reliably during local generation is *choose* the filter argument when producing an extractall call. The token-level prediction follows the corpus-dominant pre-Python-3.12 form.

This is the **deployment-context-blind** failure mode applied to a deprecation-recent ecosystem change. The defect path requires:
1. The function runs on a deployment that handles externally-supplied archives.
2. The Python version is 3.12+ (where the filter argument is available and the unfiltered form emits a DeprecationWarning).
3. The codebase has not been migrated to the filter idiom.

All three are common in 2026 — Python 3.12 adoption is widespread; AI-generated code is being deployed; archives come from many sources.

The defect path is direct: arbitrary file write on the extraction host. Concrete attack scenarios from the captured specimens:

- **mlrun**: malicious archive in an artifact store overwrites files on the MLRun execution host
- **daily_papers_tool**: malicious arXiv source tarball overwrites files in the user's home directory during paper-processing pipeline
- **FFmpeg-AutoToolkit**: man-in-the-middle on the FFmpeg download URL serves a malicious archive that overwrites system files

This pattern is **AI-amplified, not AI-exclusive**. Human Python programmers wrote bare extractall calls for years (the corpus is full of them). The AI-amplified differential rests on:

1. **Initial-state authorship after Python 3.12**: AI-generated codebases produce the pre-3.12 form even when the project targets Python 3.12+ (where the filter argument is the documented recommendation).
2. **Codified-guidance-is-insufficient at the bandit/CVE layer**: Bandit B202 catches the pattern; CVE-2007-4559 is documented; Python 3.12 emits a DeprecationWarning. AI-generated codebases still produce the unfiltered form.
3. **Trust-boundary-shift on archive sources**: AI-generated code routinely fetches archives from third-party sources (paper repos, model registries, dataset hubs, package indexes) — exactly where the trust assumption fails first.

## Evidence / incident

Three captured specimens from different AI/Python project domains. Detailed specimen notes are not included in the public repository.

- **[mlrun/mlrun](https://github.com/mlrun/mlrun)** — established MLOps platform; `mlrun/package/utils/_archiver.py` extracts archives without member validation. Bandit B202 HIGH. Part of a **2026-03-16 batch audit** filed across 5+ Python repos (mlrun, PyCQA/bandit, alephdata/memorious, eliasgranderubio/dagda, crate/crate-python) with identical structure — suggests an automated security-audit service. References CWE-22. AGENTS.md (6513 bytes).
- **[kpollz/daily_papers_tool](https://github.com/kpollz/daily_papers_tool)** — arXiv source-archive figure extractor; `summary_utils/extract_figure.py` uses bare extractall on user-supplied archives. Critical severity; self-audit by project author. References Python 3.12 deprecation. AGENTS.md (23367 bytes).
- **[iAmGiG/FFmpeg-AutoToolkit](https://github.com/iAmGiG/FFmpeg-AutoToolkit)** — cross-platform FFmpeg auto-installer; `ffmpeg_manager.py:91-92` extracts internet-downloaded archives. HIGH severity. References **CVE-2007-4559** (the canonical Python tarfile CVE) explicitly. Provides both Python 3.12+ filter recipe and pre-3.12 manual safe_extract recipe — methodologically thorough.

Three different defect surfaces (MLOps execution host / paper-processing pipeline host / desktop-utility user system), three different trust-boundary contexts (artifact store / paper-author-supplied source tarball / mirror MITM), three different audit framings (batch-audit by automated service / self-audit / self-audit with canonical-CVE reference).

Supplementary references:

- **PyCQA/bandit itself** — the **bandit project's own example file** `examples/tarfile_extractall.py` was caught by the 2026-03-16 batch audit. Bandit's example is intentionally a B202 violation (the file demonstrates what B202 catches) — but it's a small irony that the canonical Python security-linter's own example file got flagged.
- **alephdata/memorious** — `memorious/operations/extract.py` in a web-scraping toolkit. Adjacent specimen; same batch-audit shape.
- **crate/crate-python** — `src/crate/testing/layer.py`. Adjacent specimen; same batch-audit shape.

Bandit has rule **B202** (`tarfile_unsafe_members`). Python 3.12 added `tarfile.data_filter` (PEP 706); Python 3.12+ emits a DeprecationWarning for `extractall()` without a filter; Python 3.14+ is scheduled to make it an error. Wide community recognition; the AI-amplified observation is that AI-generated code continues to produce the pre-filter form despite the deprecation roadmap.

## Detection cues

What to look for in a diff or completion:

- **`tar.extractall(path)` or `tarfile.open(...).extractall(path)` without a `filter=` argument.** The most direct signal. Python 3.12+ should always use `filter='data'`; pre-3.12 should use a manual safe_extract wrapper.
- **`zipfile.ZipFile(path).extractall(dest)`** — same defect class for ZIP archives. Python 3.12 also added a filter mechanism for zipfile (though less commonly used). Path traversal applies equally.
- **Archive-extracting code in artifact-store, paper-processing, model-registry, or dataset-fetching contexts.** These are the AI-typical surfaces where untrusted archives flow.
- **Auto-installer / package-manager code that downloads tarballs from a URL.** The download URL is the trust boundary; a compromised mirror / MITM allows malicious archives.
- **Functions whose archive input comes from user upload, third-party API, or external storage.** The trust boundary is *whoever can produce an archive that ends up in this function* — verify by tracing the data flow to the function's archive parameter.
- **`# noqa: B202` annotations.** Bandit suppression for the rule. If the suppression has no justifying comment, the lint rule has been silenced without addressing the underlying defect.

The diagnostic question for any archive-extraction call: *who can supply the archive, and what does an attacker-controlled member path look like?* If the answer to "who" is anything other than "code I trust completely," the filter is required.

Bandit `B202` catches the pattern mechanically. Python 3.12+ also produces a runtime `DeprecationWarning` — if the test suite captures warnings, the defect surfaces automatically.

## Notes

**Category `security`.** Second entry in the `security` category (joining [`string-built-sql`](string-built-sql.md)). Both are CVE-class defects with widely-adopted lint rules (Bandit B202, B608) that AI-generated code reproduces despite ecosystem recognition.

**Difficulty rated `low`.** Spotting `extractall(...)` without `filter=` is visually trivial. Bandit B202 catches it mechanically. Python 3.12+ DeprecationWarning surfaces it at runtime. The reason this is in the taxonomy is *AI-amplification dimensions* (post-3.12 codebases still produce the pre-3.12 form) and *defect surface* (archive-extraction contexts in AI tooling).

**The pattern is AI-amplified, not AI-exclusive.** Restated: every Python developer who has worked with tarfile has written a bare `extractall(path)` at some point. CVE-2007-4559 has been open for nearly 20 years. The AI-amplified differential rests on initial-state authorship after Python 3.12 (the corpus-dominant pre-3.12 form persists), codified-guidance-insufficient at multiple layers (Bandit + Python deprecation + CVE documentation), and trust-boundary-drift in AI-tooling contexts.

**False-positive shapes.** Be cautious before flagging:

- *Genuinely-trusted archives.* Internal-only build pipelines, CI artifacts produced by your own infrastructure with cryptographic verification, archives whose contents have been pre-vetted. If the archive's provenance is internally controlled and verified, the filter is belt-and-suspenders rather than required. The cue is whether the archive could *ever* be produced by an external party.
- *Python < 3.12 codebases where the filter argument isn't available.* The pre-3.12 form requires a manual safe_extract wrapper. The AI-typical form is the bare extractall regardless of Python version — but the cure differs.
- *Test fixtures or scripts that extract known-content archives.* `extractall(test_dir)` in a unit test where the archive is checked into the repo is fine.
- *Migration code with documented version constraint.* If the project explicitly targets pre-3.12 and the bare form is wrapped in a documented manual safe_extract, the absence of `filter='data'` is by design.

**Mutation operator hint.** A deterministic mutation that introduces the pattern from clean code:

- Take `tar.extractall(dest, filter='data')` and remove the filter argument
- Take a `safe_extract(tar, dest)` call and replace with `tar.extractall(dest)`
- Take a `zipfile.ZipFile.extractall(dest, members=safe_members)` and remove the members argument
- Wrap a bare extractall in `# noqa: B202` without justification

These compose with [`swallowed-exceptions`](swallowed-exceptions.md) — a bare extractall inside `try: ...; except Exception: pass` silently absorbs path-traversal errors that would otherwise surface, allowing the attack to succeed silently. Also composes with [`hardcoded-config-values`](hardcoded-config-values.md) when the archive source URL is hardcoded (no way to verify integrity at fetch time).

**Connection to [`codified-guidance-is-insufficient`](../notes/codified-guidance-is-insufficient.md) note.** Bandit B202 + Python 3.12 DeprecationWarning + CVE-2007-4559 + Python documentation guidance — all are codified, well-known, and widely-cited. AI-generated codebases reproduce the pre-filter form despite all four layers of codified guidance. The 2026-03-16 batch audit catching the bandit project's own example file is the comedic-but-real instance of codified-guidance-insufficient (the canonical lint-rule project's own example demonstrates the lint-rule violation).

**Connection to deployment-context-blind defects cluster.** This entry joins [`missing-network-timeout`](missing-network-timeout.md), [`assert-for-runtime-validation`](assert-for-runtime-validation.md), [`resource-leak-no-context-manager`](resource-leak-no-context-manager.md), [`async-await-mismatch`](async-await-mismatch.md), [`print-instead-of-logging`](print-instead-of-logging.md), [`f-string-in-logger-call`](f-string-in-logger-call.md), and [`string-built-sql`](string-built-sql.md) in the cluster of patterns whose defect surfaces only in production-deployment contexts. Here the deployment-context is *receives-untrusted-archives* — which AI tooling routinely does (model registries, paper extractors, dataset fetchers).

**Connection to trust-boundary-shift methodological observation.** The kpollz specimen's framing — *"Dataset registries tend to grow over time, and the trust boundary moves"* (a phrase from the asi-build specimen for shell=True) — applies here at the archive-source layer. A codebase that today extracts archives only from a trusted internal store may tomorrow extract from a community registry. The bare extractall doesn't survive the trust-boundary shift; the filter form does. This is methodologically important for evaluating *latent* security defects in AI-generated code — the question isn't only "is the code safe today" but "does it survive normal evolution of the trust boundary."
