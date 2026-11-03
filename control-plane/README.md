# Claude control plane

The control plane runs locally on the main Instabox machine at `127.0.0.1:8787`. It is protected by `CONTROL_API_TOKEN` and is not exposed directly to the Internet.

## Current endpoints

- `GET /healthz` — local liveness check.
- `GET /v1/status` — list persistent tmux sessions.
- `GET /v1/models` — list safe provider/model aliases.
- `POST /v1/models/select` — select an alias for the next Claude session.
- `POST /v1/sessions` — create a shell-backed tmux session.
- `POST /v1/claude/start` — start Claude Code in a persistent session.
- `POST /v1/claude/message` — send a message to Claude Code.
- `GET /v1/claude/output?session=claude` — read recent captured output.
- `POST /v1/command` — send a command to a session.
- `GET /v1/files?path=` — list files under the workspace.
- `POST /v1/files/upload` — upload any file type under the workspace.
- `GET /v1/files/download?path=` — download a file from the workspace.
- `WS /v1/sessions/{session}/ws` — interactive terminal stream with input and output.

HTTP requests use `Authorization: Bearer <CONTROL_API_TOKEN>`. WebSocket clients should send the token as the first JSON message (`{"token":"..."}`); a query-token fallback exists for clients that cannot send a first message, but it is less private because URLs can be logged.

## Temporary SSH access

For a private local connection, forward the port over SSH:

```bash
ssh -p 2222 -L 8787:127.0.0.1:8787 USER@ssh.instabox.sh
```

Then call `http://127.0.0.1:8787` from the client. A persistent remote URL should use a named Cloudflare Tunnel plus Cloudflare Access; do not expose port 8787 directly.

The API grants SSH-like terminal capability to an authenticated caller. Keep the bearer token private, rotate it if exposed, and review commands before using an external client.

Providers use LiteLLM's standard `anthropic/<model>` and `openai/<model>` routes. The user-facing aliases are prefixed, for example `anthropic-claude-sonnet-4-5`, `openai-gpt-4o`, or `reformboss-glm-5.3-prime`. Provider keys stay in `/data/infra/litellm/proxy.env`; the model list never returns key values.

The local provider manager is installed at `/data/infra/litellm/providerctl.py`. Add a provider over SSH without putting the key in Git:

```bash
read -rsp 'Provider key: ' KEY; echo
printf '%s' "$KEY" | sudo -u user /data/infra/litellm/providerctl.py add anthropic \
  --protocol anthropic --api-base https://api.anthropic.com \
  --env-key ANTHROPIC_PROVIDER_API_KEY --key-stdin claude-sonnet-4-5
unset KEY
```

For an OpenAI-compatible provider, use `--protocol openai` and its `/v1` base URL. The resulting alias is `<provider>-<model>`.

File transfer is authenticated and restricted to `/data/workspace`; path traversal and paths outside that directory are rejected. Upload uses multipart form fields `path` and `file`:

```bash
curl -X POST "$API_URL/v1/files/upload" \
  -H "Authorization: Bearer $TOKEN" \
  -F path=instabox-24-7-agent/input.zip \
  -F file=@./input.zip

curl "$API_URL/v1/files/download?path=instabox-24-7-agent/output.zip" \
  -H "Authorization: Bearer $TOKEN" \
  -o output.zip
```
