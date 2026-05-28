---
name: async-await-mismatch
category: async
difficulty: medium
generation: evergreen
since_model: null
evidence_grade: observed
---

# Async-Await Mismatch

## Code example

```python
class Tool:
    async def set_progress(self, content: str | None) -> None:
        ...

class CodeExecutionTool(Tool):
    async def execute(self, ...) -> ToolResult:
        ...
        self.set_progress(truncated_output)        # missing await — coroutine never runs
        ...
```

The call site is inside an `async def` method where `await` is available. The callee is correctly declared `async`. The caller omits `await`. The return value of `self.set_progress(truncated_output)` is a *coroutine object* — the deferred computation an `async def` function gives back when called, which must be awaited to actually run — not the side effect the developer intended. Python emits `RuntimeWarning: coroutine 'Tool.set_progress' was never awaited` to logs; the progress update silently never happens.

The fix is one keyword:

```python
await self.set_progress(truncated_output)
```

The *dual* shape is also AI-typical — declaring functions `async def` that don't need to be async:

```python
# defective: declared async but contains no await
async def handle_join(self, msg: JoinMessage) -> None:
    self._connected_users.add(msg.user)
    self._broadcast_join(msg.user, msg.channel)
    # no await anywhere in the body
```

Both shapes are surface forms of the same mismatch: the model produces `async` and `await` keywords without consistently tracking which functions are coroutines and where awaits belong.

The pattern has several visible sub-shapes in captured specimens:

- **Missing await on coroutine call** (most defect-direct). The callee is correctly declared async; the caller forgets `await`. The coroutine is silently created and discarded. Symptom: `RuntimeWarning: coroutine '<name>' was never awaited` repeating in logs; user-visible behavior is silent stall or empty result. Captured in agent0ai/agent-zero#1543 (progress updates dropped, agent appears frozen in WebUI) and carpenike/coachiq#164 (SecurityWebSocketHandler stats + recent-events broken).
- **Unnecessary async on sync handler** (stylistic). The function is declared `async def` but has no await inside. Callers are forced to await; tests must use async fixtures. SonarCloud `S7503` / Ruff `RUF029` catch this mechanically. Captured in agentculture/culture#83 (51 occurrences across 4+ files).
- **Mixed missing-await + downstream-typed-attribute mismatch** (compound defect). The carpenike/coachiq#164 specimen documents this: missing `await` on `get_statistics()` leaves a coroutine object; adding the `await` exposes a *second* latent bug — the callee returns a Pydantic v2 model where the caller does `.get("performance", {})` as if it were a dict. Fixing the await reveals the model-vs-dict mismatch that the missing-await accidentally masked.
- **Partial-fix-propagation** (audit-scope drift). The coachiq specimen explicitly notes the bug was discovered during PR A6 (the v1→v2 cutover) but scoped out of A6 and deferred. The right pattern was applied at the sites A6 touched; the wrong pattern remains at sibling sites.

All sub-shapes share the same root mechanism: the model produces `async`/`await` keywords without consistently tracking which functions are coroutines and at which call sites the awaits belong.

## Mechanism

A language model generates each function definition and each function call in its own local attention context. The async/await contract requires *correspondence* between the two:

- A function declared `async def` returns a coroutine when called; the call site must `await` it (or `asyncio.create_task` / `asyncio.gather`).
- A function declared `def` returns its value directly; the call site must *not* `await` it.

This correspondence is enforced at runtime (calling an async function without await produces a warning; using await on a non-async value raises `TypeError`). What is *not* enforced at generation time is that the model has tracked which functions in scope are async. The model's local-attention prior at any given call site is shaped by:

- The immediate surrounding tokens (recently-seen function definitions, recently-seen async-await patterns)
- The model's general prior about whether a function with a given name is likely async (e.g., `fetch_*`, `get_*`, `send_*` lean async; `compute_*`, `parse_*`, `validate_*` lean sync — but neither is strict)
- Whether the caller is itself in an `async def` body (which biases the model toward producing `await`, but unreliably)

When the model produces a call site, the prior decides whether to emit `await`. If the callee is async and the prior favors await, the call site is correct. If the callee is async but the prior favors no-await (because the function name doesn't read as async, or the surrounding context recently produced sync calls), the call site is wrong — coroutine never runs.

The **dual sub-shape** (unnecessary-async-def) has the inverse mechanism. The model produces `async def` for a function whose body contains no await because:

- The function is a *dispatch target* in a pattern where the dispatcher uniformly awaits handlers (per agentculture's `await handler(msg)` pattern), so each handler is declared async to fit the dispatcher's contract
- The function name leans async (`handle_*`, `process_*`, `serve_*`) and the model defaults to the async signature
- The surrounding code is heavily async, and the model's local-attention prior favors `async def` over `def`

The model produces 51 unnecessary asyncs in agentculture/culture because the dispatcher's `await handler(msg)` pull cascades through every handler implementation. The dispatcher's choice forced the handlers' choice; the model never went back and verified each handler actually needed the async keyword.

There is also a corpus-bias contribution: the AI-tutorial corpus has *grown* the proportion of async code substantially as Python's async ecosystem matured (FastAPI, asyncio, aiohttp, trio). The model's prior is biased toward async by exposure. In codebases that mix sync and async legitimately, the model tends to produce more async than the code needs, which then drives unnecessary-async-def shapes.

Three concrete failure paths are visible in the captured specimens:

**Path 1: Defect-direct missing-await with broad-except masking.** agent-zero's `code_execution_tool.py` has two sites of `self.set_progress(truncated_output)` (lines 259, 371) where the callee is async but `await` is missing. The coroutine is silently discarded. `RuntimeWarning` appears in logs but is invisible in the WebUI. *Agent appears stalled* — symptom is indistinguishable from a network or LLM-timeout failure. The defect is particularly costly in agentic systems because the user has no other signal that the agent is alive.

**Path 2: Partial-fix-propagation with compound downstream defect.** coachiq's `security_handler.py:208, 265-266` and `security_dashboard.py:120-121` have missing-await on `get_recent_events`, `get_statistics`, `get_event_stats`. Adding the await exposes a second latent defect — the callees return Pydantic v2 models but the callers do dict-style `.get("performance", {})` access. The missing-await accidentally *masked* the model-vs-dict mismatch (because the broad `except` swallowed the TypeError from list-comprehension-on-coroutine before the dict-access mismatch could fire). Fixing the await unmasks the second bug. The structured audit framework ("A1-A10 audit cycles") explicitly notes this is deferred work; PR A6 didn't reach this scope.

**Path 3: Dispatcher-pulls-unnecessary-async at codebase scale.** agentculture/culture has 51 occurrences of `async def` on handlers that don't need it, across `culture/server/server_link.py`, `culture/clients/*/daemon.py`, `culture/bots/http_listener.py`, and `packages/agent-harness/daemon.py`. The dispatcher pattern (`await handler(msg)`) forces each handler to be async; the audit recommends checking `if asyncio.iscoroutine(result): await result` at the dispatcher and removing async from the handlers that don't need it. The mechanism is the dispatcher's contract pulling unnecessary-async through every handler.

This pattern is **AI-amplified, not AI-exclusive**. Human Python programmers also produce missing-awaits and unnecessary-asyncs, particularly when migrating sync code to async or when working in unfamiliar async libraries. The AI-amplified differential rests on:

1. **Initial-state authorship density**: AI-generated codebases produce 51-occurrence unnecessary-async at initial commit; humans produce drift over time.
2. **Dispatcher-cascade shape**: AI-generated dispatcher patterns force unnecessary-async at every handler call site (agentculture: 51 handlers async-declared because dispatcher awaits).
3. **Coroutine-never-run silent failures**: AI-generated agent systems produce stuck/frozen-agent symptoms (agent-zero) because the missing-await is masked by broad-except patterns that themselves are AI-typical (cross-links to [`swallowed-exceptions`](swallowed-exceptions.md)).
4. **Same-template clustering**: both sub-shapes show same-template clustering — 2 sites in agent-zero, 4 sites in coachiq, 51 sites in agentculture all reproduce the same wrong template within one codebase.

## Evidence / incident

Three captured specimens covering both sub-shapes (missing-await and unnecessary-async) and different scales. Detailed specimen notes are not included in the public repository.

- **[agent0ai/agent-zero#1543](https://github.com/agent0ai/agent-zero/issues/1543)** — missing-await sub-shape, defect-direct. `self.set_progress(truncated_output)` at two sites in `code_execution_tool.py:259, 371` — coroutine never awaited. Agent appears stalled/frozen in WebUI; user cannot distinguish from network/LLM timeout. AGENTS.md (11633 bytes), explicit "Full-Stack Agentic Framework."
- **[carpenike/coachiq#164](https://github.com/carpenike/coachiq/issues/164)** — missing-await with compound downstream mismatch. `get_recent_events`, `get_statistics`, `get_event_stats` called without await in `security_handler.py`; same shape in `security_dashboard.py:120-121`. Fixing the await unmasks a Pydantic-model-vs-dict-access mismatch. Discovered during PR A6 (v1→v2 cutover) but scoped out; structured "A1-A10 audit cycle" with ADR references.
- **[agentculture/culture#83](https://github.com/agentculture/culture/issues/83)** — unnecessary-async sub-shape at codebase scale. **51 occurrences** of `async def` on sync handlers across 4+ files. Dispatcher's `await handler(msg)` pattern forces each handler to be async. CLAUDE.md (7326 bytes); "A mesh of IRC servers where AI agents collaborate." Audit signed `- Claude` at the bottom of the issue body — Claude-generated audit on Claude-coded project.

Three different sub-shapes / scales / audit framings: defect-direct user-stall (agent-zero, 2 sites) / structured audit cycle (coachiq, 4 sites + downstream) / codebase-scale dispatcher-cascade (agentculture, 51 sites).

Supplementary references:

- **[infiniflow/ragflow](https://github.com/infiniflow/ragflow)** — "GraphRAG calls async `Dealer.get_vector()` without await, causing empty entities/relations" (2026-05-08). Same missing-await shape in an AI-RAG project; defect-direct (empty graph entities).
- **[NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)** — "/reload-mcp confirmation prompt is broken — async coroutine never awaited" (2026-05-09). Hermes-agent has contributed specimens to 5+ other entries; not captured here to avoid same-codebase concentration but worth noting as cross-link evidence.
- **[basis-protocol/basis-hub](https://github.com/basis-protocol/basis-hub)** — "main.py:296 calls async `run_agent_cycle()` without await — silent failure, blocks `assessments` attestation" (2026-05-13). Same missing-await shape; silent-failure surface.
- **[traceloop/openllmetry](https://github.com/traceloop/openllmetry)** — `RuntimeWarning: coroutine 'Request.json' was never awaited` when `@workflow` decorates an async FastAPI endpoint receiving a `Request` parameter (2026-04-09). A *framework-level* missing-await — the decorator drops the await.

Ruff has rule **RUF029** (`useless-async`); SonarCloud has **S7503** (`Functions declared async but never use await`); Python's runtime warns `RuntimeWarning: coroutine '...' was never awaited` for the missing-await case. Three independent community-recognized rules covering the dual sub-shapes; widespread adoption confirms the pattern is recognized as a defect class.

## Detection cues

What to look for in a diff or completion:

- **`<async_fn>(...)` without `await`** in an `async def` body. The most direct missing-await signal. Particularly suspect when the function name leans async (`fetch_*`, `get_*`, `send_*`, `update_*`).
- **`RuntimeWarning: coroutine '...' was never awaited`** in test output or production logs. Mechanical surface — the warning fires every time. If it's repeating in logs, find the call site.
- **`async def` with no `await` anywhere in the body.** SonarCloud S7503 / Ruff RUF029 catch this. Particularly suspect for handler/dispatch-style functions in projects that uniformly `await handler(msg)` at the dispatch site.
- **Calls to `.get()`, `.method()`, or attribute access on what looks like an *expected* dict/object but the callee returns a coroutine.** The missing-await is upstream; the visible symptom is `AttributeError: 'coroutine' object has no attribute '<method>'` or `TypeError: 'coroutine' object is not iterable`.
- **Adjacent sites in the same file where one call awaits and the next doesn't.** A nearby `await foo()` paired with a non-awaited `bar()` where both callees are async is a sticky-local-pattern miss — the model didn't propagate the await to all sites.
- **A dispatcher that uniformly awaits handlers, paired with handler implementations that don't have awaits inside.** The dispatcher's contract is forcing unnecessary-async on the handlers; consider refactoring the dispatcher to accept both sync and async (`if asyncio.iscoroutine(result): await result`).
- **A prior PR that fixed missing-awaits at *some* sites in a module.** The remaining sites in sibling modules likely still have the bug — partial-fix-propagation shape. Grep the codebase for *all* call sites of the previously-fixed function and verify each has its await.

The diagnostic question for any async-related code: *do the `async`/`await` keywords match across the call graph?* If a function is async, every call to it needs `await` (or `create_task`/`gather`). If a function is non-async, no caller should `await` it. If a function is *unnecessarily* async (no awaits in body), removing the async keyword and updating callers is the cure.

`pyright`/`mypy` strict mode catches both sub-shapes during type-checking; `pytest` produces `coroutine was never awaited` warnings at test runtime. Adding these to CI is the structural cure.

## Notes

**Category `async`.** Second entry in this category (joining [`sleep-based-synchronization`](sleep-based-synchronization.md)). Both stem from the model's async-ecosystem corpus inheritance — sleep-based-synchronization replaces proper synchronization with sleep; async-await-mismatch produces async/await keywords without consistent tracking.

**Difficulty rated `medium`.** Spotting `async def` is visually trivial; spotting *missing* `await` requires understanding the callee's signature. The runtime warning (`RuntimeWarning: coroutine '...' was never awaited`) makes detection mechanical *if* the test suite or production logs are watched. The harder case is missing-await with broad-except masking (the coachiq specimen): the swallowed exception means the warning is the only signal.

**The pattern is AI-amplified, not AI-exclusive.** Restated: every Python developer who works with async produces missing-awaits occasionally. The AI-amplified differential rests on initial-state-authorship density, dispatcher-cascade shape (51 unnecessary-asyncs in agentculture from one dispatcher contract), and silent-failure surface (the missing-await stall is invisible without log inspection).

**False-positive shapes.** Be cautious before flagging:

- *Intentional fire-and-forget with explicit handling.* `asyncio.create_task(self.set_progress(...))` is the principled way to fire-and-forget a coroutine; the task object holds a reference to prevent gc. If the call site explicitly creates a task, missing-await is intentional.
- *Calling `__await__` directly* in a custom awaitable implementation. Rare but legitimate; the cue is whether the function is decorated with `@types.coroutine` or returns an awaitable object.
- *Async generators / async iterators.* `async for x in async_iter()` is the iteration form, not `await async_iter()`. The async iter object is not awaitable; awaiting it is the bug.
- *Functions intentionally declared async to satisfy a protocol.* If an abstract-base or protocol requires `async def method()`, concrete implementations must use `async def` even when their body is sync. The cue is whether the function implements an abstract async method.
- *Coroutines passed as arguments* (e.g., to `asyncio.gather`, `asyncio.wait`). These deliberately don't await at the call site because the caller will be awaited later.

**Mutation operator hint.** A deterministic mutation that introduces the pattern from clean code:

- **Missing-await variant**: Remove `await` from a call site whose callee is `async def`. The diff is 5 characters.
- **Unnecessary-async variant**: Add `async` to a `def` whose body contains no await; update callers to `await` the call.
- **Compound variant**: Remove `await` AND change the callee's return type from `dict` to a Pydantic model with `.get()` not implemented. The downstream `.get("key")` call then crashes once the missing-await is fixed (coachiq shape).

These compose with [`swallowed-exceptions`](swallowed-exceptions.md) — a missing-await wrapped in `except Exception: pass` produces the maximally silent failure (RuntimeWarning suppressed, coroutine discarded, no visible symptom).

**Connection to [`same-project-knows-right-pattern`](../notes/same-project-knows-right-pattern.md) note.** The coachiq specimen shows adjacent files with correct awaits at some sites and missing-awaits at the SecurityWebSocketHandler-and-dashboard sites. Per-site drift within a single codebase, surfaced by per-site attention context.

**Connection to [`partial-fix-propagation`](../notes/partial-fix-propagation.md) note.** The coachiq specimen is the third of the three founding specimens for this note: PR A6 fixed missing-awaits at the v1→v2 cutover sites; the SecurityWebSocketHandler-and-dashboard sites were explicitly scoped out of A6 and deferred as separate work in #164. The deferral is documented, the residue is intentional but unaddressed, and the missing-await accidentally masks a downstream Pydantic-vs-dict mismatch that surfaces only once the await is added. The coachiq specimen's landing in 2026-05-16 brought the count to three and triggered the 2026-05-25 promotion of partial-fix-propagation from a sub-shape of same-project-knows-right-pattern into its own note.

**Connection to [`ai-pedagogical-bias`](../notes/ai-pedagogical-bias.md) note.** Async patterns are *over-represented* in modern Python tutorial corpus (FastAPI, asyncio, aiohttp). The model's default-toward-async bias is the corpus-bias surface; the resulting unnecessary-async-def at 51 sites is the AI-amplified scale.

**Connection to MCP-server-deployment-context observation.** Both the agent-zero specimen (agentic framework, code execution tool) and the coachiq specimen (WebSocket handler) surface the defect at deployment-context-sensitive boundaries where silent failures are particularly costly. The agentculture specimen is at the IRCd dispatcher boundary — same architectural surface, different protocol. The cross-cutting observation: agent-system and protocol-server boundaries are where async-await-mismatch defects bite hardest.
