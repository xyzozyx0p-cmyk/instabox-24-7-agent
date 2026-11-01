# Instabox third watchdog on Cloudflare Workers

This Worker runs every five minutes using a Cloudflare Cron Trigger. It wakes the Render watchdog with an HTTP request, reads the Instabox machine named `s`, and requests `resume` for paused/suspended machines. It requests `start` for a stopped machine only when `AUTO_START_STOPPED=true`.

## Secrets

Configure these as Cloudflare Worker secrets; do not commit them:

```bash
npx wrangler secret put INSTABOX_API_KEY
npx wrangler secret put WORKER_AUTH_TOKEN
```

`WORKER_AUTH_TOKEN` protects the optional `/healthz` endpoint. The scheduled handler does not require it.

## Deploy

```bash
cd cloudflare-worker
npx wrangler deploy
```

Cron schedules use UTC. Cloudflare documents that Cron Trigger changes can take several minutes to propagate.

## Important limitations

This is a scheduled control plane, not a permanently running VM. Render Free services sleep after 15 minutes without inbound traffic and wake on the next HTTP request; the five-minute schedule is best-effort and is not an uptime guarantee. Instabox Free machines still enforce their 30-minute idle suspension policy. Persistent data must stay on Instabox `/data` or another durable store.
