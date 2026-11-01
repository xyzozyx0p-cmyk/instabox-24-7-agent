const DEFAULT_TIMEOUT_MS = 15_000;

function withTimeout(promise, ms = DEFAULT_TIMEOUT_MS) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), ms);
  return promise(controller.signal).finally(() => clearTimeout(timer));
}

async function requestJson(url, init = {}, timeoutMs = DEFAULT_TIMEOUT_MS) {
  return withTimeout(async (signal) => {
    const response = await fetch(url, { ...init, signal });
    const text = await response.text();
    let body = null;
    try { body = text ? JSON.parse(text) : null; } catch (_) { body = { text: text.slice(0, 500) }; }
    return { ok: response.ok, status: response.status, body };
  }, timeoutMs);
}

async function checkAndRecover(env) {
  const machineName = env.INSTABOX_MACHINE_NAME || "s";
  const renderUrl = (env.RENDER_STATUS_URL || "https://instabox-24-7-watchdog.onrender.com/status").replace(/\/$/, "");
  const startedAt = Date.now();
  const result = { checkedAt: new Date().toISOString(), machine: machineName, actions: [] };

  // This request wakes a sleeping Render Free web service and asks its watchdog
  // to check the Instabox machine using the Instabox key kept only in Render.
  try {
    const headers = { Accept: "application/json" };
    if (env.RENDER_STATUS_TOKEN) headers.Authorization = `Bearer ${env.RENDER_STATUS_TOKEN}`;
    const render = await requestJson(renderUrl, { headers });
    result.render = { ok: render.ok, status: render.status };
    result.instabox = render.body?.ok ? {
      ok: true,
      state: render.body.state || "unknown",
      runtime_ready: Boolean(render.body.runtime_ready),
    } : { ok: false, error: "render_status_failed" };
    if (!render.ok) result.actions.push("render_health_failed");
  } catch (error) {
    result.render = { ok: false, error: error.name === "AbortError" ? "timeout" : "request_failed" };
    result.actions.push("render_health_failed");
  }

  return { ...result, durationMs: Date.now() - startedAt };
}

export default {
  async scheduled(_controller, env, ctx) {
    ctx.waitUntil(checkAndRecover(env).then((result) => console.log(JSON.stringify(result))));
  },

  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (url.pathname !== "/healthz") return new Response("not found", { status: 404 });
    const expected = env.WORKER_AUTH_TOKEN;
    if (expected && request.headers.get("Authorization") !== `Bearer ${expected}`) {
      return new Response("unauthorized", { status: 401 });
    }
    const result = await checkAndRecover(env);
    return Response.json(result, { status: result.render?.ok && result.instabox?.ok ? 200 : 503 });
  },
};
