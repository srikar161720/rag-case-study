/**
 * Frontend wire types — hand-written mirror of the backend Pydantic contracts
 * in `backend/src/customs_agent/agent/contracts.py`.
 *
 * These are PLACEHOLDER types for the Phase-1 MVP. On `feat/api-contract`
 * (Day 4, G3), `frontend/src/lib/api-types.ts` is generated from the backend's
 * committed `openapi.json` via `openapi-typescript`, and this file will be
 * refactored to re-export from it. Until then, keep these in sync with
 * contracts.py by hand — the `api-contract` CI job will catch drift once codegen
 * lands.
 *
 * Naming/shape rules followed here:
 *  - Field names match the JSON keys the backend emits (snake_case).
 *  - Optional / defaulted backend fields become optional (`?`) properties.
 *  - `ToolCallTrace.args` / `result` are `Record<string, unknown>` — per-tool
 *    typing is future work (G3 nuance, see context/06-frontend.md).
 */

// ─────────────────────────────────────────────────────────────────────────────
// Request side (what the proxy forwards to POST /chat)
// ─────────────────────────────────────────────────────────────────────────────

export type Role = "user" | "assistant";

/** One turn. Mirrors backend `Message` (content capped at 2000 chars). */
export interface Message {
  role: Role;
  content: string;
}

/** POST /chat body. Mirrors backend `ChatRequest`. */
export interface ChatRequest {
  messages: Message[];
  conversation_id?: string | null;
}

// ─────────────────────────────────────────────────────────────────────────────
// Sidecar parts
// ─────────────────────────────────────────────────────────────────────────────

/** One retrieved-knowledge entry, cited via `[id]` in prose. Mirrors `Citation`. */
export interface Citation {
  id: number;
  kind: "knowledge";
  doc: string;
  section: string;
  chunk_id: string;
  snippet: string;
}

/** One recorded tool invocation. Mirrors `ToolCallTrace`. */
export interface ToolCallTrace {
  id: number;
  kind: "computation";
  name: string;
  args: Record<string, unknown>;
  result: Record<string, unknown>;
  sql_executed?: string | null;
  view_used?: "entries_v" | "entry_lines_v" | null;
  shell_entries_excluded: number;
  rows_inspected: number;
  latency_ms: number;
}

/** One default the agent applied. Mirrors `Assumption`. */
export interface Assumption {
  key: string;
  value: string;
  rule_id?: string | null;
  rule_section?: string | null;
}

/** Fork 25 — five refusal categories. Mirrors `RefusalCategory`. */
export type RefusalCategory =
  | "off_domain"
  | "out_of_range"
  | "unmapped"
  | "meta"
  | "adversarial";

/** Per-response operational metadata. Mirrors `ResponseMeta`. */
export interface ResponseMeta {
  request_id: string;
  prompt_version: string;
  model: string;
  embedding_model: string;
  temperature: number;
  iterations_used: number;
  iteration_limit_hit: boolean;
  budget_limit_hit: boolean;
  duplicate_tool_calls: number;
  input_tokens: number;
  output_tokens: number;
  cached_input_tokens: number;
  estimated_cost_usd: number;
  total_latency_ms: number;
  stream_ttft_ms?: number | null;
  history_truncated_turns?: number | null;
}

// ─────────────────────────────────────────────────────────────────────────────
// Response side
// ─────────────────────────────────────────────────────────────────────────────

/** POST /chat response body. Mirrors `ChatResponse`. */
export interface ChatResponse {
  answer: string;
  knowledge_citations: Citation[];
  tool_calls: ToolCallTrace[];
  assumptions: Assumption[];
  refused: boolean;
  refusal_category?: RefusalCategory | null;
  meta: ResponseMeta;
}

// ─────────────────────────────────────────────────────────────────────────────
// UI-only types (not part of the wire contract)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * A message as held in UI state. The optional `sidecar` is the full
 * `ChatResponse` for assistant turns (citations, tool calls, meta) and is
 * stripped before re-sending history to the backend (backend `Message` forbids
 * extra fields).
 */
export interface ChatMessage {
  role: Role;
  content: string;
  sidecar?: ChatResponse;
}
