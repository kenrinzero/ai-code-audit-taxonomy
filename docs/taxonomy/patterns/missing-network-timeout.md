---
name: missing-network-timeout
category: reliability
difficulty: low
generation: evergreen
since_model: null
evidence_grade: observed
---

# Missing Network Timeout

## Code example

```python
import requests

def fetch_user_profile(user_id: str) -> dict:
    """Return the profile JSON for a given user."""
    response = requests.get(f"https://api.example.com/users/{user_id}")
    response.raise_for_status()
    return response.json()
```

The function works correctly when the API responds promptly. When the API hangs — slow upstream, dead connection, half-closed socket, mid-deployment outage — the call blocks the calling thread *indefinitely*. `requests.get` defaults `timeout=None`, which means "wait forever." The process holds open one TCP connection per stuck request, holds a thread, and accumulates back-pressure until the OS or a downstream timeout (load balancer, Kubernetes liveness probe, supervising process) kills the worker.

The tightened version provides explicit timeout(s):

```python
import requests

CONNECT_TIMEOUT = 5     # seconds
READ_TIMEOUT = 30       # seconds

def fetch_user_profile(user_id: str) -> dict:
    """Return the profile JSON for a given user."""
    response = requests.get(
        f"https://api.example.com/users/{user_id}",
        timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
    )
    response.raise_for_status()
    return response.json()
```

`requests.get` accepts either a single `timeout=N` (applied to both connect and read phases) or a `(connect, read)` tuple. The tuple form is more precise: connect failures should fail fast (the remote either accepts the TCP handshake or doesn't), while read failures need more budget (the remote may legitimately take many seconds to respond).

The pattern generalizes beyond `requests`. The same shape — *missing timeout on a blocking call to an external system* — appears with `urllib`, `httpx` (synchronous mode), `subprocess.run`, async HTTP clients without per-request timeouts, database connection pools, and Redis/HTTP poll loops. All blocking primitives that accept a `timeout=` parameter can suffer from this defect when the parameter is omitted.

The pattern has several visible sub-shapes in captured specimens:

- **Clustered `requests.get` calls in a server module** — every download/fetch site in an MCP/RPC server omits `timeout=`. Captured in MiniMax-AI/MiniMax-MCP#64 (6 instances of `requests.get` in MCP `server.py`).
- **`subprocess.run` without `timeout=` in agent-tool code** — 4 `subprocess.run` calls in an agent's GitHub-CLI integration tool block indefinitely if the `gh` CLI hangs. The same project's `shell.py` and `http_request.py` correctly use timeouts elsewhere. Captured in NorthlandPositronics/Cogtrix#972; same-project-knows-right-pattern at the timeout-on-blocking-primitive layer.
- **`requests.*` calls in a developer CLI** — partial fix in one path, missed sites in another. Captured in dagster-io/dagster#33747 (3 `requests.*` calls in `dagster-dg-cli` with AST-scan reproduction).
- **Wide-codebase missing-timeout across N call sites** — large established codebase with many call sites lacking `timeout=`. Adjacent reference: internetarchive/openlibrary#12704 (~25 callsites; AI-authorship of the underlying code uncertain due to codebase age).

All sub-shapes share the same root mechanism: the model produced a blocking call to an external system and omitted the timeout parameter that would prevent indefinite hangs.

## Mechanism

A language model generates each network/subprocess/IO call in a local context. The training corpus's treatment of `requests.get` and similar primitives is heavily skewed toward minimal forms:

- **Tutorial code** — `import requests; response = requests.get(url)` is the canonical "how to make an HTTP request in Python" example. Tutorials omit `timeout=` because the parameter distracts from the lesson.
- **Stack Overflow answers** — questions of the form "how do I download X with Python?" have answers that omit `timeout=` for the same pedagogical reason.
- **Library README examples** — quick-start examples in `requests`, `urllib`, `httpx`, etc. typically show the minimal form first.
- **One-off scripts and REPL examples** — when the user is just trying things out, hanging is acceptable because the user can `Ctrl-C`.

What the corpus contains less of, per-token, is the **production-grade form**:

- `requests.get(url, timeout=30)` or `timeout=(5, 30)` — explicit timeout
- Wrapped with a custom transport adapter that injects a default timeout — a subclassed `requests.adapters.HTTPAdapter` whose `send()` supplies `timeout=` when the caller omits it. (Note: a plain `session.timeout = 30` on a `requests.Session` is silently ignored — `Session` has no honored `timeout` attribute — so it is *not* a valid way to set a default.)
- With error handling for the timeout exception: `try: ...; except requests.Timeout: ...`
- Retry-with-backoff using `urllib3.util.retry.Retry` or `tenacity`

The model has seen all of these forms but the *frequency-weighted prior* favors the tutorial-minimal form. When the model generates an HTTP call in production code, the local-attention generation step produces `requests.get(url)` — the form that fits most surrounding tutorial-like context — rather than the production-hardened form.

This is a direct instance of the **AI-pedagogical-bias** mechanism (see [`ai-pedagogical-bias`](../notes/ai-pedagogical-bias.md)): the model defaults to patterns appropriate for tutorial/example code (no timeout — hanging is acceptable in a script) when the deployment context calls for the production alternative (explicit timeout — hanging is a denial-of-service).

The defect paths are real and varied:

1. **Process-level indefinite hang.** Single-threaded CLI tools (Dagster's `dagster-dg-cli`) freeze on slow endpoints. The user must `Ctrl-C` and retry; no progress signal.
2. **Worker-pool starvation.** Web servers with thread pools (FastAPI sync routes, gunicorn workers) exhaust pool capacity as stuck calls accumulate. New requests queue or fail. Cross-links to [`sleep-based-synchronization`](sleep-based-synchronization.md) where `time.sleep` in async-aware code starves AnyIO thread pools.
3. **MCP/RPC protocol stall.** MCP servers (MiniMax-MCP captures this directly) cannot return tool-call responses while a downstream HTTP request hangs. The AI agent on the other side cannot get a timeout signal; the agent's turn stalls indefinitely.
4. **Cascading deployment failures.** Health probes timeout on stuck workers; orchestrators (Kubernetes, ECS) kill and restart pods; restart loops compound back-pressure on the upstream that triggered the hang.
5. **Resource leak compounding.** Each stuck call holds a TCP connection, possibly a database transaction, possibly a file handle. Long-tail timeouts at the OS level (default 2-hour TCP keepalive) leave connections hanging well after the application gives up.

Three concrete failure paths are visible in the captured specimens:

**Path 1: Clustered missing-timeouts in a single-responsibility server module.** MiniMax-MCP's `server.py` has 6 `requests.get` calls — every media-download site omits `timeout=`. The model generated each download site in turn, each time producing the tutorial-minimal form. The sticky-local-pattern observation from other entries applies at the HTTP-primitive layer.

**Path 2: Same-primitive-different-modules drift.** Cogtrix's `github_tools.py` has 4 `subprocess.run` without `timeout=` while sibling modules `shell.py` and `http_request.py` correctly use timeout protection. The model's prior at one module's generation context favored the timeout-protected form; the prior at the GitHub-tools module favored the unprotected form. This is the **same-project-knows-right-pattern** mechanism at the per-module level.

**Path 3: Half-completed-propagation of a prior fix.** Dagster's prior PR #17831 added timeouts to schedule/sensor code paths but did not propagate the fix to the developer-CLI code path. The 3 instances in `dagster-dg-cli` are exactly the sites the prior fix did not reach. The audit author includes an AST-scan reproducer that mechanically detects the pattern — a sign of calibrated reviewer practice.

The training corpus reinforces the failure mode in one additional way: **timeout values are deployment-specific**, and the model has no way to know the right value from the local code context alone. "Should this be 5 seconds or 5 minutes?" depends on what the API does, how the user expects to wait, what the SLA is. The model often produces *no timeout at all* rather than producing a *wrong timeout*. The absence is the form the model defaults to when uncertainty would otherwise force a choice.

This pattern is the **reliability-primitive cousin of [`sleep-based-synchronization`](sleep-based-synchronization.md)**. Both stem from the model's tutorial-corpus inheritance: sleep-based-synchronization replaces a proper synchronization primitive with a sleep (the corpus-fluent shortcut); missing-network-timeout omits a defensive parameter (the corpus-fluent omission). Both are pedagogical-bias-driven mechanisms applied at adjacent surfaces.

The pattern is **AI-amplified, not AI-exclusive**. Human Python programmers omit timeouts constantly — particularly in scripts, particularly under deadline, particularly when the API is "internal" and "we control it." The AI-amplified observation rests on three differential dimensions:

1. **Initial-state authorship in production-deployment-context code**: AI-generated MCP servers, agent tools, and CLI utilities — code that *will be deployed* — produce the pattern from the first commit. Captured specimens are all in deployment-context-sensitive code paths.
2. **Clustering**: 6 instances in one server module (MiniMax-MCP) is sticky-local-pattern density; humans tend to vary their attention across sites.
3. **Same-primitive-different-module drift**: the project knows the right pattern at one site (Cogtrix shell.py) and produces the wrong pattern at another (Cogtrix github_tools.py). Per-call-site / per-module generation evidence.

## Evidence / incident

Three captured specimens, each from a different AI-coded Python project, each demonstrating a different sub-shape. Detailed specimen notes are not included in the public repository.

- **[MiniMax-AI/MiniMax-MCP#64](https://github.com/MiniMax-AI/MiniMax-MCP/issues/64)** — clustered `requests.get` in MCP server. Six instances of `requests.get(url)` in `server.py` (voice clone, audio playback, video generation, image download) without `timeout=`. MiniMax-MCP is the **official MiniMax MCP server** (1476+ stars, MiniMax-AI organization). MCP server hangs the AI agent's tool pipeline. Contributor "Xuner AI" suggests AI signature in recent commits.
- **[NorthlandPositronics/Cogtrix#972](https://github.com/NorthlandPositronics/Cogtrix/issues/972)** — `subprocess.run` variant with same-project-knows-right-pattern shape. Four `subprocess.run` calls in `tools/github_tools.py` lack `timeout=`. The same project's `tools/shell.py` *has* timeout protection and `tools/http_request.py` clamps HTTP timeouts to 1–120s. Bot-authored audit (`is_bot: true`). Project contributors named after Futurama characters ("Turanga Leela", "Ami Wong"). Issue body explicitly compares the correct-pattern sites to the drifting site.
- **[dagster-io/dagster#33747](https://github.com/dagster-io/dagster/issues/33747)** — `requests.*` calls in developer CLI with AST-scan reproducer. Three sites in `dagster-dg-cli` omit `timeout=`. Audit author distilled the pattern into a reproducible AST check — methodologically reusable. Reference to prior partial-fix #17831 (timeouts added to schedule/sensor paths but not propagated to developer-CLI).

Three different libraries (`requests` / `subprocess` / `requests`), three different scales (6 / 4 / 3), three different defect surfaces (MCP server hang / agent tool call hang / CLI hang), three different audit framings (project bug report / bot-authored audit / contributor-driven AST-scan with prior-fix reference). Cross-axis variance is broad.

Supplementary references:

- **[internetarchive/openlibrary#12704](https://github.com/internetarchive/openlibrary/issues/12704)** — ~25 callsites of `requests.{get,post,put,patch,delete}` missing `timeout=` across openlibrary. Massive scale but the openlibrary codebase is decade-old; AI-authorship of the underlying code is uncertain. Captured as adjacent reference for the scale-evidence dimension; the audit framing ("blocking workers indefinitely") matches the defect path documented in this entry.
- **[KuechlerO/simple_baserow_api](https://github.com/KuechlerO/simple_baserow_api)** — "Missing timeout parameter on all HTTP requests" (2026-03-19) — scope-comprehensive sweep on a young codebase.
- **[fossasia/eventyay](https://github.com/fossasia/eventyay)** — "Webhook HTTP Request Missing Timeout and Inconsistent Error Logging" (2026-04-26) — webhook-specific shape combined with inconsistent error logging (cross-link to [`inconsistent-error-handling`](inconsistent-error-handling.md)).
- **[microsoft/agent-framework#5741](https://github.com/microsoft/agent-framework/issues/5741)** — synchronous tool execution including missing-timeout patterns; framework-level integration with the agent ecosystem. Adjacent specimen mentioned in [`sleep-based-synchronization`](sleep-based-synchronization.md) supplementary references.
- **Bandit lint rule B113 and Ruff equivalent** exist precisely to catch this pattern (`requests` calls without `timeout=`). Wide community adoption; the AI-amplified observation is that the rule fires at unusual density on AI-generated code, paralleling the ruff PLC0415 observation in [`unjustified-lazy-import`](unjustified-lazy-import.md) and ruff G004 in [`f-string-in-logger-call`](f-string-in-logger-call.md).

## Detection cues

What to look for in a diff or completion:

- **`requests.get(url)` / `requests.post(url, ...)` / any `requests.<method>(...)` without `timeout=` kwarg.** The most direct signal. Particularly suspect when the call is in a server, agent tool, MCP server, or any long-running context where indefinite hangs are unacceptable.
- **`subprocess.run(cmd, ...)` / `subprocess.Popen(cmd, ...)` without `timeout=`.** Same root mechanism applied to the subprocess primitive. Particularly suspect when `cmd` is anything that could block (CLI tools, scripts, anything making network requests itself).
- **`urllib.request.urlopen(url)` without `timeout=`.** The lower-level stdlib HTTP primitive; same trap.
- **`httpx.get(url)` (synchronous mode) without `timeout=`.** Modern Python HTTP client with same primitive surface.
- **Async HTTP calls without per-request timeout context.** `aiohttp` requires explicit `ClientTimeout`; `httpx` async has its own timeout model. Missing-timeout in async code is less likely to hang a thread pool but can still leak connections.
- **A `wait_for_X` helper / polling loop that calls an external API in the loop body without per-call timeout.** The loop's bounded-iteration provides some protection, but individual API calls can still hang for the entire loop duration.
- **Same project knows the right pattern at one site and the wrong pattern at another.** The Cogtrix shape: grep for `timeout=` matches in the project; find sites that should have timeouts but don't.
- **An audit/PR that adds timeouts to *some* sites but not *all* of them.** The Dagster shape: the prior fix didn't propagate to all call sites. New fix opportunities are sibling-files that the prior fix didn't reach.

The diagnostic question for any HTTP/subprocess/blocking call: *what happens if this primitive hangs? Is there a higher-level timeout that would eventually kill it?* If the answer is "the calling thread hangs until the OS or load balancer kills it," the timeout is missing. If the answer is "I rely on the framework's deployment timeout (gunicorn worker timeout, Kubernetes liveness probe)," check whether that timeout is configured shorter than the longest plausible legitimate operation.

Bandit `B113`, Ruff equivalent rule, and similar lint configurations catch the most common form (`requests.<method>` without `timeout=`) mechanically. Adding these to CI is the structural cure; documentation alone is observably insufficient (the IBM specimen in [`f-string-in-logger-call`](f-string-in-logger-call.md) and the Cogtrix same-project-knows-right-pattern shape both demonstrate this).

## Notes

**Category `reliability`.** The category captures patterns about *whether the program can be expected to run reliably under realistic deployment conditions*.

**Difficulty rated `low`.** The visual cue is unambiguous — `timeout=` either appears in a kwarg list or doesn't. A grep finds every missing-timeout site mechanically. The reason this is in the taxonomy is *density and form* (AI-generated code produces missing timeouts across deployment-context-sensitive sites at notable frequencies), not difficulty.

**The pattern is AI-amplified, not AI-exclusive.** Human Python programmers omit timeouts constantly — particularly in scripts, particularly under deadline. The AI-amplified differential rests on initial-state authorship in production-deployment-context code, clustering, and same-primitive-different-module drift.

**False-positive shapes.** Be cautious before flagging:

- *Truly unbounded operations.* Some operations are *meant* to wait forever — `socket.accept()` on a listening server socket, `select.select()` with no timeout for an event-loop entry point. Different mechanism; the lack of timeout is part of the contract.
- *Operations with framework-level timeouts.* If the function is decorated with `@timeout(30)` or is called inside a context with implicit timeout (a Celery task with `time_limit`, a Django request with the deployment-level timeout), the lack of an explicit primitive-level timeout may be acceptable. The cue is whether the framework's timeout is shorter than the worst-case primitive hang.
- *Test code that intentionally drives slow paths.* Some tests deliberately wait for slow responses; explicit timeouts would mask the test's intent. Test code usually has `@pytest.mark.slow` or similar to signal this.
- *Streaming/large-download operations.* `requests.get(url, stream=True)` may legitimately accept long reads. The cue is whether there's per-chunk timeout or some kind of progress check inside the stream loop.
- *Backoff retry loops with bounded retries.* Some code intentionally lets each individual request take its time, but caps the total retries. The aggregate timeout is bounded even if each call's primitive timeout is not.

**Mutation operator hint.** A deterministic mutation that takes a clean function with explicit timeout and removes it produces this pattern from clean code. Variants:

- Take `requests.get(url, timeout=30)` and replace with `requests.get(url)`
- Take `subprocess.run(cmd, timeout=60)` and replace with `subprocess.run(cmd)`
- Take a `(connect, read)` tuple timeout and replace with a missing parameter
- Take a Session with a default timeout and remove the timeout default
- Add a new HTTP call to a service file and omit the timeout (the most common AI-generated form)

These compose with [`sleep-based-synchronization`](sleep-based-synchronization.md) — a polling loop calling an external API with no per-call timeout is the maximally defective concurrent shape. Also composes with [`swallowed-exceptions`](swallowed-exceptions.md) — a missing-timeout call wrapped in `except Exception: pass` produces a silent indefinite hang that may eventually surface as a worker-pool starvation; logs show nothing, metrics show nothing, only the dropped throughput reveals the defect.

**Connection to [`ai-pedagogical-bias`](../notes/ai-pedagogical-bias.md) note.** This entry is one of six members of the AI-pedagogical-bias meta-family: the model treats production code as if it were tutorial code, producing the tutorial-minimal HTTP/subprocess form rather than the production-hardened form. The family now spans `narrating-comments`, `print-instead-of-logging`, `hardcoded-config-values`, `missing-network-timeout`, `f-string-in-logger-call`, and `assert-for-runtime-validation`.

**Connection to [`same-project-knows-right-pattern`](../notes/same-project-knows-right-pattern.md) note.** The Cogtrix specimen contributes another instance of this observation: `shell.py` and `http_request.py` know the right pattern; `github_tools.py` drifts. Per-module drift within a single codebase, surfaced by per-module attention context.

**Connection to [`partial-fix-propagation`](../notes/partial-fix-propagation.md) note.** The Dagster specimen is one of the three founding specimens for this note: prior PR #17831 added timeouts to schedule/sensor code paths, but the developer-CLI sub-tree (`dagster-dg-cli`) was not in scope; 3 `requests.*` sites were later surfaced by an AST-scan reproducer in #33747. The fix's boundary became a new drift boundary.

**MCP-server context as a recurring sub-shape.** Three of the taxonomy's entries now have MCP-server-specific defect surfaces: [`print-instead-of-logging`](print-instead-of-logging.md) (print() corrupts stdout transport), [`wrong-tool-for-job`](wrong-tool-for-job.md) (shell-embedded Python in MCP skills), and this entry (missing timeouts hang the agent tool pipeline). As MCP adoption expands, MCP-server-specific patterns may merit their own consolidated note.
