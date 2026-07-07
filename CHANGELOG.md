# Changelog

All notable changes to **agent-spawner** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Post-merge review fixes for PR #2 (FleetView telemetry spool-append).

### Fixed
- **Channel-less local/hybrid bundles no longer crash on the first message.**
  The scaffolder now always writes `channels/__init__.py`, `channels/exfil.py`,
  and `channels/telemetry.py` for `--type local`/`hybrid`, even with
  `--channels none`; previously `local/agent.py` imported `channels.telemetry`
  and `channels.exfil` unconditionally but the package was only scaffolded when
  channel adapters were configured (`ModuleNotFoundError` in `handle_message`).
  The telemetry import in the agent template is also guarded with a no-op
  fallback so pre-existing bundles keep working.
- **`session_end` now fires on error paths.** `handle_message` records
  `session_end` with `{"reason": "error"}` when any pipeline stage raises, so
  failed sessions no longer sit "live" in FleetView forever.
- Telemetry's session-info block is now keyed on `etype == "session_start"`
  instead of a process-lifetime `_started` set — removes unbounded growth and
  the stranded-session-info case when the first spool write failed.

### Changed
- **Assistant-reply excerpts are no longer shipped to FleetView by default.**
  The `message` telemetry event now records the reply length; the scrubbed
  500-char excerpt is included only when `TELEMETRY_LOG_CONTENT=1` (documented
  in `.env.example`, matching the `AUDIT_LOG_CONTENT` precedent).

### Added
- `tests/test_scaffold_smoke.py` — scaffolds local (with/without channels) and
  hybrid bundles into a tmpdir, byte-compiles every rendered `.py`, and asserts
  every `channels.*` import in the rendered agent resolves. Run via `just test`.

## [0.1.1] — 2026-05-24

The "Managed Agents API correctness" cycle (PR #1): corrected the Managed
Agents API surface, added the recommended `orchestrator` agent type, and
rewrote the reference docs to match how Managed Agents actually work.

### Added
- **New `--type orchestrator` scaffold** — the recommended Managed Agents SaaS
  shape: a managed agent plus a client process that holds the SSE stream,
  dispatches `agent.custom_tool_use` events to remote workers over the HMAC
  bridge, and returns `user.custom_tool_result`.
  - `orchestrator.py.tmpl` — `AsyncAnthropic` client with fail-fast env,
    lossless reconnect (`events.list` backfill + `events.stream` + dedupe by
    id), the Pattern 5 idle gate, and Pattern 9 custom-tool dispatch over HMAC.
    Accepts an optional `user_id` for identity passthrough into session metadata.
  - `worker.py.tmpl` — FastAPI worker with an open `/health` and an
    HMAC-verified `/execute` (constant-time compare + 60s skew window + nonce
    LRU), a sample tool registry, and an audit log that records input keys only.
- **Reference guides**
  - `references/orchestrator-pattern.md` — the orchestrator/worker architecture
    and four-type comparison table.
  - `references/auth-and-identity.md` — three-layer pattern for threading
    authenticated web users through to a managed agent; hard rule against
    putting credentials/identity tokens in prompts, messages, or session
    metadata.
- Scaffolder now writes **both** a committed `.env.example` (placeholders) and a
  gitignored `.env` (real generated secrets), fixing the prior leak where the
  HMAC secret landed in the committed file.

### Changed
- `references/managed-vs-local.md` rewritten to document what Managed Agents
  actually is (Agents + Environments + Sessions), how custom-tool events flow
  over the SSE stream, and what the HMAC bridge is really for.
- `README.md` now leads with a four-type comparison table and the orchestrator
  layout as the primary example; cross-links the new references and notes the
  hybrid-bridge HMAC gotcha.
- `SKILL.md` updated: type list includes `orchestrator`, per-type run
  instructions, and the hybrid clarification warning against pointing
  `DELEGATE_URL` directly at Anthropic.
- `scaffold_agent.py`: `VALID_TYPE` adds `orchestrator`; env/setup/bridge helper
  blocks branch on type; managed setup now walks through the previously-missing
  Environment-creation step using the correct `/v1/agents` endpoint with
  `x-api-key` + `anthropic-version` headers.

### Fixed
- **Managed Agents API surface** — templates referenced a non-existent
  `/v1/managed-agents` endpoint and wrong field names. Corrected to `/v1/agents`,
  `system` (not `system_prompt`), default model `claude-opus-4-7`, and
  `agent_toolset_20260401` by default; dropped the spurious `max_tokens`.
- **Orchestrator template `events.stream()` await shape** — `events.stream()`
  returns an `AsyncStream` (await + iterate), not an async context manager; the
  old `async with … as stream:` form raised `AttributeError` on first SDK call.
- **Pattern 5 idle gate** — break only when `stop_reason.type` is `end_turn` or
  `retries_exhausted`, so the loop no longer races against the post-tool-result
  idle (e.g. `requires_action`).
- `bridge.py.tmpl` docstring clarified that HMAC headers are not validated by
  Anthropic; renamed `_sign` to `sign` for reuse by the orchestrator.

## [0.1.0] — 2026-04-15

Initial public release.

### Added
- `agent-spawner` skill that scaffolds Claude agents (managed / local / hybrid)
  with channel adapters (Telegram / Slack / Discord), HMAC-signed bridges
  between local and managed agents, IDE run configs (JetBrains + VSCode),
  systemd / Windows Task Scheduler autostart units, and SCP/SSH deploy to a
  Linux host.
- Scripts: `scaffold_agent.py`, `package_agent.py`, `deploy.sh`.
- Reference docs: architecture, channels, deploy, IDE integration,
  managed-vs-local.
- Templates for agents, bridge, channel adapters, persona, IDE configs, and
  autostart units.
- `justfile` task runner, `.env.example`, and MIT `LICENSE`.

### Fixed
- Restructured as a proper Claude Code plugin: added `.claude-plugin/plugin.json`
  and moved the skill to `<repo-root>/skills/` so the marketplace plugin loader
  discovers it (2026-04-16).

[Unreleased]: https://github.com/Chameleon-Labs-LLC/agent-spawner/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/Chameleon-Labs-LLC/agent-spawner/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/Chameleon-Labs-LLC/agent-spawner/releases/tag/v0.1.0
