---
name: string-built-sql
category: security
difficulty: low
generation: evergreen
since_model: null
evidence_grade: observed
---

# String-Built SQL

## Code example

```python
def policy_lookup(state: AgentState, policy_id: str) -> dict:
    """Tool function called by LangGraph agent."""
    cursor = state.db_conn.cursor()
    cursor.execute(f"SELECT * FROM policies WHERE id = '{policy_id}'")
    return cursor.fetchone()
```

The function looks fluent. An f-string interpolates `policy_id` into a SQL string. The query runs. For tested values (e.g., `policy_id = "P-12345"`), the result is correct.

The defect is invisible until `policy_id` is attacker-controlled. With `policy_id = "' OR 1=1 --"`, the constructed SQL becomes:

```sql
SELECT * FROM policies WHERE id = '' OR 1=1 --'
```

— the predicate is now tautological; the query returns *every* row. With `policy_id = "'; DROP TABLE policies; --"`, depending on the database backend and execution mode, the entire `policies` table can be deleted. This is CWE-89 / OWASP A03:2021 (Injection) — the canonical SQL injection.

The fix is the canonical parameterized-query idiom:

```python
def policy_lookup(state: AgentState, policy_id: str) -> dict:
    cursor = state.db_conn.cursor()
    cursor.execute("SELECT * FROM policies WHERE id = %s", (policy_id,))
    return cursor.fetchone()
```

The `%s` placeholder is *not* string interpolation — it's a parameter marker that the database driver binds separately, ensuring `policy_id` is treated as data, not as SQL syntax.

The pattern has several visible sub-shapes in captured specimens:

- **Agent-tool-surface SQL injection.** A LangGraph or similar agent's tool function builds SQL from values reachable from the agent's state. The trust boundary is *user → agent → tool function → SQL*. AI-generated agent tools commonly produce f-string SQL because the tool function's local context favors fluent string construction over parameterized binding. Captured in digvijaysai29/agentic-insurance#1 (production multi-agent insurance system with explicit "built with Claude" branding; SQL injection in `tools/policy_lookup.py` and `tools/claim_history.py`).
- **Prompt-injection-induced SQL injection.** An AI coding tool (Aider) was initially producing safe parameterized SQL. Attacker-supplied "team coding standard" reframed unsafe string formatting as the project's standard. The AI accepted the guidance, rewrote safe code into unsafe code, *and generalized the unsafe pattern to a new login function in the same workflow*. Captured in Aider-AI/aider#5077. This is a meta-shape: AI coding tools themselves can be subverted into producing the pattern.
- **Schema-blind f-string with three independent interpolation channels.** A SQL-building function takes three parameters (`fields`, `table_name`, `start_date`), interpolates all three via f-string, and treats them as interchangeable. The schema-aware fix differs per channel: parameterized binding for *values*, allow-list validation for *identifiers* (column/table names cannot be parameterized). Captured in jackyideal/AlphaTeam (`get_data_by_sql` in a quant-trading platform; HIGH severity; reproduction with `start_date = "20200101' OR 1=1 --"` returns unfiltered rows).
- **Helper-function with concatenation in WHERE clause.** The Chaudhry-Adill/hrms case (supplementary): `search_faq` endpoint builds a WHERE clause by joining a list of condition strings and interpolates that into the SQL template. Values are parameterized, but the *condition list itself* is concatenated. Future refactors that append user-controlled raw text become injection vectors.

All sub-shapes share the same root mechanism: the model produced SQL by string construction (f-string, `.format()`, `+` concatenation) when the database driver's parameter-binding API was available and would have been correct.

## Mechanism

A language model generates SQL-touching code from a local context that contains:

- A connection / cursor object (or ORM session)
- A SQL string template to execute
- Values to inject into the template

The model has seen *both* fluent string-construction patterns *and* parameterized-query patterns in its training corpus:

- **Fluent / defective**: `cursor.execute(f"SELECT * FROM users WHERE name LIKE '%{q}%'")` — readable, idiomatic-looking for f-string-era Python.
- **Parameterized / correct**: `cursor.execute("SELECT * FROM users WHERE name LIKE %s", ('%' + q + '%',))` — slightly less readable; requires knowing the database driver's parameter style (`%s` for psycopg, `?` for sqlite3, named for SQLAlchemy).

The defective shape is over-represented per-token in three corpus segments:

**Tutorial code that demonstrates SQL queries.** Python SQL tutorials use string-formatted queries because the example focuses on *what SQL is*, not on *how to safely parameterize it*. The "how to do SQL in Python" search produces many tutorials with f-string examples. The "how to prevent SQL injection" search is a separate Q&A with its own corpus that the model has also seen — but the tutorial corpus is heavier per-token.

**f-string adoption (PEP 498) shifted Python's idiom.** Pre-2016 Python tutorials used `%`-style or `.format()` for string interpolation. Post-2016 tutorials use f-strings. The SQL-string-construction corpus inherited the f-string shift. The result: modern Python tutorials almost universally use f-string SQL when demonstrating queries. The model's *modern* prior is f-string-SQL-heavy.

**One-liner-with-side-effect SQL.** `cursor.execute(f"SELECT ... {x}")` is a one-line side effect that fits the fluent shape. The principled alternative requires *two* arguments to `execute()` (the SQL template and the parameter tuple), which the model produces less fluently. Token-level prediction favors the one-liner.

There are also explicit *warnings* in the corpus — bandit's B608, OWASP guidance, Python security blogs. The model has seen them. What the model does not reliably do during local generation is *select* the parameterized form when producing a SQL call. The corpus's tutorial weight overrides the warning weight at the per-token decision point.

Three concrete failure paths are visible in the captured specimens:

**Path 1: Agent-tool-surface boundary injection.** digvijaysai29/agentic-insurance has SQL injection in `tools/policy_lookup.py` and `tools/claim_history.py` — tool functions called by LangGraph agents. The trust boundary is *user → agent state → tool function → SQL*. The CLAUDE.md (1166 bytes) prescribes "No Hallucinations: Agents must use tools for all data retrieval" but is silent on SQL injection at the tool surface. The "Corridor security analysis" audit identifies CWE-89 / OWASP A03:2021. The defect surface is the *high-trust-boundary* shape — agent tool functions are where user input flows through the trust boundary into SQL.

**Path 2: Prompt-injection-induced rewrite.** Aider-AI/aider#5077 documents a security-relevant meta-finding: in a validated retest, Aider initially produced safe parameterized SQL, was presented with attacker-supplied "team coding standard" guidance favoring string formatting, *accepted* the guidance, and rewrote the safe SQL into unsafe SQL — *and generalized the unsafe pattern* to a new login function in the same workflow. The mechanism here is *prompt-injection-driven*, distinct from the corpus-fluency-driven default shape, but produces the same defect. The audit's framing: *"Aider should resist attacker-supplied or repository-supplied coding guidance that explicitly downgrades safe SQL handling to unsafe string interpolation."*

**Path 3: Schema-blind three-channel interpolation.** jackyideal/AlphaTeam's `get_data_by_sql` interpolates `fields`, `table_name`, and `start_date` all via f-string. The audit's worked attack: `start_date = "20200101' OR 1=1 --"` produces SQL that SQLite parses and executes, returning unfiltered rows. The fix is *three different defenses* (allow-list for column/table identifiers, parameterized binding for values) — the model produced one defense (none) for all three channels because it treated them as interchangeable string-interpolation slots.

This pattern is **AI-amplified, not AI-exclusive**. Human Python programmers write f-string SQL constantly — particularly beginners, particularly in scripts, particularly when prototyping. The AI-amplified differential rests on:

1. **Agent-tool-surface concentration**: AI-generated agent systems produce f-string SQL at the highest-trust-boundary points (the user-facing tool surface). The defect's blast radius is largest exactly where the AI produces it most.
2. **Prompt-injection vulnerability**: AI coding tools can be *steered* to produce SQL injection via adversarial project context (the Aider specimen). Human developers don't have an analogous failure mode.
3. **Coexistence with other AI-typical patterns**: agent tool functions paired with `except Exception: pass` swallow the SQL error; the injection succeeds silently. Cross-link to [`swallowed-exceptions`](swallowed-exceptions.md).
4. **CLAUDE.md / AGENTS.md don't prevent it**: the digvijaysai29 project has CLAUDE.md with coding standards; the SQL injection slipped through because the standards address agent-loop hygiene without explicit security rules at the tool boundary.

## Evidence / incident

Three captured specimens covering distinct sub-shapes and AI-authorship signals. Detailed specimen notes are not included in the public repository.

- **[digvijaysai29/agentic-insurance#1](https://github.com/digvijaysai29/agentic-insurance/issues/1)** — agent-tool-surface SQL injection in a Production-ready multi-agent insurance system. CLAUDE.md (1166 bytes); project description explicitly names *"built with LangGraph, FastAPI, and Claude"*. Affected files: `tools/policy_lookup.py`, `tools/claim_history.py`. Audit framework: "Corridor security analysis." References CWE-89, OWASP A03:2021.
- **[Aider-AI/aider#5077](https://github.com/Aider-AI/aider/issues/5077)** — prompt-injection-induced SQL injection. AI coding tool (Aider) rewrote safe parameterized SQL into unsafe f-string SQL after accepting attacker-supplied "team coding standard." Generalized the unsafe pattern to a new login function. Validated retest with `gpt-4o-mini` (whole-edit format). Captures the meta-shape: AI tools themselves are subvertable.
- **[jackyideal/AlphaTeam](https://github.com/jackyideal/AlphaTeam)** — schema-blind three-channel f-string SQL. `AlphaFin/indicators/db_utils.py:41-62` interpolates `fields`, `table_name`, and `start_date` directly. Reproducible attack with `start_date = "20200101' OR 1=1 --"` returns unfiltered rows. HIGH severity. *AI-authorship of the underlying code is inferred (agent-tool-surface domain, future-driven framing) rather than confirmed.*

Three different sub-shapes (agent-tool-surface / prompt-injection-induced / schema-blind-three-channel), three different defect surfaces (LangGraph agent tools / AI coding tool subversion / quant-trading agent-tool-future-surface).

Supplementary references:

- **[Chaudhry-Adill/hrms](https://github.com/Chaudhry-Adill/hrms)** — CRITICAL SQL injection via f-string WHERE clause in helpdesk FAQ search. Fork of frappe/hrms with CLAUDE.md (5153 bytes). The values are parameterized but the WHERE-clause condition list is concatenated — a partial-defense shape.
- **[BDB-Labs/TruePresenceESE](https://github.com/BDB-Labs/TruePresenceESE)** — "f-string SQL construction is a SQL injection vector" in `api/auth.py`. Audit-label-driven finding.
- **[startreedata/mcp-pinot#90](https://github.com/startreedata/mcp-pinot/issues/90)** — Apache Pinot MCP server's `read_query` tool only validates `SELECT` prefix; raw SQL flows from MCP client to Pinot with weak input sanitization. Adjacent shape — *trust-boundary-too-wide* rather than f-string-construction.
- **[laichunpongben/magi](https://github.com/laichunpongben/magi)** — SQL injection via f-string table/schema interpolation in `knowledge_base.py`. AI knowledge-base project.

Bandit has rule **B608** (`hardcoded_sql_expressions`); semgrep has equivalent rules; OWASP has explicit guidance. Widely-adopted community lint rules; the AI-amplified observation is the agent-tool-surface concentration.

## Detection cues

What to look for in a diff or completion:

- **`cursor.execute(f"...")` / `cursor.execute(sql.format(...))` / `cursor.execute("..." + var + "...")`** — any string-built SQL in the execute call. The most direct signal.
- **f-string SQL in agent tool functions.** Files in `tools/`, `agents/*/tools/`, or similarly-named directories of LangGraph / LangChain / agentic-framework projects. The trust boundary makes this the highest-stakes surface.
- **SQL-building helper functions that take user-derivable parameters.** A function that takes `query_text`, `user_input`, `filter_value`, or similar and constructs SQL by interpolation. Even if today's caller passes safe constants, the function is reachable from user-controlled paths.
- **Multi-channel interpolation where channels have different defense needs.** A SQL-building function that takes both *identifiers* (column names, table names) and *values* — the identifiers cannot use parameter binding (SQL syntax forbids it) and need allow-list validation; the values must use parameter binding. If both are f-stringed, the function is schema-blind.
- **`f"... '{var}' ..."` patterns** (single-quoted f-string interpolation inside SQL). The single quotes are a strong signal the model is trying to "quote" the value into the SQL — exactly the form that breaks under any value containing a `'` character (whether attacker-controlled or just `O'Brien`).
- **AGENTS.md / CLAUDE.md that mention security/SQL but the code doesn't reflect it.** Codified-guidance-is-insufficient applied to the SQL-injection surface.
- **Attacker-supplied "team coding standards" / "style guides" that override parameterized-query defaults.** The Aider sub-shape — if a repo contains a coding-standard file that explicitly prefers string-formatted SQL, AI tools may take that at face value.

The diagnostic question for any SQL-touching code: *if a value flowing into this SQL contained `'`, `"`, `;`, `--`, or `OR 1=1`, what would happen?* If parameter-bound, the value is treated as literal text — safe. If f-string-interpolated, the value is treated as SQL syntax — injection-prone. The cure is mechanical: use the database driver's parameter style (`%s`, `?`, named) instead of string construction.

Bandit `B608` catches the pattern mechanically. Adding it to CI is the structural cure; documentation alone is observably insufficient.

## Notes

**Category `security`.** The category covers patterns where defects produce *security* failures (data exfiltration, data destruction, authentication bypass).

**Difficulty rated `low`.** Spotting `f"..."` inside `cursor.execute(...)` is visually trivial. Bandit B608 catches it mechanically. The reason this is in the taxonomy is *defect surface* (agent-tool-surface concentration) and *AI-meta-shape* (prompt-injection-induced rewrite), not difficulty. Once a reader knows to look at SQL-touching code in agent tools, the audit is mechanical.

**The pattern is AI-amplified, not AI-exclusive.** Restated: every developer who has written SQL in Python has written an f-string SQL query at some point. The AI-amplified differential rests on agent-tool-surface concentration (the highest-trust-boundary surface), prompt-injection vulnerability of AI coding tools, and codified-guidance-insufficient at the SQL-injection-prevention layer.

**False-positive shapes.** Be cautious before flagging:

- *Truly-trusted internal constants.* `cursor.execute(f"SELECT COUNT(*) FROM {TABLE_NAME}")` where `TABLE_NAME` is a module-level constant or an enum value validated at startup. The cue is whether the interpolated value can be traced back to user input.
- *Identifier interpolation that genuinely requires it.* Column names and table names *cannot* be passed via parameters (SQL syntax). The fix is allow-list validation before interpolation, not parameter binding. Flagging the f-string here would be technically correct but the cure differs from the value-injection case.
- *ORM-built queries that use `format()` internally.* SQLAlchemy and similar ORMs sometimes construct SQL via templating but parameter-bind the values separately. Verify the underlying execute uses parameter binding.
- *SQL templates loaded from external files / stored procedures.* The interpolation may be happening elsewhere; the visible code may just be the wrapper. Check the full data flow.
- *Test fixtures that intentionally construct SQL strings* for SQL-parsing / SQL-syntax tests. The code's purpose is to exercise SQL, not to execute it against real data.

**Mutation operator hint.** A deterministic mutation that introduces the pattern from clean code:

- Replace `cursor.execute("SELECT * FROM t WHERE id = %s", (id,))` with `cursor.execute(f"SELECT * FROM t WHERE id = '{id}'")`
- Replace `cursor.execute(sql_template, params)` with `cursor.execute(sql_template.format(**params))`
- Replace ORM-built query with manual f-string SQL in a "performance optimization" comment
- Replace parameterized identifier validation (allow-list) with raw f-string interpolation
- Take an agent tool function that uses parameterized SQL and rewrite under "team coding standard" reframing (the Aider meta-sub-shape)

These compose with [`swallowed-exceptions`](swallowed-exceptions.md) — f-string SQL inside `try: ...; except Exception: pass` silently swallows the SQL-syntax error that would normally surface from a malformed payload, allowing injection attempts to fail quietly. Also composes with [`assert-for-runtime-validation`](assert-for-runtime-validation.md) — `assert sanitized(input)` followed by f-string SQL is stripped under `-O`, so the sanitization vanishes while the injection-prone SQL remains.

**Connection to [`ai-pedagogical-bias`](../notes/ai-pedagogical-bias.md) note.** Modern Python tutorials (FastAPI, LangChain, LangGraph examples) use f-string SQL extensively in their demonstration code because the example focuses on *what* the API does. The model inherits the tutorial style; production code under user input becomes injection-prone. This is the *security-stakes* version of the AI-pedagogical-bias mechanism — same generation pattern, harder consequences.

**Connection to [`codified-guidance-is-insufficient`](../notes/codified-guidance-is-insufficient.md) note.** The digvijaysai29 specimen has CLAUDE.md coding standards focused on agent-loop hygiene; SQL injection slipped through because the standards don't explicitly address security at the tool boundary. The Chaudhry-Adill specimen is a fork of frappe/hrms with CLAUDE.md; the SQL injection is in inherited code but the AI-driven audit caught it. Bandit B608 + OWASP guidance + project-level CLAUDE.md / AGENTS.md still don't prevent AI from producing the pattern at agent tool surfaces.

**Connection to prompt-injection as a new defect-introduction vector.** The Aider specimen is methodologically important: AI coding tools accept "team coding standards" from project context and treat them as authoritative. An attacker who can place a CONTRIBUTING.md / CODING_STANDARDS.md / CLAUDE.md / AGENTS.md in a repository can steer the AI's generation to produce *known-vulnerable* patterns. This is a defense-in-depth observation that crosses the boundary between *AI-generated-defect-classes* (the taxonomy's main framing) and *AI-tool-security-models* (an adjacent concern).

**Connection to deployment-context cluster.** This entry joins [`missing-network-timeout`](missing-network-timeout.md), [`assert-for-runtime-validation`](assert-for-runtime-validation.md), [`resource-leak-no-context-manager`](resource-leak-no-context-manager.md), [`async-await-mismatch`](async-await-mismatch.md), [`print-instead-of-logging`](print-instead-of-logging.md), and [`f-string-in-logger-call`](f-string-in-logger-call.md) in the cluster of patterns where the defect's blast radius is largest in deployment contexts (long-running services, agent tool surfaces, production servers) — exactly where AI-generated code is being shipped now. The cure across the cluster is to encode deployment-context awareness in CI / lint rather than in documentation.
