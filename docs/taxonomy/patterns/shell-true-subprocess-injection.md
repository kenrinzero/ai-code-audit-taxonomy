---
name: shell-true-subprocess-injection
category: security
difficulty: low
generation: evergreen
since_model: null
evidence_grade: observed
---

# Shell=True Subprocess Injection

## Code example

```python
import subprocess

def fetch_dataset(url: str, dest_path: str) -> None:
    cmd = f"wget -c {url} -O {dest_path}"
    subprocess.run(cmd, shell=True, capture_output=False)
```

The function works for sanitized inputs. `wget` downloads `url` to `dest_path`. For trusted URLs and paths the function is correct.

The defect emerges when either `url` or `dest_path` contains shell metacharacters. With `url = "http://x; rm -rf ~"`, the constructed shell string is `wget -c http://x; rm -rf ~ -O ...` — the shell parses the `;` as a command separator and runs `rm -rf ~` after the wget. The same applies to backticks, `$(...)`, `|`, `&&`, `||`, redirections, glob patterns, and many other shell metacharacters. Any string value reachable from external input becomes a remote-code-execution vector.

The tightened version uses argument-list form and `shell=False` (the default):

```python
def fetch_dataset(url: str, dest_path: str) -> None:
    subprocess.run(
        ["wget", "-c", url, "-O", str(dest_path)],
        capture_output=False,
        check=False,
    )
```

The argument list is passed directly to the OS exec; no shell is involved; no metacharacters are interpreted. The function is now injection-proof for the values themselves (though the program being invoked — `wget` here — still needs to be trusted).

The pattern has several visible sub-shapes in captured specimens:

- **shell=True + f-string interpolation** — the dual surface to [`string-built-sql`](string-built-sql.md). `f"command {var}"` passed to `subprocess.run(..., shell=True)` produces a shell-injection point at each interpolated value. Captured in web3guru888/asi-build#1264 (`f"wget -c {url} -O {dest_path}"` with `shell=True`; ASI framework with 11KB CLAUDE.md).
- **LLM-output-direct-to-shell** — the planning loop produces commands; commands run via `subprocess.run(shell=True)`. No sanitization, no allow-list, no sandboxing. The trust boundary is *LLM output → host shell*. If the LLM can be prompt-injected, the shell is the payload's target. Captured in peteromallet/megaplan (`_run_user_command()` in `loop/engine.py` — "General-purpose planning and execution harness for LLMs").
- **Compound shell=True + swallowed-exception bypass of safety check.** A safety module (`detect_dangerous_command` or similar) is supposed to gate command execution, but the safety-module import is wrapped in `except ImportError: pass`. If the import fails (missing dependency, environment issue), the safety check silently doesn't run and all commands execute unfiltered. Captured in NousResearch/hermes-agent (`tui_gateway/server.py` — 2 instances; Claude Code-generated audit).
- **shell=True + HTTP request parameter direct to shell.** User-supplied command from HTTP request is passed straight to a shell with no validation. Captured in NousResearch/hermes-agent instance 2 (also in QuantGeekDev/docker-mcp's WindowsExecutor, supplementary).

All sub-shapes share the same root mechanism: `subprocess.run(..., shell=True)` with an interpolated string from any externally-reachable source.

## Mechanism

A language model generates subprocess-invoking code from a local context that contains:

- A command to run (string template)
- Values to inject into the template
- A subprocess primitive (`subprocess.run`, `subprocess.Popen`, `os.system`, etc.)

The training corpus contains **both** the safe form *and* the unsafe form:

- **Unsafe (corpus-dominant)**: `subprocess.run(cmd_string, shell=True)`. Reads naturally; matches how shells are documented in Stack Overflow answers ("just pass the command string"); one-line construction.

- **Safe (corpus-recessive)**: `subprocess.run([prog, arg1, arg2], shell=False)`. The argument list form; requires breaking the command into components; less fluent to write inline.

The defective shape is over-represented per-token in three corpus segments:

**"How do I run a shell command in Python" Stack Overflow answers.** The asker's framing — "I have this shell command, how do I run it?" — naturally leads to answers like `subprocess.run("cmd args ...", shell=True)`. The asker had a shell-syntax-formatted command in mind; the answer matches the framing. Security-conscious follow-ups exist in separate Q&A threads.

**Tutorial code and beginner Python content.** Subprocess tutorials commonly show `shell=True` because the example is *demonstrating that subprocess can run shell commands*. The shell-injection caveat is a separate paragraph or footnote that the model doesn't reliably attach to the surface form.

**Quick scripts and one-liners.** `subprocess.run(f"ls {dir}", shell=True)` is fluent; `subprocess.run(["ls", dir])` is one character longer but breaks the chain. Token-level prediction favors the one-liner.

The model knows about `shell=True` risk in the abstract — it can explain SQL injection and command injection when asked directly. What it does not do reliably during local generation is *select* the argument-list form when producing a subprocess call. The corpus's shell-syntax-fluent form wins at the per-token decision point.

The pattern interacts with the **prompt-injection-induced defect class** observation captured in [`string-built-sql`](string-built-sql.md): AI coding tools can be steered toward unsafe-subprocess code via adversarial "coding standards" the same way they can be steered toward unsafe SQL. The defense-in-depth argument applies to both surfaces.

The defect path is **direct shell-command-injection at any externally-reachable subprocess call**. Concrete attack scenarios from the captured specimens:

- **hermes-agent (instance 1)**: user-config-supplied `quick_commands` execute with `shell=True`; any user who edits the config can inject shell commands.
- **hermes-agent (instance 2)**: HTTP request param flows directly to `shell=True`; remote attacker can execute arbitrary commands.
- **megaplan**: LLM-output-direct-to-shell; prompt-injected LLM output becomes shell-injection payload.
- **asi-build**: dataset config URL interpolated into shell string; future trust-boundary movement (community-supplied URLs) makes the latent defect active.

This pattern is **AI-amplified, not AI-exclusive**. Human Python programmers write `shell=True` constantly, particularly in scripts. The AI-amplified differential rests on:

1. **Agent-tool-surface concentration**: AI-generated agent systems produce `shell=True` at the *most user-facing surface* (TUI gateways, HTTP request handlers, LLM-output-handling). The defect's blast radius is largest exactly where AI produces it most.
2. **LLM-output-trust-chain**: AI tooling that runs LLM-generated commands extends the trust chain through the LLM. Prompt-injection of the LLM becomes shell-injection of the host. Human developers don't have an analogous trust-chain failure mode at this scale.
3. **Compound shape with swallowed-exceptions**: the hermes-agent instance 2 shows safety checks bypassed via `except ImportError: pass`. The compound defect is more AI-typical than either component alone — AI generates both broad excepts and shell=True; the combination produces a silent safety-check bypass.
4. **Codified-guidance-is-insufficient at multiple layers**: Bandit B602 (subprocess_popen_with_shell_equals_true), B604 (any_other_function_with_shell_equals_true), B605 (start_process_with_a_shell), OWASP Command Injection guidance — all are codified. AI-generated code reproduces the pattern despite all the rule-coverage.

## Evidence / incident

Three captured specimens, each from a different AI-tooling Python project. Detailed specimen notes are not included in the public repository.

- **[NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)** — 2 instances of `subprocess.run(..., shell=True)` in `tui_gateway/server.py` (lines 2308 and 3131). Instance 1: user config commands. Instance 2: HTTP request commands with safety check bypassed by `except ImportError: pass` (compound shape with swallowed-exceptions). Critical severity. **Claude Code-generated audit** (signed `🤖 Generated with Claude Code`). AGENTS.md 51529 bytes (one of the largest in the taxonomy's evidence base). Hermes-agent has now contributed specimens to 6+ taxonomy entries.
- **[peteromallet/megaplan](https://github.com/peteromallet/megaplan)** — `_run_user_command()` in `loop/engine.py:104-107, 246-249` passes LLM output directly to `subprocess.run(..., shell=True)` with no sanitization or sandboxing. Project description: "General-purpose planning and execution harness for LLMs." The defect surface is the framework's central function.
- **[web3guru888/asi-build#1264](https://github.com/web3guru888/asi-build/issues/1264)** — `subprocess.run(f"wget -c {url} -O {dest_path}", shell=True)` in `download_datasets.py:55-56`. Composite shape: `shell=True` + f-string + url interpolation. "Unified ASI framework" with CLAUDE.md (11511 bytes). The audit explicitly raises the **trust-boundary-drift** argument: "Dataset registries tend to grow over time, and the trust boundary moves."

Three different sub-shapes (compound shell=True + swallowed-exception bypass / LLM-output-direct-to-shell / shell=True + f-string composite), three different audit framings (Claude Code-generated / community code-audit / community contributor B602 reference), three different AI-tooling project domains (TUI agent gateway / LLM planning harness / ASI framework).

Supplementary references:

- **[QuantGeekDev/docker-mcp#19](https://github.com/QuantGeekDev/docker-mcp/issues/19)** — "Security: Command injection via shell=True in WindowsExecutor" — docker MCP server with shell=True at the executor surface. Same root mechanism in MCP-server deployment context.
- **[Heldinhow/workflow-dev](https://github.com/Heldinhow/workflow-dev)** — "ShellTool uses shell=True - command injection risk" filed in March 2026. Workflow framework's ShellTool — the framework's *primary tool* is the defect.
- **[chaoss/CollectOSS](https://github.com/chaoss/CollectOSS)** — "shell=True could lead to injection in Facade Worker" (2026-04-30). Adjacent specimen in OSS-collection tooling.

Bandit has rules **B602** (`subprocess_popen_with_shell_equals_true`), **B604** (`any_other_function_with_shell_equals_true`), and **B605** (`start_process_with_a_shell`). OWASP Command Injection guidance is widely cited. CWE-78 (OS Command Injection). The AI-amplified observation is the *concentration at AI-tooling user-facing surfaces*.

## Detection cues

What to look for in a diff or completion:

- **`subprocess.run(cmd, shell=True, ...)` / `subprocess.Popen(cmd, shell=True, ...)`** where `cmd` is anything other than a fully-internal hardcoded constant. The most direct signal. Particularly suspect when `cmd` is an f-string, a `.format()` result, or a `+`-concatenated string.
- **`os.system(cmd)` / `os.popen(cmd)`** — older API surfaces that always invoke a shell. Same defect class.
- **`subprocess.run("cmd " + var, ...)` / `subprocess.run(f"cmd {var}", ...)`** even when `shell=True` is omitted. If the first argument is a single string (not a list) and `shell=True` is not explicit, the behavior depends on the OS — but the *intent* is shell-syntax and the safety analysis should treat it as `shell=True`.
- **LLM-output-direct-to-subprocess** — code that takes a string from an LLM response and passes it to subprocess. The trust chain is *LLM → subprocess*; the LLM is attackable; the subprocess is the payload's target.
- **Agent tool functions that accept commands from external sources** (HTTP, WebSocket, user config, request params). The trust boundary is the agent's input surface; subprocess on that surface should always use argument-list form.
- **Safety-check imports wrapped in `try: import safety; except ImportError: pass`.** If the safety module governs subprocess execution, the bypass makes the safety check optional. This is the **compound shape with swallowed-exceptions** captured in the hermes-agent specimen.
- **Bandit `# noqa: B602` / `# noqa: B604` / `# noqa: B605` annotations** without justifying comments. The lint rule has been silenced; verify whether the suppression is principled or reflexive.

The diagnostic question for any subprocess call: *can any value flowing into the command string ever be attacker-controlled?* If yes, use argument-list form. If no — verify by tracing the data flow — even then prefer argument-list as a future-proofing measure against trust-boundary drift.

Bandit `B602`, `B604`, `B605` catch the pattern mechanically. Adding them to CI is the structural cure. The argument-list form is virtually never wrong when it's a viable alternative.

## Notes

**Category `security`.** Together with [`string-built-sql`](string-built-sql.md) and [`tarfile-extractall-without-filter`](tarfile-extractall-without-filter.md), the category spans the three most common AI-amplified security surfaces: SQL injection, command injection, path-traversal-via-archive-extraction.

**Difficulty rated `low`.** Spotting `shell=True` is visually trivial. Bandit B602 catches it mechanically. The reason this is in the taxonomy is *AI-tool-surface concentration* (the defect lands where AI tooling is most user-facing) and the *LLM-output-trust-chain* observation (a new defect class introduced by AI agent systems).

**The pattern is AI-amplified, not AI-exclusive.** Restated: every Python developer who has written subprocess code has used `shell=True` at some point. The AI-amplified differential rests on agent-tool-surface concentration, LLM-output-trust-chain, compound-shape with swallowed-exceptions, and codified-guidance-insufficient at multiple layers.

**False-positive shapes.** Be cautious before flagging:

- *Hardcoded internal commands.* `subprocess.run("ls -la", shell=True)` with no variables and no external input is safe in the narrow sense. Even here the argument-list form is preferred for clarity, but it isn't a security defect.
- *Genuinely-needed shell features.* Some commands require pipes, redirections, glob expansion, or environment-variable substitution. The argument-list form can't express these. The cure is either (a) using `shlex.quote()` on user-controlled values before interpolation, (b) implementing the shell features in Python (pathlib's glob, file-open redirections), or (c) accepting the risk with documented allow-list validation. The cue is whether the audit can identify *why* shell is required.
- *Subprocess with allow-list-validated values.* If the value going into the shell string has been validated against a tight allow-list (e.g., `if cmd not in {"ls", "ps", "df"}: raise`), the injection vector is constrained. The argument-list form is still preferred but the security defect is reduced.
- *Test code intentionally testing shell behavior.* Tests that exercise shell escaping deliberately may use `shell=True`. The cue is whether the test is testing shell escaping or just *using* a shell.
- *Migration code from a shell-script-based prior implementation.* If the project is incrementally migrating a shell script into Python and the subprocess call is the legacy boundary, `shell=True` may be transitional. The cue is whether the migration is documented and the transition is being completed.

**Mutation operator hint.** A deterministic mutation that introduces the pattern from clean code:

- Take `subprocess.run([prog, arg1, arg2])` and replace with `subprocess.run(f"{prog} {arg1} {arg2}", shell=True)`
- Take `subprocess.run([cmd], shell=False)` and add `shell=True`
- Replace argument-list form with `os.system(cmd_string)`
- Take a safety-module-gated subprocess and wrap the safety-module import in `try: import safety; except ImportError: pass` (compound with swallowed-exceptions)

These compose with [`string-built-sql`](string-built-sql.md) (same root mechanism applied to SQL vs shell), [`swallowed-exceptions`](swallowed-exceptions.md) (the compound bypass shape captured in hermes-agent), and [`hardcoded-config-values`](hardcoded-config-values.md) (when the shell command target is hardcoded but the arguments are interpolated, the configuration is half-secure).

**Connection to [`codified-guidance-is-insufficient`](../notes/codified-guidance-is-insufficient.md) note.** Bandit B602/B604/B605 + OWASP guidance + CWE-78 + project-level CLAUDE.md / AGENTS.md (in hermes-agent, asi-build, etc.) — all are codified, well-known, widely-cited. AI-generated codebases reproduce the pattern despite all four layers. The compound shape (shell=True + swallowed-exception bypass) demonstrates how AI-typical defects compose to defeat even *intended* safety checks.

**Connection to LLM-output-trust-chain observation.** The megaplan specimen captures a defect class that didn't exist before AI agent frameworks: *AI-generated commands executed on a host*. The trust chain is *user → planner → LLM → subprocess*. Prompt injection of the LLM (via task description, retrieved context, tool result, or attacker-supplied input anywhere upstream) becomes shell injection of the host. This is structurally similar to the prompt-injection-induced sub-shape in [`string-built-sql`](string-built-sql.md) (Aider's case) but with a more direct attack path — the LLM doesn't need to *modify project code*; it just needs to *produce a command*. Worth tracking if more specimens of LLM-output-direct-to-dangerous-primitive accumulate: this could be a structurally important new cross-cutting note.

**Connection to deployment-context-blind defects cluster.** This entry joins seven prior entries in the cluster of defects whose blast radius is largest in production deployment contexts. Specifically, this entry's deployment context is *receives-external-command-input* — which AI agent frameworks routinely have at their TUI / HTTP / LLM-tool surfaces.

**The compound shape is a methodologically new observation.** The hermes-agent specimen captures **three taxonomy entries' worth of mechanism in one defect path**:

1. `shell=True` — the primary injection vector
2. `except ImportError: pass` on safety-module import — swallowed-exceptions
3. The safety module exists and is intended; the defective import + suppression makes it not run — codified-guidance-defeated-by-its-own-implementation

This compound shape is methodologically richer than any single-pattern defect. AI-typical defects *compose* — combining mechanisms produces qualitatively more severe outcomes than any individual mechanism alone.
