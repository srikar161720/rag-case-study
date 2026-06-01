/**
 * Unified frontend error type (G10).
 *
 * `lib/api.ts` translates every failure mode — HTTP status codes from the
 * backend, network failures, malformed responses — into a single `ApiError`
 * with a stable `code`. The error-to-toast mapping table (`ERROR_TOAST_MAP`)
 * and the `<ErrorToast>` component land on `feat/error-boundary` (G10); Phase 1
 * just surfaces `err.message` inline. Defining the class here keeps the
 * `lib/errors.ts` home stable so the later toast work is additive.
 */

export type ApiErrorCode =
  | "missing_api_key"
  | "invalid_api_key"
  | "validation_error"
  | "rate_limited"
  | "server_error"
  | "network_error"
  | "stream_interrupted";

export class ApiError extends Error {
  constructor(
    public code: ApiErrorCode,
    message: string,
    public retryAfter?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}
