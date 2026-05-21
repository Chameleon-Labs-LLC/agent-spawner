# Auth and identity — wiring logged-in users into a managed agent

How to pass a web user's identity through to an Anthropic-managed agent without leaking credentials into the session.

## The hard rule

**Never put API keys, passwords, refresh tokens, or any user-identifying secret in the system prompt, user message, or session metadata.** They persist in the session's event history, are returned by `events.list()`, and are included in compaction summaries. Anything you put there is durably readable for the life of the session — and prompt-injection attacks against agents that *can* call `events.list()` make that history reachable from inside the agent loop too.

Treat the session like a public transcript. Identity goes in via server-side state your orchestrator already controls; secrets stay out entirely.

## The three layers

| Layer | What you're passing | How |
|---|---|---|
| **User identity** | `user_id`, tier, role | Web app SSR sends `{user_id, tier, role}` to the orchestrator over a service-side channel. Orchestrator puts it in `metadata` on `sessions.create()` **and** prepends a per-run system-prompt suffix (e.g. `"You are acting on behalf of user_id=u_123, tier=pro."`). The agent uses identity for *reasoning*; the orchestrator uses it for *authorization*. |
| **OAuth third-party APIs** (GitHub, Notion, Linear, etc.) | OAuth access + refresh tokens | One Anthropic **Vault** per user — `client.beta.vaults.create(name=f"user_{user_id}")` — with credentials stored as `mcp_oauth` (see `managed-vs-local.md` → Vaults). Attach via `vault_ids` on session create. Anthropic auto-refreshes; the sandbox never sees the token. |
| **App-side data** (Stripe, your DB, internal APIs) | Server-side credentials keyed by `user_id` | Declare a custom tool on the agent. Agent emits `agent.custom_tool_use`; the orchestrator — which already knows `user_id` from layer 1 — resolves the request under its own server-side credentials and responds with `user.custom_tool_result`. The agent picks *what* to ask for; the orchestrator picks *whose* data. |

## Worked example

```python
# Orchestrator entry point. user_id and message come from your authenticated web app.
async def handle_request(user_id: str, message: str):
    session = await client.beta.sessions.create(
        agent={"type": "agent", "id": AGENT_ID, "version": AGENT_VERSION},
        environment_id=ENVIRONMENT_ID,
        vault_ids=[vault_id_for(user_id)],         # OAuth creds for this user only
        metadata={"user_id": user_id},             # identity, never secrets
    )

    # Prepend per-run identity context. The agent's persistent system lives on the agent;
    # this is a transient user-turn instruction.
    await client.beta.sessions.events.send(session.id, events=[{
        "type": "user.message",
        "content": [{"type": "text",
                     "text": f"[acting on behalf of user_id={user_id}] {message}"}],
    }])

    async for event in client.beta.sessions.events.stream(session.id):
        if event.type == "agent.custom_tool_use" and event.name == "query_user_subscriptions":
            # Orchestrator resolves user_id from its OWN state, not from event.input.
            # The model could be tricked into passing a different user_id under prompt injection.
            subs = stripe.subscriptions.list(customer=stripe_customer_for(user_id))
            await client.beta.sessions.events.send(session.id, events=[{
                "type": "user.custom_tool_result",
                "tool_use_id": event.id,
                "content": subs.to_dict(),
            }])
```

Three things to notice: `user_id` is resolved from the orchestrator's authenticated context, never from `event.input`; the Stripe key lives in the orchestrator's env, never crosses to Anthropic; the per-user Vault scopes OAuth to one tenant.

## What doesn't work

- **Pasting the user's session JWT into `user.message`** — durable leak via event history, and any user on that session can call `events.list()` and read it back.
- **Storing the user's API key in session `metadata`** — same problem. `metadata` is *visible*, not encrypted.
- **`"act as user_xyz"` in plain text with no server-side check** — prompt-injection bait. A malicious prior message can rewrite the agent's belief about which user_id it should pass to a custom tool. Always resolve identity from the orchestrator's own state, not from tool input.
- **One shared Vault for all users** — defeats the principle of least privilege. A bug in agent or orchestrator code suddenly reaches every user's GitHub.
- **Embedding API keys in the agent's persistent `system` prompt** — every session created from that agent version inherits the leak, and rotation requires bumping the agent version.
