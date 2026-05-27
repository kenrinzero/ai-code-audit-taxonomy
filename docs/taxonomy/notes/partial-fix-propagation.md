# Partial-fix-propagation

A prior fix-PR addressed *some* sites of an AI-typical pattern; sibling files, modules, or call-sites that weren't in the PR's scope retain the wrong pattern. The PR's boundary becomes a new drift boundary inside the codebase.

This is structurally a sub-shape of [`same-project-knows-right-pattern`](same-project-knows-right-pattern.md) — the right pattern lives in the codebase, at exactly the sites the prior fix touched — but it has its own AI-vs-human differential and its own audit move, which is why it earns a standalone note now that three specimens are in evidence across three distinct entries.

## Where the observation appears

| Entry | Prior fix | Sites the fix did not reach |
|-------|-----------|-----------------------------|
| [`f-string-in-logger-call`](../patterns/f-string-in-logger-call.md) | IBM/mcp-context-forge precursor #1837 migrated `sse_transport.py` and `resource_service.py` to `%`-style | ~50 sibling modules across `mcpgateway/services/`; ~1000+ residual f-string log calls surfaced in #4617 |
| [`missing-network-timeout`](../patterns/missing-network-timeout.md) | dagster-io/dagster prior #17831 added timeouts to schedule/sensor code paths | `dagster-dg-cli` developer-CLI path; 3 `requests.*` sites surfaced by an AST-scan reproducer in #33747 |
| [`async-await-mismatch`](../patterns/async-await-mismatch.md) | carpenike/coachiq PR A6 fixed missing-awaits at the v1→v2 cutover sites | SecurityWebSocketHandler stats + recent-events sites, deferred as separate work in #164; a downstream Pydantic-vs-dict mismatch surfaces only once the missing-await is fixed |

Three specimens, three different defect surfaces (logging discipline / reliability primitive / async correctness), three different reasons the fix did not propagate (codebase scale / forgotten sibling sub-tree / explicit out-of-scope deferral).

## Mechanism

When the AI generates a fix, the local-attention context is *the scope of the PR*: the file under repair, the test cases the reviewer commented on, the diff hunks in the staged change. The model produces correct code at every site inside this scope. Sibling files outside the scope are not in the local attention window, and the model does not naturally extend the fix to them — "look for sibling instances and fix them all" is a global-scan operation, and the model is in a local-generation step.

This is the same local-attention limitation that produces [`same-project-knows-right-pattern`](same-project-knows-right-pattern.md) drift during original authoring, applied at the fix-PR step.

## Why this is human-vs-AI differential

Human developers fixing one site of a pattern naturally extend the fix to sibling sites *because the developer's working memory holds the pattern being fixed*. The pattern is the thing in mind; the next thought is "where else does this happen?" A human reviewer who sees one f-string log call starts grepping the codebase.

The AI's fixing step has the same local-attention limitation as its generating step. The fix scope is the local window; sibling sites outside that window are not naturally surfaced. The PR boundary becomes a drift boundary that did not exist before the fix — sibling sites visibly retain the wrong pattern while the fixed sites now stand out at the right pattern.

## Diagnostic move

The fastest audit on a codebase with a recent fix-PR addressing a known AI-typical pattern:

1. Read the fix-PR's scope — which files, which functions, which sub-tree.
2. Grep the rest of the codebase for the unfixed pattern. Sibling files in adjacent directories are the highest-likelihood drift sites.
3. If the fix-PR closes a tracking issue, the sibling-site residue is often a candidate for a follow-up tracking issue — IBM, dagster, and coachiq all have a tracking-issue-after-fix-PR shape, and #4617 / #33747 / #164 are exactly those follow-ups.

An AST-scan reproducer is particularly diagnostic — the dagster specimen's author distilled the pattern into a mechanical check that surfaces every residual site. When the pattern is mechanically detectable, the audit sweeps the codebase in seconds.

## Why this is a note, not an entry

The defect at each residual site is whatever the underlying pattern is — `f-string-in-logger-call`, `missing-network-timeout`, `async-await-mismatch`. Each is documented by its own entry. The cross-cutting observation is *about how a prior fix's scope shapes the residual drift*, which sits meta-on-top-of the defect class. An entry would either duplicate the three existing entries or create an umbrella whose evidence is the three entries themselves.

The note exists to name the meta-shape and the audit move it enables.

## Promotion criteria

This observation was tracked as a candidate inside [`same-project-knows-right-pattern`](same-project-knows-right-pattern.md). The promotion-trigger (3 specimens across distinct entries) was reached when the coachiq PR A6 specimen landed alongside the IBM and dagster ones. Standalone-note status promoted 2026-05-25.

If a fourth specimen surfaces that adds a new shape to the family (a fix-PR explicitly scoped to a single site with overlooked siblings; a fix-PR that propagated *some* but not *all* of a multi-component pattern; a fix-PR whose scope was correct but whose sibling-residue surfaces a compound downstream defect different from coachiq's Pydantic-vs-dict shape), expand the table here.
