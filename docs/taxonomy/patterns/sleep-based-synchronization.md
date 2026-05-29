---
name: sleep-based-synchronization
category: async
difficulty: medium
generation: evergreen
since_model: null
evidence_grade: observed
---

# Sleep-Based Synchronization

## Code example

```python
async def test_connector_routes_message_to_correct_phone() -> None:
    connector_task = asyncio.create_task(connector.run())
    try:
        await asyncio.sleep(0.5)  # hope discovery completes
        result = await harness.run_step(session_a.id)
        assert result.phone == "+15551234"
    finally:
        connector_task.cancel()
```

The test passes most of the time. On a developer's laptop, `connector.run()` populates the connector's internal state in well under 0.5s and the subsequent step runs against fully-initialized state. On a CI runner under load, `connector.run()` sometimes takes longer, the step runs against half-initialized state, and the test fails with a `KeyError` that has nothing to do with the behavior being tested.

The 0.5s sleep is doing two jobs poorly: it is *substituting for a synchronization primitive* (waiting for "connector ready") and it is *betting on a timing budget* (assuming 0.5s is always enough). Neither job is what `asyncio.sleep` is for. The right tools exist:

```python
async def _connector_ready() -> bool:
    return len(connector.state) >= 2

deadline = asyncio.get_running_loop().time() + 5.0
while not await _connector_ready():
    if asyncio.get_running_loop().time() >= deadline:
        raise AssertionError("connector state not populated within 5s")
    await asyncio.sleep(0.05)
```

The test now polls a defined readiness invariant and proceeds as soon as it is satisfied — typically in <100ms locally, up to 5s on a slow CI runner, never silently passing on a half-populated state. The right primitive is *either* an `asyncio.Event` exposed by the connector or a predicate-based poll on the readiness condition; the sleep was substituting for both because neither was exposed.

The pattern has several visible sub-shapes in captured specimens:

- **Sleep as test synchronization with timing wager** — `await asyncio.sleep(0.5)  # hope discovery completes`. The test author often acknowledges the wager in a comment ("CI loses this race; local dev usually wins it"). Captured in eumemic/aios#363.
- **Sync `time.sleep()` in async-context-aware production code** — a rate limiter, retry loop, or wait helper uses `time.sleep()`; when called from an async handler running in a thread pool, sleeping threads can starve the pool and cascade into health-check failures. Captured in tornikebolokadze1-cyber/training-agent#42.
- **Polling-loop architecture when events are available** — a `wait_for_X` helper polls a REST endpoint at 200-500ms intervals when the underlying system publishes WebSocket events for the same condition. The right tool exists (the WebSocket client is already used elsewhere in the codebase) but the poll was used here anyway. Captured in homeassistant-ai/ha-mcp#1152.
- **`time.sleep(2)` for TTL expiry in tests** — when the cache or storage layer has an API to expire entries manually, sleeping for the TTL is the wrong tool. Documented in oliverhaas/django-cachex#86 as a remaining-work item.

All sub-shapes share the same root mechanism: the model used a time-based primitive (`time.sleep`, `asyncio.sleep`, polling-with-sleep) when an event-based or condition-based primitive would have been more correct, faster, and more deterministic.

## Mechanism

A language model's prior for "how do I wait for X" is heavily shaped by the training corpus's treatment of waiting primitives. The corpus contains many examples of:

- `time.sleep(N)` in tutorial code that demonstrates "this is how you wait"
- Stack Overflow answers that recommend `time.sleep` as a quick fix for "my test is flaky, what should I do?"
- Beginner Python code that uses `time.sleep` for any wait-related need
- Polling loops as the simplest illustration of "wait until condition"

What the corpus contains less of, per-token, is the principled alternative:

- `asyncio.Event.wait()` for async code where one task signals another
- `threading.Condition` for sync code with multi-threaded waits
- `asyncio.to_thread` to offload sync blocking calls from an async event loop
- WebSocket / SSE / event-stream subscriptions instead of REST polling
- Predicate-based polling with a defined readiness invariant
- Test fixtures that expose `ready_event` or `wait_until` primitives for deterministic synchronization

The model knows about these alternatives in the abstract — it can write `asyncio.Event` code when asked directly. What it does not do reliably during a local generation step is *choose* the event-based primitive when the surrounding context already has a sleep-based pattern available. The model's local-attention bias favors the simpler-and-more-corpus-frequent primitive.

Three concrete failure paths are visible in the captured specimens:

**Path 1: Sleep-as-test-synchronization with timing wager.** The model writes `await asyncio.sleep(0.5)` before driving a test step that requires prior setup to complete. The sleep is a *timing wager*: 0.5s is enough on the developer's machine, but might not be on CI. The wager is invisible until the test runs under different timing conditions. eumemic/aios#363 captures this with the author's own comment acknowledging "CI loses this race; local dev usually wins it." This is the most common shape because it works locally and fails only under load.

**Path 2: Sync `time.sleep()` in async-context-aware code.** The model writes a rate limiter, retry loop, or wait helper using `time.sleep()`. The function is locally correct — it does sleep the right duration. The defect emerges when the function is called from an async handler context (FastAPI / aiohttp / asyncio app): `time.sleep()` is a synchronous blocking call. When called from an async handler running in a thread pool, it occupies a thread for the entire sleep duration. Under burst load, the thread pool fills with sleeping threads and other endpoints stop responding. training-agent#42 captures this with concrete arithmetic (10 stuck sends × 60s = pool starvation). The defect is invisible in isolation; it emerges from the interaction between the local code and the framework's threading model.

**Path 3: Polling-loop architecture when events exist.** The model writes a `wait_for_X` helper that polls a REST endpoint at 200-500ms intervals until the condition is satisfied. The right primitive — a WebSocket event subscription — exists in the same codebase, is used for other purposes, and would resolve the wait deterministically with zero polling overhead. The model chose polling because that is the simpler architectural pattern in the training corpus; the event-subscription pattern requires more setup code and more knowledge of the system's event API. ha-mcp#1152 captures this exactly: the WebSocket client is already imported in the same codebase, but the wait helper polls REST anyway.

The training corpus reinforces the failure mode through tutorial code in particular. Examples that teach Python often use `time.sleep` for clarity ("here we wait two seconds to give the API time to respond") because the alternative (proper synchronization) would distract from the example's actual lesson. The model has seen many such examples; the pedagogical clarity becomes a default it carries into production code where the same primitive is harmful.

There is also a self-reinforcing local pattern within a generation session. The eumemic/aios#363 specimen shows three different e2e tests (signal outbound, telegram outbound, signal registration) all sharing the same `await asyncio.sleep(0.5)` synchronization wager. Once the model generated one test with sleep-based sync, the next tests used the same template. This is the same sticky-local-pattern observation seen in [`unjustified-lazy-import`](unjustified-lazy-import.md), [`unreachable-defensive-guard`](unreachable-defensive-guard.md), and [`swallowed-exceptions`](swallowed-exceptions.md) — applied at the synchronization-primitive level.

The defect paths are real and varied:

1. **Test flakiness** — sleep-as-synchronization tests pass under one timing budget and fail under another. CI noise compounds. eumemic/aios#363 documents 1/3 CI runs flaking.
2. **Cascading failures in production** — sync sleep in async contexts can starve the thread pool, causing unrelated endpoints to fail. training-agent#42 documents this.
3. **False timeouts and ambiguous results** — polling-loop helpers can time out before the event has occurred, producing `success: true with warning` outputs that downstream consumers can't interpret reliably. ha-mcp#1152 documents this.
4. **Performance latency floors** — polling at 200-500ms intervals adds median latency to every wait operation, even when the underlying event would arrive instantly.
5. **Resource waste** — CPU/scheduler overhead from polling loops; thread-pool occupation from sleeping threads.

This pattern is the **synchronization-primitive cousin of [`wrong-tool-for-job`](wrong-tool-for-job.md)**. Both stem from the model choosing a corpus-default primitive when a framework- or library-specific alternative would be more correct. The difference is that wrong-tool-for-job is about general primitive choices (Jinja vs str.format, pathlib vs os.path), while this entry is about synchronization choices specifically (events vs sleeps, polling vs subscriptions).

The pattern is **AI-amplified, not AI-exclusive**. Human developers write sleep-based synchronization constantly, particularly in tests where the alternative requires more code. The AI-amplified observation is the *frequency* and *consistency*: AI-generated code defaults to sleep-based primitives across many situations where a moment's thought would have suggested the event-based alternative. The clustering shape (three tests with the same `sleep(0.5)` template) is also AI-amplified — humans tend to vary their sleeps based on intuition about how long different operations take; AI tends to reuse the same magic number across multiple sites.

## Evidence / incident

Three captured specimens, each from a different AI-coded Python project. Detailed specimen notes are not included in the public repository.

- **[tornikebolokadze1-cyber/training-agent#42](https://github.com/tornikebolokadze1-cyber/training-agent/issues/42)** — sync `time.sleep` in async-context-aware code. Rate limiter blocks AnyIO thread pool under burst load. 10 stuck sends × 60s = 25% pool utilization on sleeps alone; health checks and admin endpoints start queueing. Severity rated HIGH. AI training-session-management project with Gemini integration.
- **[eumemic/aios#363](https://github.com/eumemic/aios/issues/363)** — sleep-as-test-synchronization. Three e2e tests use `await asyncio.sleep(0.5)` as a synchronization primitive; the author's own comment acknowledges the wager ("CI loses this race; local dev usually wins it"). 1/3 CI runs flake. Three tests share the same defective template — sticky-local-pattern shape. Cure: polling on readiness invariant. AI agent runtime project.
- **[homeassistant-ai/ha-mcp#1152](https://github.com/homeassistant-ai/ha-mcp/issues/1152)** — polling-loop when events exist. `wait_for_entity_registered` polls REST `/api/states/<entity_id>` at 200-500ms intervals up to a deadline; Home Assistant publishes `entity_registry_updated` events over WebSocket that would resolve the wait instantly. The WebSocket client is already used in the same codebase for other purposes. False-timeout warnings ("Helper created but input_number.foo not yet queryable") propagate to the agent and increase misattribution rate. MCP server with substantial CLAUDE.md (41605 bytes).

Three different defect surfaces (test flakiness, production cascading failure, false-timeout ambiguous results), three different layers (test code, production rate limiter, polling helper), three different AI-related projects. Cross-context coverage is broad.

Supplementary references:

- **oliverhaas/django-cachex#86** remaining-work list: *"Multiple `time.sleep(2-4)` for TTL expiry in `tests/cache/test_cache_timeouts.py`, `test_django_core_compat.py`, `test_cache_sync.py` — project memory says use `cache.expire(key, 0)`. ~30s of suite time + CI flake risk."* — captures the **sleep-for-TTL-expiry** sub-shape, where tests sleep for the cache TTL instead of using the cache's expire API. Slow test suites + CI flake. Not captured as primary specimen because the audit references the pattern abstractly.
- **microsoft/agent-framework#5741** — synchronous tool execution (including `time.sleep`) blocks the agent's async event loop, freezing the Responses API polling for tools that should have been written with `asyncio.to_thread`. Adjacent specimen at the framework level — the framework's tool-execution path doesn't wrap sync tools in `to_thread`, and AI-generated tools default to sync `def` rather than `async def`. Could be a separate specimen but the framework-vs-tool-code distinction is fuzzy.

## Detection cues

What to look for in a diff or completion:

- **`time.sleep(N)` in any code that may be called from an async handler.** FastAPI sync endpoints run in a thread pool; an `await`ed wrapper is fine, a sync `time.sleep` is not. The cue is to ask whether the function's caller chain includes any async handlers; if yes, the sleep is dangerous.
- **`await asyncio.sleep(N)` immediately before a test step that depends on setup completion.** Particularly suspect when `N` is a "magic number" (0.5, 1, 2 seconds) without a comment explaining why that duration is enough. The fix is polling on a defined readiness invariant.
- **A comment that says "hope X completes" or "wait for Y" next to a sleep.** The wager is being acknowledged in prose; the code itself is the unsafe primitive.
- **Multiple tests with the same `sleep(0.5)` template.** Three or more tests using the same sleep duration for different operations is a sticky-local-pattern signal. Each sleep is a separate wager, all with the same magic number — strong indicator the pattern was generated, not designed.
- **A `wait_for_X` helper that polls a REST endpoint when the system publishes events.** Check whether the project uses WebSockets / SSE / event streams for *other* purposes. If yes, the polling helper is the wrong tool for a system that already speaks events.
- **`while True: result = check(); if result: return; time.sleep(interval)` patterns.** Classic busy-wait shape. Almost always replaceable with `asyncio.Event.wait()`, `threading.Condition.wait_for(predicate)`, or a subscription primitive.
- **Test code that mocks `time` to control sleep duration.** Suggests the test author has noticed that sleeps are the problem but is patching the symptom rather than removing the unsafe primitive. The underlying production code is also probably wrong.

The diagnostic question for any candidate: *what condition is this code actually waiting for, and can that condition be observed directly?* If the answer is "I'm waiting for some operation to complete and there's no direct signal," the right move is to expose a signal (an `asyncio.Event`, a callback, an event subscription) rather than to wait an arbitrary duration. If the answer is "I'm waiting because the API requires waiting before retry," the right move is to use the API's recommended primitive (often a structured backoff library) rather than ad-hoc sleeps.

## Notes

**Category `async`.** The fit is good for the captured specimens, which all involve async-context concerns even when the wrong primitive is technically synchronous (training-agent's `time.sleep` is wrong *because* the surrounding context is async-aware FastAPI).

**Difficulty rated `medium`.** Spotting `time.sleep` or `await asyncio.sleep` is visually immediate. Knowing whether the sleep is appropriate (some sleeps are correct — backoff loops, deliberate pacing) or defective (sleep-as-synchronization, sleep-blocks-pool, polling-when-events-exist) requires context about the surrounding code's threading model and the system's available primitives. A reader who knows the project's stack can audit quickly; a reader who doesn't will see locally-valid code.

**The pattern is AI-amplified, not AI-exclusive.** Human developers write sleep-based synchronization constantly — particularly in tests, particularly under deadline pressure, particularly when the proper primitive requires more code. The AI-amplified claim rests on frequency, consistency (same magic-number sleep across multiple tests), and the sticky-local-pattern observation (one sleep-based test in a generation context produces several more).

**False-positive shapes.** Be cautious before flagging:

- *Backoff loops with exponential delay.* `for attempt in range(5): try: ...; except: time.sleep(2 ** attempt)` is a legitimate retry-with-backoff pattern, not the defective sleep-based synchronization.
- *Deliberate pacing in a producer loop.* A worker that polls a queue every 1 second is using sleep as a deliberate rate-limiter, not as a synchronization primitive. The cue is whether the sleep duration is *the desired cadence* (correct) or *a wager about how long an operation takes* (defective).
- *Test fixtures that intentionally delay for timing-sensitive coverage.* `time.sleep(0.001)` between two operations to ensure they have different timestamps is legitimate. The cue is whether the sleep is testing timing behavior (correct) or substituting for synchronization (defective).
- *Sleep-as-yield in cooperative multitasking.* `await asyncio.sleep(0)` is the canonical way to yield control to the event loop without delay. Not this pattern.
- *Backoff after a known transient failure.* Network retry loops that sleep 1-30 seconds between attempts are correct. The cue is that the sleep is between *retries of the same operation*, not before a *different operation that depends on prior completion*.

**Mutation operator hint.** A deterministic mutation that takes a clean event-based synchronization pattern and replaces it with sleep-based produces this pattern from clean code. Variants:

- Replace `await ready_event.wait()` with `await asyncio.sleep(0.5)`
- Replace `subscribe(...) → resolve_on_event` with `while not check_via_rest(): time.sleep(0.2)`
- Replace `await asyncio.to_thread(blocking_op)` with `blocking_op()` directly (preserves the sync call without the thread-offload)
- Replace `await asyncio.sleep(retry_delay)` with `time.sleep(retry_delay)` in an async function
- Take a backoff loop and remove the backoff math, replacing it with a fixed `time.sleep(2)`

These compose with other patterns: a `time.sleep` paired with [`swallowed-exceptions`](swallowed-exceptions.md) (the sleep masks transient errors and the swallow hides them) is the maximally defective concurrent shape. A polling loop with [`brittle-error-detection`](brittle-error-detection.md) (the loop catches all exceptions and string-matches on the message) is similarly bad.

**Connection to [`same-project-knows-right-pattern`](../notes/same-project-knows-right-pattern.md) note.** Both [`swapped-args`](swapped-args.md), [`wrong-tool-for-job`](wrong-tool-for-job.md), and this entry feature the diagnostic shape of *the same project knowing the right primitive at one site and using the wrong primitive at another*. The ha-mcp specimen is the cleanest instance here: the WebSocket client is in the same codebase, imported in the same module's dependency graph, used for other features, and not used by `wait_for_entity_registered`. The model's prior at the wait-helper site favored the polling pattern; the model's prior elsewhere favored WebSocket subscriptions. Local generation produced both. The cross-cutting note now spans 10 entries.

**Connection to [`defensive-choice-with-justifying-comment`](../notes/defensive-choice-with-justifying-comment.md) note.** The aios#363 specimen's `# hope discovery completes` comment is doing the same work as `# Memory is optional` in swallowed-exceptions or `# Using TAG for Valkey compatibility` in wrong-tool-for-job: a comment that *justifies* a defensive choice in terms of a hope or constraint rather than ensuring the choice is correct. The "hope" comment is particularly diagnostic — it signals that the author *knew* the primitive was uncertain and chose it anyway. This entry is one of 9+ in the cross-cutting note.
