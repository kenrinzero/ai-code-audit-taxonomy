---
name: hardcoded-config-values
category: configuration
difficulty: medium
generation: evergreen
since_model: null
evidence_grade: observed
---

# Hardcoded Config Values

## Code example

```python
# agent/anthropic_adapter.py
MODEL_MAX_OUTPUT_TOKENS = {
    "claude-sonnet-4.5": 64000,
    "claude-haiku-4.5": 64000,
    ...
}


async def call_anthropic(model: str, prompt: str) -> str:
    response = await client.messages.create(
        model=model,
        max_tokens=MODEL_MAX_OUTPUT_TOKENS[model],   # hardcoded to model max
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text
```

The function works for the Anthropic API. The hardcoded 64000 is the absolute maximum the model can output; pre-flighting that ceiling at every request seems defensive — "request the most, trust the model to use only what it needs."

The defect emerges when the same code talks to OpenRouter as a proxy provider. OpenRouter's billing model *pre-reserves* the full requested `max_tokens × output rate` as collateral before allowing the call. The user with $5–$25 of credit sees:

```
HTTP 402: This request requires more credits, or fewer max_tokens.
You requested up to 64000 tokens, but can only afford 17176.
```

The actual response would have been 50–500 tokens; nothing executes, nothing is billed. The hardcoded ceiling broke the integration on the most common-by-deployment provider.

A tightened version makes `max_tokens` configurable, extending the project's existing config-resolution chain to cover it:

```python
async def call_anthropic(model: str, prompt: str, profile_config: dict) -> str:
    max_tokens = (
        profile_config.get("model", {}).get("max_tokens")
        or MODEL_MAX_OUTPUT_TOKENS.get(model, 8192)
    )
    response = await client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text
```

The user can now set `max_tokens: 8192` in their profile config to match their credit budget. The hardcoded constant remains as a fallback default. The project's existing context-window resolution chain (config override → custom per-model → cache → `/models` endpoint → registry) is extended to cover one more value.

The pattern has several visible sub-shapes in captured specimens:

- **Hardcoded-config-value-that-breaks-downstream-provider** — a literal in source code that prevents the agent from working with a particular provider's API constraints. Captured in NousResearch/hermes-agent#22879 (max_tokens hardcoded; breaks OpenRouter pre-reservation billing).
- **Hardcoded-by-omission-with-defective-default** — the code does not write an explicit value; it omits a parameter and lets the upstream library's default kick in. The default is wrong for some users. Captured in MemPalace/mempalace#1261 (no `embedding_function` passed; ChromaDB defaults to English-only `all-MiniLM-L6-v2`; non-English users get poor recall).
- **Magic-number-defaults-in-dict-get-at-scale** — `config_dict.get("key", MAGIC_NUMBER)` repeated across many sites in a module; magic numbers duplicate values in the YAML config file; misspelled keys silently fall through to the magic default. Captured in stkzlv/ContentEngineAI#125 (68 sites across 10 files in one module).
- **Hardcoded-branding-in-source** — app name, logo paths, organization identifiers hardcoded in code; blocks white-labeling. Captured in dx-dtran/unsloth#24 (referenced as adjacent shape).

All sub-shapes share the same root mechanism: the model wrote a literal value in source code where a configurable parameter (env var, config file field, CLI flag, constructor argument) would have been more appropriate.

## Mechanism

A language model generates code in response to a task description. When the task involves a numeric or string parameter, the model has two broad strategies:

1. **Hardcode the value** in the source. Simple, works for the immediate case, no plumbing required.
2. **Make the value configurable** via an env var, config file field, CLI flag, or constructor argument. Requires plumbing: declare the parameter, thread it through the call chain, document the default.

The corpus contains both strategies. What it does not contain in proportion to their *correctness* is which strategy applies when. Tutorial code uses hardcoded values for clarity ("`max_tokens=2000` to keep the example concise"). Stack Overflow answers use hardcoded values to focus the answer on the asker's question. Beginner Python code uses hardcoded values because configuration is presented as an advanced topic. Production library code uses configurable values because users need to override defaults for their context. The model has seen both forms; its prior for "what should this parameter be" defaults toward the simpler hardcoded form because the simpler form is more frequent in the corpus.

Three concrete failure paths are visible in the captured specimens:

**Path 1: Hardcoded value at API boundary that breaks downstream contracts.** The model writes `max_tokens=64000` in the Anthropic adapter because Anthropic's API allows it. The same code is later used with OpenRouter as a proxy, which has a different billing model. The hardcoded value is *correct for Anthropic direct* and *incorrect for OpenRouter*. The model did not consider the multi-provider context at generation time because the local generation context was "Anthropic adapter" — provider-specific assumptions were baked into provider-generic code.

**Path 2: Hardcoded-by-omission with an upstream library's defective default.** The model writes `client.get_or_create_collection(name, metadata={...})` without passing an `embedding_function`. The omission is invisible at the call site — readers see a normal API call. The upstream library's default takes effect: `all-MiniLM-L6-v2`, an English-only embedder. Non-English users get silently degraded results. The hardcoded value is *the default of the upstream library*, encoded by omission rather than by literal. The model's local generation step did not check what the upstream default was or whether it was the right choice.

**Path 3: Magic-number-default-in-consumer-code at scale.** The model writes `config_dict.get("download_timeout", 30)` in one place; later writes `config_dict.get("download_chunk_size", 8192)` in another place; later writes `config_dict.get("retry_attempts", 3)` and so on. Each call has a magic-number default that duplicates the YAML config. Across 68 sites, the magic numbers may agree with the YAML or may have drifted; misspelled YAML keys silently fall through to the magic default with no warning. The sticky-local-pattern observation applies: once one `dict.get` with a magic default landed, the next several inherited the pattern.

The training corpus reinforces the failure mode through pedagogical sources in particular. Tutorial code that demonstrates "here's how you use the API" uses hardcoded values because the alternative — "first set up a config system, then thread the parameter through, then call the API" — distracts from the lesson. The model has internalized "use the value directly" as the default; the "make it configurable" alternative requires recognizing the *deployment context* (library code, server code, multi-tenant code) where configurability is needed.

The defect paths vary in severity:

1. **Broken provider integration** (highest severity, captured in hermes-agent). The hardcoded value actively prevents a feature from working with a downstream system that has different constraints.
2. **Excluded user population** (captured in mempalace). The default works for some users and produces silently-degraded results for others (non-English users).
3. **Silent fallback bug class** (captured in ContentEngineAI). Misspelled YAML keys silently fall through to magic-number defaults; the misconfiguration produces no warning, no error, no test failure — just a subtly different runtime.
4. **Defaults drift** (captured in ContentEngineAI). Two declarations of the same default (one in YAML, one in code) can disagree over time. Nothing enforces consistency.
5. **No CLI/env precedence** (captured in ContentEngineAI). Standard CLI > env > config precedence cannot be applied to values that live as literals in source code.
6. **Operator can't tune without forking** (captured in mempalace). The user resorts to manual source patching after each install (`sed -i 's/64000/8192/g'`), which gets reverted on every update.

This pattern is the **configuration-time cousin of [`wrong-tool-for-job`](wrong-tool-for-job.md)**. Both stem from the model choosing a corpus-default approach when a project-specific or deployment-specific alternative would be more correct. Wrong-tool-for-job is about which library/primitive to use; this entry is about whether a value should be a literal or a config parameter.

The pattern is also the **scale-multiplied cousin of [`narrating-comments`](narrating-comments.md) and [`print-instead-of-logging`](print-instead-of-logging.md)** — three entries that demonstrate the AI-pedagogical-bias meta-family. The model produces patterns appropriate for tutorial code (narrating comments, print statements, hardcoded values) when the deployment context (production, library, server) calls for the more elaborate alternatives (concise comments, structured logging, configurable values). The unifying observation: AI-generated code is *pedagogically inflected* in ways that work for examples and fail for production.

This pattern is **AI-amplified, not AI-exclusive**. Human developers hardcode values constantly — particularly during prototyping, during exploration of a new API, or when the value is genuinely a constant. The AI-amplified observation is the *frequency* and *consistency*: AI-generated codebases produce hardcoded values across library/server/agent code at densities that exceed what human-paced development would produce, and the model does not reliably evaluate the deployment context before choosing a literal.

## Evidence / incident

Three captured specimens at three different defect-severity levels and scales. Detailed specimen notes are not included in the public repository.

- **[NousResearch/hermes-agent#22879](https://github.com/NousResearch/hermes-agent/issues/22879)** — hardcoded-config-value-breaks-downstream-provider. `max_tokens` hardcoded to model maximum (64000); OpenRouter's pre-reservation billing makes the agent unusable for moderate-credit users. Defect-direct, user-immediate-blocker. The project has a context-window resolution chain; the model did not extend it to max_tokens. **Fifth AI-typical pattern from the same codebase.**
- **[MemPalace/mempalace#1261](https://github.com/MemPalace/mempalace/issues/1261)** — hardcoded-by-omission-with-defective-default. ChromaDB call omits `embedding_function`; upstream library defaults to English-only `all-MiniLM-L6-v2`; non-English users get silently-degraded recall (80% top-1 instead of expected 90-100% with multilingual embedder). Empirical evidence on Spanish-majority content. AI memory project.
- **[stkzlv/ContentEngineAI#125](https://github.com/stkzlv/ContentEngineAI/issues/125)** — magic-number-defaults-in-dict-get-at-scale. **68 `dict.get(key, MAGIC_NUMBER)` sites** across 10 files in the scraper module. Magic-number defaults duplicate `config/scraper.yaml`; misspelled keys silently fall through. The same project has typed Pydantic config in 4 of 5 modules; the scraper is the holdout. Prior incident (issue #121) confirms the silent-fallback bug class is real.

Three different defect surfaces (broken provider integration, excluded user population, silent fallback at scale), three different AI-related project domains. Cross-context coverage is broad.

Supplementary references:

- **dx-dtran/unsloth#24** — hardcoded "Unsloth" branding strings throughout the studio frontend; blocks white-labeling. The cure is the same general pattern (extract to config via env vars), the surface is different (UI branding rather than API parameters). Adjacent shape worth noting.
- **NousResearch/hermes-agent#16831** — memory character limit hardcoded at 2,200; same project, similar shape. Suggests the pattern clusters in this codebase.
- **NousResearch/hermes-agent#2020** — platform notes hardcoded instead of configurable.

## Detection cues

What to look for in a diff or completion:

- **Numeric literals in API calls.** `max_tokens=64000`, `timeout=30`, `chunk_size=8192`. Particularly suspect when the literal represents an operational parameter (capacity, timing, retries) rather than a true semantic constant.
- **String literals naming external resources or models.** `"all-MiniLM-L6-v2"`, `"https://api.example.com"`, `"us-east-1"`, `"gpt-4o-mini"`. Particularly suspect when the choice should vary by deployment environment.
- **API calls that omit a configuration parameter.** `client.get_or_create_collection(name, metadata={...})` — no `embedding_function`. The hardcoded value is the upstream library's default, encoded by omission. Always check the upstream signature to see what defaults are being implicitly accepted.
- **`config.get("key", MAGIC_NUMBER)` patterns.** The magic number is the fallback. If the YAML key is missing or misspelled, the fallback takes effect silently. Multiple sites with the same pattern indicate a systemic shape rather than one-off hardcoding.
- **Two declarations of the same default value.** One in `config.yaml`, one in `parser.py`. Nothing enforces they agree; they can drift over time.
- **Same project has typed/configurable patterns elsewhere but uses hardcoded patterns in some modules.** The right pattern exists in the codebase; one module didn't get the migration. Same-project-knows-right-pattern observation at the configuration-handling layer.
- **Hardcoded branding, organization names, contact emails, copyright years.** Anything that would need to change for a fork, white-label deployment, or rebrand.

The diagnostic question for any candidate: *should this value vary across deployments, environments, or users?* If yes, it should be configurable. If no — if it's a true semantic constant like `MILLISECONDS_PER_SECOND = 1000` — hardcoding is correct. The model's local generation step does not perform this analysis; the audit step has to.

## Notes

**Category `configuration`.** The category captures patterns about *how the program is parameterized for different contexts*.

**Difficulty rated `medium`.** Spotting a numeric or string literal in code is trivially easy. Knowing whether it should be hardcoded (`MILLISECONDS_PER_SECOND = 1000`) or configurable (`max_tokens = 64000`) requires understanding the deployment context — who runs this code, in what environment, with what variations. A reader who knows the project's stack and user base can audit quickly; a reader who doesn't will see locally-valid code.

**The pattern is AI-amplified, not AI-exclusive.** Human developers hardcode values constantly during prototyping, exploration, and when values are genuinely constant. The AI-amplified observation is the *frequency* across deployment-context-sensitive code (libraries, servers, agents) and the *consistency* of the hardcoded-rather-than-configurable choice across many files. The 68-site scale in ContentEngineAI is a clustering signature.

**False-positive shapes.** Be cautious before flagging:

- *True semantic constants.* `MILLISECONDS_PER_SECOND = 1000`, `BYTES_PER_KILOBYTE = 1024`, `HOURS_PER_DAY = 24`. These should be hardcoded. The cue is whether the value could plausibly vary across deployments.
- *Mathematical constants and physics.* `PI = 3.14159...`, `EARTH_RADIUS_KM = 6371`, `SPEED_OF_LIGHT = 299792458`. Always correct as literals.
- *Protocol or specification constants.* HTTP status codes (`HTTP_OK = 200`), magic bytes for file formats (`PDF_MAGIC = b"%PDF-"`), well-known port numbers. The constraint comes from outside the project; the value cannot vary.
- *Values that are configurable through a parent layer.* If `process_batch(items, batch_size=100)` has `100` as a default but the caller can pass any value, the literal is a default-not-a-hardcode. Configurability is provided one layer up.
- *Genuinely-best-default that users would never want to change.* `password_min_length = 8` in a security context: users *could* change it but the security baseline argues against making it easy. Some hardcoded values are deliberate non-configurations.
- *Branding for the canonical edition of an open-source project.* Hardcoded "Django", "FastAPI", "PyTorch" in their respective projects' first-party UI is correct; the project IS Django/FastAPI/PyTorch. The pattern fires only when the project is meant to be white-labeled or rebranded.

**Mutation operator hint.** A deterministic mutation that takes a configurable parameter and replaces it with a literal produces this pattern from clean code. Variants:

- Take `max_tokens=config.max_tokens` and replace with `max_tokens=64000`
- Take `client.get_or_create_collection(name, embedding_function=ef)` and replace with `client.get_or_create_collection(name)` (encode by omission)
- Take `config.timeout` and replace with `30` (hardcode the timeout)
- Take typed Pydantic field access (`settings.retry_attempts`) and replace with `config_dict.get("retry_attempts", 3)` (move to dict.get with magic default)
- Add a magic-number default to a previously-unparameterized call

These mutations compose well with [`convention-drift`](convention-drift.md) — a project that uses typed config in some modules and magic-number-defaults in others is the canonical drift shape applied at the configuration-handling layer. The ContentEngineAI specimen explicitly demonstrates this: 4 of 5 modules use typed Pydantic, the scraper holds out.

**Connection to [`ai-pedagogical-bias`](../notes/ai-pedagogical-bias.md) note.** This entry is one of five members of the AI-pedagogical-bias meta-family alongside [`narrating-comments`](narrating-comments.md), [`print-instead-of-logging`](print-instead-of-logging.md), [`missing-network-timeout`](missing-network-timeout.md), and [`f-string-in-logger-call`](f-string-in-logger-call.md). Tutorial code uses inline literals for clarity; production code makes values configurable because deployments vary. The model defaults to the tutorial-fluent form.

**Connection to [`same-project-knows-right-pattern`](../notes/same-project-knows-right-pattern.md) note.** This entry contributes specimens at the configuration-handling layer:

- hermes-agent: project has context-window resolution chain; max_tokens does not use it
- mempalace: project has `EmbedderIdentityMismatchError` enforcement; embedder selection is not configurable
- ContentEngineAI: project has typed Pydantic config in 4/5 modules; scraper holds out

The note now spans nine entries demonstrating same-project-knows-right-pattern at varying scales (per-call-site, per-file, per-module). The mechanism is consistent: the model's prior at each generation site is independent enough to produce the wrong pattern even when the right one exists in the codebase.

**Connection to [`codified-guidance-is-insufficient`](../notes/codified-guidance-is-insufficient.md) note.** The ContentEngineAI specimen explicitly notes that the project's typed-Pydantic convention is documented and used in most of the codebase; the scraper module's failure to migrate is *despite* the documented convention. The note now spans ten+ entries.

**Connection to [`defensive-choice-with-justifying-comment`](../notes/defensive-choice-with-justifying-comment.md) note.** The mempalace specimen's omission of `embedding_function` is hardcoded-by-omission — the *absence* of the parameter is itself the choice, with no comment justifying it. The note observes that even *implicit* defensive choices participate when the upstream library's default produces a defective result and the project never marks the absence. This entry is one of 7+ in the cross-cutting note.
