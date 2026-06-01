/**
 * Server-side proxy for POST /chat (Fork 29 non-streaming + Fork 48 auth).
 *
 * The browser posts here (same origin); this Node route injects the backend
 * `X-API-Key` from a server-only env var and forwards to the FastAPI `/chat`
 * endpoint. The key never reaches the browser — `lib/api.ts` calls this route,
 * not the backend directly.
 *
 * Env (server-side only; no NEXT_PUBLIC_ prefix — see frontend/.env.example):
 *   BACKEND_URL      — backend origin (e.g. https://customs-agent-backend.fly.dev)
 *   BACKEND_API_KEY  — static key forwarded as X-API-Key
 *
 * The SSE streaming proxy (`/api/chat/stream`) lands on `feat/streaming`.
 */

import { NextRequest } from "next/server";

export const runtime = "nodejs"; // Vercel function (iad1)
export const dynamic = "force-dynamic"; // never cache chat responses

export async function POST(req: NextRequest) {
  const backendUrl = process.env.BACKEND_URL;
  const apiKey = process.env.BACKEND_API_KEY;

  // Misconfiguration guard: fail with a clear 500 rather than fetching
  // `undefined/chat` and surfacing an opaque network error to the client.
  if (!backendUrl || !apiKey) {
    return Response.json(
      {
        error: "proxy_misconfigured",
        message: "Server is missing BACKEND_URL or BACKEND_API_KEY.",
      },
      { status: 500 },
    );
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${backendUrl}/chat`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-API-Key": apiKey,
      },
      body: await req.text(),
    });
  } catch {
    // Backend unreachable (down, DNS, timeout) — normalize to 502 JSON so the
    // client maps it to a server_error rather than a confusing network_error.
    return Response.json(
      { error: "backend_unreachable", message: "Could not reach the backend service." },
      { status: 502 },
    );
  }

  // Forward the backend response body + status. We deliberately rebuild a
  // minimal header set rather than copying all upstream headers: blindly
  // forwarding Content-Length / Content-Encoding / Transfer-Encoding while
  // re-piping the body can corrupt the response, and the backend's
  // browser-oriented security headers (X-Frame-Options, HSTS) don't belong on
  // this fetch-consumed JSON proxy response (and HSTS shouldn't be asserted for
  // the Vercel origin from here). We DO forward Retry-After so a 429 still tells
  // the client how long to back off. Non-streaming, so the body is JSON either way.
  const headers: Record<string, string> = {
    "Content-Type": upstream.headers.get("Content-Type") ?? "application/json",
    "Cache-Control": "no-cache",
  };
  const retryAfter = upstream.headers.get("Retry-After");
  if (retryAfter) headers["Retry-After"] = retryAfter;

  return new Response(upstream.body, {
    status: upstream.status,
    headers,
  });
}
