# The orchestrator pattern — `--type orchestrator`

The orchestrator type scaffolds a managed agent plus the client process that drives it. This is the right shape for a typical SaaS: an Anthropic-hosted agent that calls back into your own servers for app data, deployment, billing, etc.

## What an orchestrator IS

A **client process** — Lambda, ECS task, long-running CLI, web-app backend, your laptop — that:

1. Creates a session against a pre-registered managed agent
2. Holds an SSE stream to that session
3. Sends user messages in
4. Handles `agent.custom_tool_use` events by calling out to your own services (Workers)
5. Returns `user.custom_tool_result` over the same authenticated stream
6. Surfaces the final response to whatever started the run

"Client" here means *API client*. Your code, your AWS account, your secrets. The orchestrator is the only thing in your stack that holds the Anthropic API key. Workers don't talk to Anthropic; the agent doesn't talk to your network.

## When to pick which type

| Use case | Type |
|---|---|
| Managed agent + custom tools running on YOUR servers (typical SaaS) | **`orchestrator`** |
| Local Agent SDK on your laptop, occasionally delegating to a more capable managed peer | `hybrid` |
| Just the managed-agent definition — you'll write the client elsewhere | `managed` |
| No managed agent involved; everything local | `local` |

If you found yourself reading `hybrid` and inventing a verifier proxy to sit between your servers and Anthropic, you probably wanted `orchestrator`. See [managed-vs-local.md](managed-vs-local.md) for the bridge protocol details.

## The event flow

```
web request → orchestrator → sessions.create → user.message
                                ↓
                          events.stream (SSE)
                                ↓
                  agent.custom_tool_use ─→ dispatch to Worker (HMAC)
                                          → user.custom_tool_result
                                ↓
                          session.status_idle (no pending tools)
                                ↓
                      return final text + audit
```

The HMAC leg is **orchestrator → Worker**, not Worker → Anthropic. Workers never make outbound calls to the Anthropic API; their only inbound surface is the orchestrator's HMAC-signed POST.

## What the scaffolder generates

| File | Purpose |
|---|---|
| `managed/definition.json` | POST body for `/v1/agents` — model, system, tools, mcp_servers, skills |
| `orchestrator/orchestrator.py` | SSE-stream client; sessions.create, events.stream, custom-tool dispatcher |
| `worker/worker.py` | FastAPI HTTPS server with HMAC verification; one process per host |
| `local/bridge.py` | HMAC signing primitive used by the orchestrator when calling Workers |
| `.env.example` | `ANTHROPIC_API_KEY`, `AGENT_ID`, `ENVIRONMENT_ID`, `BRIDGE_HMAC_SECRET`, `WORKER_BASE_URL` |

Per-host: `WORKER_HOST_ID` and a Worker process listening on HTTPS. Per-orchestrator: the rest.

## Setup (one time)

1. `POST /v1/environments` (config `{type: "cloud"}`) — store the returned `env_...` ID.
2. `POST /v1/agents` with `managed/definition.json` — store the returned `agent.id` **and** `agent.version`. Sessions can pin to a version; existing sessions keep their pinned version when you update.
3. Deploy `worker/worker.py` to each host. Each Worker needs `BRIDGE_HMAC_SECRET` (same value as the orchestrator) and a unique `WORKER_HOST_ID`.
4. Run the orchestrator wherever — Lambda, ECS, your laptop — with the env vars set.
5. To change the agent's behavior: `POST /v1/agents/{id}`. Each update bumps the version. Existing sessions stay pinned; new ones pick up the change. Don't create a new agent for every tweak — accumulating orphans gets messy.

## Identity passthrough

If web users initiate orchestrator runs, see [auth-and-identity.md](auth-and-identity.md) for the three-layer pattern: identity via `metadata` + system-prompt suffix, OAuth via per-user Vaults, app-side data via custom tools that resolve `user_id` from server state.

## Gotchas

- **The orchestrator holds your Anthropic API key. The Worker doesn't.** Workers can't talk to Anthropic. Don't ship the key to them.
- **Custom tool definitions live on the agent** (in `definition.json` under `tools[]`), not on the orchestrator. The orchestrator implements the *handler* for each tool; the *declaration* is part of the agent config and must be kept in sync.
- **The orchestrator's process needs to outlive the longest session you expect.** Plan for the 15-minute Lambda ceiling; if a single session might run longer, move to ECS or Step Functions with reconnect. The SSE stream has no replay — see `managed-agents-client-patterns.md` Pattern 1 for the consolidation pattern.
- **Reconnect on dropped streams** — open `events.stream`, then `events.list` to backfill, dedupe by event ID, then proceed. Pattern 1 in the canonical docs.
- **Use the correct idle gate** — `session.status_idle` alone is not "done"; the agent goes idle every time it's waiting on you for a `user.custom_tool_result`. Break only when status is `idle` *and* no custom tool calls are pending resolution (Pattern 5).
- **Don't `agents.create()` in the hot path.** Create the agent once in a setup script, persist the ID, load it at orchestrator startup. Each session create reuses the same agent.
