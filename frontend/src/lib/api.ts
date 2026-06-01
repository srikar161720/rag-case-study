/**
 * Frontend API client (Phase 1 — non-streaming).
 *
 * `sendChat` posts the conversation to the same-origin Next.js proxy at
 * `/api/chat` (see `app/api/chat/route.ts`), which injects the backend
 * `X-API-Key` server-side and forwards to the FastAPI `/chat` endpoint. The
 * browser never holds the key and never talks to the backend directly.
 *
 * This is the NON-STREAMING variant: one request → one `ChatResponse`. The SSE
 * streaming client (`/api/chat/stream` + progressive `onEvent`) lands on
 * `feat/streaming` (Fork 29 Phase 2).
 *
 * Every failure mode is normalized to an `ApiError` with a stable `code` so the
 * UI (and the G10 toast layer, later) can branch on `err.code` rather than
 * parsing HTTP internals.
 */

import { ApiError, type ApiErrorCode } from "./errors";
import type { ChatMessage, ChatResponse } from "./types";

/** Map an HTTP status from the proxy/backend to a stable ApiErrorCode. */
function codeForStatus(status: number): ApiErrorCode {
  switch (status) {
    case 401:
      return "missing_api_key";
    case 403:
      return "invalid_api_key";
    case 422:
      return "validation_error";
    case 429:
      return "rate_limited";
    default:
      return "server_error";
  }
}

/**
 * Pull a human-readable message + optional retry_after out of an error body.
 * The backend's auth/validation errors come back as
 * `{ "detail": { "error", "message" } }` (FastAPI wraps HTTPException.detail),
 * while rate-limit / some handlers use a flat `{ "message", "retry_after" }`.
 * Handle both shapes defensively.
 */
function parseErrorBody(body: unknown): { message?: string; retryAfter?: number } {
  if (typeof body !== "object" || body === null) return {};
  const b = body as Record<string, unknown>;

  // FastAPI/Pydantic auto-validation errors come back as
  // `{ detail: [{ msg, loc, ... }, ...] }` (a list, not an object). Surface a
  // clean user-facing message rather than the raw Pydantic text (which is
  // developer-oriented, e.g. "String should have at most 2000 characters") —
  // this also matches the fixed-copy approach the G10 error layer will use.
  // (Checked before the object branch below because arrays are typeof "object".)
  if (Array.isArray(b.detail)) {
    return { message: "Your message couldn't be processed. Please rephrase and try again." };
  }

  const detail =
    typeof b.detail === "object" && b.detail !== null
      ? (b.detail as Record<string, unknown>)
      : undefined;

  const message =
    (typeof b.message === "string" && b.message) ||
    (detail && typeof detail.message === "string" && detail.message) ||
    undefined;

  const retryRaw = b.retry_after ?? detail?.retry_after;
  const retryAfter = typeof retryRaw === "number" ? retryRaw : undefined;

  return { message, retryAfter };
}

/**
 * Send the conversation and resolve with the assistant's `ChatResponse`.
 *
 * History hygiene: the UI's `ChatMessage` may carry a `sidecar` on assistant
 * turns, but the backend `Message` schema forbids extra fields — so we map down
 * to `{ role, content }` before sending or the backend 422s.
 *
 * @throws ApiError on any non-2xx response, network failure, or unparseable body.
 */
export async function sendChat(messages: ChatMessage[]): Promise<ChatResponse> {
  const wireMessages = messages.map((m) => ({ role: m.role, content: m.content }));

  let response: Response;
  try {
    response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: wireMessages }),
    });
  } catch {
    throw new ApiError("network_error", "Couldn't reach the server. Check your connection and retry.");
  }

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const { message, retryAfter } = parseErrorBody(body);
    throw new ApiError(
      codeForStatus(response.status),
      message ?? "Request failed. Please try again.",
      retryAfter,
    );
  }

  try {
    return (await response.json()) as ChatResponse;
  } catch {
    throw new ApiError("server_error", "The server returned an unreadable response.");
  }
}
