# Claude control plane

The control plane runs locally on the main Instabox machine at `127.0.0.1:8787`. It is protected by `CONTROL_API_TOKEN` and is not exposed directly to the Internet.

## Current endpoints

- `GET /healthz` — local liveness check.
- `GET /v1/status` — list persistent tmux sessions.
- `POST /v1/sessions` — create a shell-backed tmux session.
- `POST /v1/claude/start` — start Claude Code in a persistent session.
- `POST /v1/claude/message` — send a message to Claude Code.
- `GET /v1/claude/output?session=claude` — read recent captured output.
- `POST /v1/command` — send a command to a session.
- `WS /v1/sessions/{session}/ws` — interactive terminal stream with input and output.

HTTP requests use `Authorization: Bearer <CONTROL_API_TOKEN>`. WebSocket clients should send the token as the first JSON message (`{"token":"..."}`); a query-token fallback exists for clients that cannot send a first message, but it is less private because URLs can be logged.

## Temporary SSH access

For a private local connection, forward the port over SSH:

```bash
ssh -p 2222 -L 8787:127.0.0.1:8787 USER@ssh.instabox.sh
```

Then call `http://127.0.0.1:8787` from the client. A persistent remote URL should use a named Cloudflare Tunnel plus Cloudflare Access; do not expose port 8787 directly.

The API grants SSH-like terminal capability to an authenticated caller. Keep the bearer token private, rotate it if exposed, and review commands before using an external client.
