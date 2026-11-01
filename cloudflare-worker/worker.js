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

function instaboxHeaders(env, includeJson = false) {
  const headers = {
    Accept: "application/json",
    "X-API-Key": env.INSTABOX_API_KEY,
  };
  if (includeJson) headers["Content-Type"] = "application/json";
  return headers;
}

async function checkAndRecover(env) {
  const machineName = env.INSTABOX_MACHINE_NAME || "s";
  const apiBase = (env.INSTABOX_API_BASE_URL || "https://api.instabox.sh").replace(/\/$/, "");
  const renderUrl = (env.RENDER_WATCHDOG_URL || "https://instabox-24-7-watchdog.onrender.com/healthz").replace(/\/$/, "");
  const startedAt = Date.now();
  const result = { checkedAt: new Date().toISOString(), machine: machineName, actions: [] };

  // This request wakes a sleeping Render Free web service.
  try {
    const render = await requestJson(renderUrl);
    result.render = { ok: render.ok, status: render.status };
    if (!render.ok) result.actions.push("render_health_failed");
  } catch (error) {
    result.render = { ok: false, error: error.name === "AbortError" ? "timeout" : "request_failed" };
    result.actions.push("render_health_failed");
  }

  if (!env.INSTABOX_API_KEY) {
    result.instabox = { ok: false, error: "INSTABOX_API_KEY_not_configured" };
    result.actions.push("instabox_check_skipped");
    return { ...result, durationMs: Date.now() - startedAt };
  }

  try {
    const machine = await requestJson(
      `${apiBase}/v1/machines/${encodeURIComponent(machineName)}`,
      { headers: instaboxHeaders(env) },
    );
    const state = machine.body?.state || "unknown";
    result.instabox = { ok: machine.ok, status: machine.status, state };

    if (machine.ok && (state === "paused" || state === "suspended")) {
      const resumed = await requestJson(
        `${apiBase}/v1/machines/${encodeURIComponent(machineName)}/resume`,
        { method: "POST", headers: instaboxHeaders(env, true), body: "{}" },
      );
      result.actions.push(resumed.ok ? "resume_requested" : "resume_failed");
    } else if (machine.ok && state === "stopped" && env.AUTO_START_STOPPED === "true") {
      const started = await requestJson(
        `${apiBase}/v1/machines/${encodeURIComponent(machineName)}/start`,
        { method: "POST", headers: instaboxHeaders(env, true), body: "{}" },
      );
      result.actions.push(started.ok ? "start_requested" : "start_failed");
    }
  } catch (error) {
    result.instabox = { ok: false, error: error.name === "AbortError" ? "timeout" : "request_failed" };
    result.actions.push("instabox_check_failed");
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
