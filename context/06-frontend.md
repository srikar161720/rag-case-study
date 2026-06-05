# Frontend

Authoritative source for the Next.js App Router application: chat UI,
empty state, citation rendering, "Sources & Computation" panel,
streaming consumer, `localStorage` persistence, conversation reset,
error handling, error boundary, page metadata, `PROMPT_VERSION` drift
badge, mobile-responsive strategy, and the SSE background-tab caveat.

Load this file when working on `frontend/src/`. For the API contract,
see `05-api-and-backend.md`. For the data shapes (`ChatResponse`,
`Citation`, `ToolCallTrace`, `Assumption`, `ResponseMeta`), see
`04-agent-and-tools.md`.

---

## Stack (Fork 6, 13)

- **Framework**: Next.js (App Router) — Vercel-native, server-route
  primitives for the proxy pattern (Fork 29), modern streaming support.
- **UI library**: shadcn/ui (Radix primitives + Tailwind classes) —
  accessible by default, copy-into-repo (no runtime dep), fits the
  "production-grade demo" aesthetic.
- **Styling**: Tailwind CSS — utility-first, fast iteration, works with
  the dev/prod parity story.
- **Markdown rendering**: `react-markdown` + `remark-gfm` for tables,
  with a custom plugin that transforms `[N]` citation markers into
  `<CitationMarker>` components.
- **Package manager**: `pnpm` 9.x (G13), pinned via `packageManager`
  field + `engines.node >= 20`.
- **TypeScript**: strict mode; types for the API contract are generated
  from the backend's OpenAPI spec via `openapi-typescript` (G3).

---

## File Layout

```
frontend/
├── package.json                              ← packageManager: pnpm@9.x.x; engines.node >= 20
├── pnpm-lock.yaml
├── pnpm-workspace.yaml                       (optional; not needed for single-package frontend)
├── tsconfig.json                             ← strict mode
├── next.config.mjs
├── tailwind.config.ts
├── postcss.config.mjs
├── vitest.config.ts                          ← G2 — Vitest unit tests for src/lib/
├── vercel.json                               ← regions: ["iad1"]
├── .env.example                              ← BACKEND_URL, BACKEND_API_KEY
├── public/
│   ├── favicon.ico                           ← G22 — USER-PROVIDED ASSET (16×16+)
│   └── og-image.png                          ← G22 — USER-PROVIDED ASSET (1200×630)
├── README.md                                 ← brief: pointer to root Makefile
└── src/
    ├── app/
    │   ├── layout.tsx                        ← metadata export + <ErrorBoundary> wrap + <Toaster />
    │   ├── page.tsx                          ← root chat route → <Chat />
    │   ├── globals.css                       ← Tailwind base + shadcn theme tokens
    │   └── api/
    │       └── chat/
    │           ├── route.ts                  ← POST /api/chat (non-streaming proxy)
    │           └── stream/
    │               └── route.ts              ← POST /api/chat/stream (SSE proxy)
    ├── components/
    │   ├── ui/                               ← shadcn primitives (Button, Sheet, HoverCard, Toast, Collapsible, Badge)
    │   ├── Chat.tsx                          ← main chat container
    │   ├── EmptyState.tsx                    ← Fork 30 — 6 starter chips
    │   ├── MessageBubble.tsx                 ← prose + AgentPanel + version badge (G25)
    │   ├── AgentPanel.tsx                    ← Fork 31 — collapsible Sources & Computation
    │   ├── CitationMarker.tsx                ← Fork 32 — inline color-coded pill
    │   ├── ConversationSidebar.tsx           ← Fork 33 Phase 2 (multi-conversation list)
    │   ├── ErrorBoundary.tsx                 ← G20
    │   ├── ErrorToast.tsx                    ← G10 toast variants
    │   └── Header.tsx                        ← brand + "+ New chat" + sidebar toggle
    └── lib/
        ├── api.ts                            ← API client (calls /api/chat[/stream] on own origin)
        ├── api-types.ts                      ← G3 — GENERATED from openapi.json; do not edit
        ├── sse.ts                            ← SSE event parser (Fork 29 consumer)
        ├── storage.ts                        ← localStorage helpers (Fork 7 + Fork 33)
        ├── citations.ts                      ← [N] marker resolution + react-markdown plugin
        ├── errors.ts                         ← G10 — ApiError + toast mapping table
        ├── types.ts                          ← hand-written frontend-only types (re-exports api-types)
        └── *.test.ts                         ← Vitest unit tests for the pure-function modules (G2)
```

`api-types.ts` is **generated** (G3) — `linguist-generated=true` in
`.gitattributes` so GitHub collapses its diff in PR review. Never edit
by hand; regenerate via `make types`.

---

## Server-Side Proxy (Fork 29 + 48)

All browser → backend traffic flows through Next.js server routes that
inject the backend `X-API-Key` from server-side env. **The browser
never holds the key.**

### Non-streaming proxy

```ts
// frontend/src/app/api/chat/route.ts
import { NextRequest } from "next/server";

export const runtime = "nodejs";       // Vercel function (iad1)
export const dynamic = "force-dynamic"; // no caching

export async function POST(req: NextRequest) {
  const backendUrl = process.env.BACKEND_URL!;
  const apiKey     = process.env.BACKEND_API_KEY!;

  const upstream = await fetch(`${backendUrl}/chat`, {
    method:  "POST",
    headers: {
      "Content-Type": "application/json",
      "X-API-Key":     apiKey,
    },
    body: await req.text(),
  });

  return new Response(upstream.body, {
    status:  upstream.status,
    headers: {
      "Content-Type":  upstream.headers.get("Content-Type") ?? "application/json",
      "Cache-Control": "no-cache",
    },
  });
}
```

### Streaming proxy (SSE)

```ts
// frontend/src/app/api/chat/stream/route.ts
import { NextRequest } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  const backendUrl = process.env.BACKEND_URL!;
  const apiKey     = process.env.BACKEND_API_KEY!;

  const upstream = await fetch(`${backendUrl}/chat/stream`, {
    method:  "POST",
    headers: {
      "Content-Type": "application/json",
      "X-API-Key":     apiKey,
    },
    body: await req.text(),
  });

  // 4xx / 5xx come back as a single JSON body, not SSE — forward as-is.
  if (!upstream.ok) {
    return new Response(upstream.body, {
      status:  upstream.status,
      headers: { "Content-Type": "application/json" },
    });
  }

  return new Response(upstream.body, {
    status: 200,
    headers: {
      "Content-Type":     "text/event-stream",
      "Cache-Control":    "no-cache",
      "Connection":       "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
```

### Env variable hygiene (Fork 39)

Vercel project env vars, server-side only (no `NEXT_PUBLIC_` prefix —
that would bundle them into the client JavaScript):

| Variable | Production scope | Preview scope | Development scope |
|---|---|---|---|
| `BACKEND_URL` | `https://customs-agent-backend.fly.dev` | same as production | `http://localhost:8080` |
| `BACKEND_API_KEY` | (set value) | same as production | from local `.env.local` |

`frontend/.env.example` carries the names + a comment block explaining
that variables prefixed with `NEXT_PUBLIC_` would be bundled to the
browser, and we deliberately have none.

> **As-built note (`feat/web-mvp`)**: the committed `.env.example`
> originally declared the URL as `NEXT_PUBLIC_BACKEND_URL` (a scaffold
> typo) while this spec + the proxy route both use server-side-only
> `BACKEND_URL`. Renamed to `BACKEND_URL` on-branch so the proxy's
> `process.env.BACKEND_URL` resolves (a `NEXT_PUBLIC_`-prefixed name is
> a different variable and would read `undefined` server-side). The
> browser never needs it — all traffic flows through the same-origin
> `/api/chat` proxy.

---

## Chat Container (`<Chat>`)

```tsx
// frontend/src/components/Chat.tsx (sketch)
"use client";

import { useEffect, useReducer, useRef } from "react";
import { EmptyState } from "./EmptyState";
import { MessageBubble } from "./MessageBubble";
import { Header } from "./Header";
import { sendChat } from "@/lib/api";
import { loadActiveConversation, saveActiveConversation } from "@/lib/storage";

type ChatMessage = {
  role: "user" | "assistant";
  content: string;
  sidecar?: ChatResponse;   // present only on assistant messages
};

type State = {
  messages: ChatMessage[];
  isStreaming: boolean;
  isHydrated: boolean;
};

export function Chat() {
  const [state, dispatch] = useReducer(reducer, initialState);

  // Hydrate from localStorage on mount (Fork 7)
  useEffect(() => {
    const stored = loadActiveConversation();
    if (stored) dispatch({ type: "HYDRATE", messages: stored.messages });
    else        dispatch({ type: "HYDRATE", messages: [] });
  }, []);

  // Persist on every change after hydration (Fork 7)
  useEffect(() => {
    if (state.isHydrated) saveActiveConversation(state.messages);
  }, [state.messages, state.isHydrated]);

  const handleSubmit = async (text: string) => {
    dispatch({ type: "USER_MESSAGE", content: text });
    dispatch({ type: "STREAM_START" });

    try {
      await sendChat({
        messages: [...state.messages, { role: "user", content: text }],
        onEvent: (ev) => dispatch({ type: "SSE_EVENT", ev }),
      });
    } catch (err) {
      // G10 — converted to ApiError + toast inside sendChat
      dispatch({ type: "STREAM_ERROR", err });
    } finally {
      dispatch({ type: "STREAM_END" });
    }
  };

  return (
    <div className="flex h-[100dvh] flex-col">                {/* G34 — dvh for iOS */}
      <Header onNewChat={() => dispatch({ type: "NEW_CHAT" })} />
      <main className="flex-1 overflow-y-auto px-4 sm:px-6">
        {state.messages.length === 0 && state.isHydrated && (
          <EmptyState onPick={(prompt) => handleSubmit(prompt)} />
        )}
        {state.messages.map((m, i) => (
          <MessageBubble key={i} message={m} isStreaming={state.isStreaming && i === state.messages.length - 1} />
        ))}
      </main>
      <ChatInput onSubmit={handleSubmit} disabled={state.isStreaming} />
    </div>
  );
}
```

Real implementation will use `useReducer` for state management (richer
than `useState` for the multi-event progressive update from the SSE
stream), but the sketch shows the lifecycle: hydrate → render → submit
→ stream events into the last assistant bubble → persist on every
change.

> **As-built note (`feat/web-mvp` Phase 1)**: the shipped MVP is
> **non-streaming**. The sketch above (and the `sendChat({messages,
> onEvent})` SSE signature in the "Error Handling" section below) shows
> the *eventual* streaming shape; Phase-1 `lib/api.ts` instead does a
> plain `sendChat(messages): Promise<ChatResponse>` — one `POST
> /api/chat` → one full JSON response rendered when complete — and the
> reducer uses `isLoading` (a "Thinking…" indicator) rather than
> progressive `SSE_EVENT` dispatch. SSE streaming (`/chat/stream`,
> `lib/sse.ts`, progressive panel) lands on `feat/streaming` (Day 6,
> Fork 29 Phase 2). The empty state on Phase 1 is a minimal centered
> heading — the starter chips (Fork 30, below) are a later branch.
> `lib/api.ts` also strips the assistant `sidecar` to `{role, content}`
> before re-sending history (backend `Message` is `extra="forbid"`).

---

## Empty State with Starter Chips (Fork 30)

```tsx
// frontend/src/components/EmptyState.tsx
"use client";
import useSWR from "swr";
import { fetcher } from "@/lib/api";

type StarterPrompt = { label: string; tier: number | "meta" };

export function EmptyState({ onPick }: { onPick: (q: string) => void }) {
  const { data: prompts } = useSWR<StarterPrompt[]>("/api/starter-prompts", fetcher);

  return (
    <div className="flex flex-col items-center gap-6 mt-16">
      <h1 className="text-2xl font-medium">Ask anything about customs data</h1>
      <p className="text-sm text-muted-foreground">
        MHF · PCA · SAG &mdash; Oct 2024 to Mar 2025
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-w-2xl w-full">
        {prompts?.map((p) => (
          <button
            key={p.label}
            type="button"
            onClick={() => onPick(p.label)}
            className="text-left p-3 rounded-lg border hover:bg-accent transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
            aria-label={`Try: ${p.label}`}
          >
            {p.label}
          </button>
        ))}
      </div>
    </div>
  );
}
```

### The 6 starter chips

Defined in `backend/config/starter_prompts.py`, served via
`/api/starter-prompts`. Curated to span all 4 tiers + meta without
copying the 11 graded questions verbatim (so it's clear the agent
generalizes, not teaches-to-test):

1. *"How many entries for MHF in November 2024?"* (Tier 1)
2. *"IEEPA exposure for PCA in February 2025"* (Tier 2)
3. *"Compare hold rates across all three customers"* (Tier 3)
4. *"Generate a QBR for MHF for Q4 2024"* (Tier 3)
5. *"What does 'on hold' mean?"* (Tier 4 — meta/knowledge lookup)
6. *"What questions can I ask?"* (meta)

Click → populate input + auto-submit. After the first user message, the
empty state hides (chat takes over). "+ New chat" (in `Header`)
restores it.

---

## Citation Pills (Fork 32)

Subtle color-coded pill markers rendered in prose. Blue for knowledge
citations, green for tool computations. Shared `[N]` number space (per
Fork 28).

```tsx
// frontend/src/components/CitationMarker.tsx
"use client";
import { cn } from "@/lib/utils";
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/hover-card";

type Props = {
  id: number;
  kind: "knowledge" | "computation";
  preview: { title: string; body: string };   // first line + snippet
  onActivate: () => void;
};

export function CitationMarker({ id, kind, preview, onActivate }: Props) {
  return (
    <HoverCard openDelay={200}>
      <HoverCardTrigger asChild>
        <button
          onClick={onActivate}
          aria-controls={`citation-${id}`}
          aria-label={`Citation ${id}: ${kind}`}
          className={cn(
            "inline-flex items-center justify-center px-1.5 py-0.5 mx-0.5",
            "text-xs font-medium rounded leading-none",
            "focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
            kind === "knowledge"
              ? "bg-blue-100 text-blue-700 hover:bg-blue-200 dark:bg-blue-900/40 dark:text-blue-300"
              : "bg-emerald-100 text-emerald-700 hover:bg-emerald-200 dark:bg-emerald-900/40 dark:text-emerald-300"
          )}
        >
          [{id}]
        </button>
      </HoverCardTrigger>
      <HoverCardContent className="w-80">
        <div className="text-sm font-medium">{preview.title}</div>
        <div className="mt-2 text-sm text-muted-foreground line-clamp-3">{preview.body}</div>
        <div className="mt-2 text-xs text-muted-foreground">Click to view full details</div>
      </HoverCardContent>
    </HoverCard>
  );
}
```

### Marker resolution

A `react-markdown` plugin walks the prose and transforms every `[N]`
text token into a `<CitationMarker>`:

```ts
// frontend/src/lib/citations.ts
import type { Citation, ToolCallTrace } from "./types";

export type ResolvedCitation = {
  id: number;
  kind: "knowledge" | "computation";
  preview: { title: string; body: string };
  ref: Citation | ToolCallTrace;
};

export function resolveMarker(
  id: number,
  citations: Citation[],
  toolCalls: ToolCallTrace[],
): ResolvedCitation | null {
  const k = citations.find((c) => c.id === id);
  if (k) return {
    id, kind: "knowledge",
    preview: { title: `${k.doc} ${k.section}`, body: k.snippet },
    ref: k,
  };
  const t = toolCalls.find((c) => c.id === id);
  if (t) return {
    id, kind: "computation",
    preview: { title: `${t.name}(${prettyArgs(t.args)})`, body: prettyResult(t.result) },
    ref: t,
  };
  return null;
}
```

Markers whose ID doesn't resolve are skipped (backend already strips
orphans per Fork 28; this is defense-in-depth).

### Click behavior (Fork 32)

Click → auto-expand `<AgentPanel>` if collapsed → scroll to the matching
item → add `.highlight-flash` class for 1.5s. The killer interaction
that makes "Sources & Computation" feel like a real citation system.

### Mobile (Fork 34)

The `<HoverCard>` gates behind `(hover: hover)` media query; on touch
devices, single-tap = jump-to-panel (no hover preview step).

---

## Show-Work Panel (Fork 31)

Collapsible per-message disclosure with three sections + Run Info.

```tsx
// frontend/src/components/AgentPanel.tsx (sketch)
"use client";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { ChevronDown, BookOpen, Calculator, AlertCircle } from "lucide-react";

import type { ChatResponse } from "@/lib/types";

export function AgentPanel({ sidecar }: { sidecar: ChatResponse }) {
  const total = sidecar.knowledge_citations.length + sidecar.tool_calls.length + sidecar.assumptions.length;
  if (total === 0 && !sidecar.refused) return null;   // nothing to show

  return (
    <Collapsible className="mt-2">
      <CollapsibleTrigger className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground">
        <ChevronDown className="h-4 w-4 transition-transform [&[data-state=open]]:rotate-180" />
        Sources & Computation
        <Badge variant="secondary">{total}</Badge>
      </CollapsibleTrigger>
      <CollapsibleContent className="mt-2 space-y-3 border-l-2 pl-3">
        {sidecar.knowledge_citations.length > 0 && (
          <KnowledgeSection items={sidecar.knowledge_citations} />
        )}
        {sidecar.tool_calls.length > 0 && (
          <ComputationsSection items={sidecar.tool_calls} />
        )}
        {sidecar.assumptions.length > 0 && (
          <AssumptionsSection items={sidecar.assumptions} />
        )}
        <RunInfo meta={sidecar.meta} />
      </CollapsibleContent>
    </Collapsible>
  );
}
```

Three sections + Run Info, each with conventions:

| Section | Default | Content |
|---|---|---|
| **Knowledge Sources** (📚) | Expanded within open panel | `doc §section_title` header + 150-char snippet (truncated with "Show more") + clickable `[N]` badge |
| **Computations** (⚙) | Expanded within open panel | `tool_name(args)` header + result summary + collapsed SQL (under `▾ SQL`) + footer `view · rows · latency · shells_excluded` |
| **Assumptions** (⚠️) | Expanded within open panel | Flat bullet list; each links to the rule that justifies it (via `rule_id` → opens matching Knowledge entry) |
| **Run Info** | Collapsed within open panel | `iterations · tokens (input/output/cached) · cost · latency · prompt_version` |

### Streaming-aware (Fork 29 Phase 2)

The panel updates progressively as SSE events arrive:

- `event: knowledge_retrieved` → populate Knowledge Sources section immediately (before any tool runs)
- `event: tool_call_started` → add a Computation item with a spinner: `Running query_entries…`
- `event: tool_call_completed` → replace spinner with check + duration + result summary
- `event: complete` → final sidecar reconciles all in-progress UI state with canonical data

Default state: **expanded during streaming** so the reviewer watches
the agent "think"; auto-collapses ~2s after `complete` arrives unless
the user has interacted with it.

### Empty-state hiding

Sections with zero items hide themselves rather than showing
"(none)" — keeps the panel clean for Tier 1 questions that have one
tool call and zero KB citations.

### Refusal rendering (Fork 25)

When `sidecar.refused === true`, the panel replaces the three sections
with a single line: `Refused: <refusal_category>`. Run Info stays
visible (still has tokens/latency/version data).

---

## Streaming Consumer (Fork 29)

Frontend-side SSE parsing lives in `lib/sse.ts` (G2 — covered by
Vitest tests). The parser handles buffering across chunk boundaries,
dispatches each event type to a handler, and provides typed payloads.

```ts
// frontend/src/lib/sse.ts (sketch)
type SSEEvent =
  | { type: "token";                payload: { delta: string } }
  | { type: "knowledge_retrieved";  payload: { chunks: ChunkSummary[] } }
  | { type: "tool_call_started";    payload: { id: number; name: string; args: Record<string, unknown> } }
  | { type: "tool_call_completed";  payload: { id: number; result_summary: string; latency_ms: number } }
  | { type: "complete";             payload: ChatResponse }
  | { type: "error";                payload: { code: string; message: string; retry_after?: number } };

export async function* parseSSEStream(
  reader: ReadableStreamDefaultReader<Uint8Array>,
): AsyncGenerator<SSEEvent> {
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let boundary: number;
    while ((boundary = buffer.indexOf("\n\n")) !== -1) {
      const rawEvent = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const parsed = parseRawEvent(rawEvent);
      if (parsed) yield parsed;
    }
  }
}

function parseRawEvent(raw: string): SSEEvent | null {
  // Lines:  event: <name>\ndata: <json>
  const lines = raw.split("\n");
  let name = "", data = "";
  for (const line of lines) {
    if (line.startsWith("event: ")) name = line.slice(7).trim();
    else if (line.startsWith("data: ")) data = line.slice(6);
  }
  if (!name || !data) return null;
  try {
    return { type: name, payload: JSON.parse(data) } as SSEEvent;
  } catch {
    return null;
  }
}
```

### TTFT capture

The frontend can measure time-to-first-token client-side:

```ts
// In sendChat:
const t0 = performance.now();
for await (const ev of parseSSEStream(reader)) {
  if (ev.type === "token" && firstTokenAt === null) {
    firstTokenAt = performance.now() - t0;
    // Could emit a navigator.sendBeacon to a /metrics endpoint;
    // alternatively, the backend already records this in Langfuse trace
    // metadata (stream.ttft_ms) per Fork 52.
  }
  onEvent(ev);
}
```

---

## `localStorage` Persistence (Fork 7 + Fork 33)

Backend is stateless (Fork 7); frontend holds all conversation state in
`localStorage` so refresh-survival works without any backend infra.

### Storage shape (Phase 1)

```ts
// frontend/src/lib/storage.ts
const ACTIVE_KEY = "customs-agent.activeConversation";

type StoredConversation = {
  id: string;            // UUID, generated on first message
  title: string;         // first 40 chars of first user message
  createdAt: string;     // ISO
  updatedAt: string;
  messages: ChatMessage[];   // includes the sidecar on assistant messages
};

export function loadActiveConversation(): StoredConversation | null {
  try {
    const raw = localStorage.getItem(ACTIVE_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as StoredConversation;
  } catch {
    return null;   // Private mode or quota exceeded — degrade to in-memory
  }
}

export function saveActiveConversation(messages: ChatMessage[]) {
  if (messages.length === 0) {
    localStorage.removeItem(ACTIVE_KEY);
    return;
  }
  const existing = loadActiveConversation();
  const now = new Date().toISOString();
  const conv: StoredConversation = {
    id:        existing?.id ?? crypto.randomUUID(),
    title:     existing?.title ?? messages[0].content.slice(0, 40),
    createdAt: existing?.createdAt ?? now,
    updatedAt: now,
    messages,
  };
  try {
    localStorage.setItem(ACTIVE_KEY, JSON.stringify(conv));
  } catch (e) {
    // QuotaExceededError → trim oldest turn pairs and retry
    handleQuotaExceeded(conv);
  }
}
```

### Phase 2 extension (Fork 33 Phase 2)

Multiple conversations with a sidebar list, auto-pruned at 50 entries:

```ts
const LIST_KEY     = "customs-agent.conversations";
const ACTIVE_ID    = "customs-agent.activeId";

// loadConversations(), saveConversation(id, …), listConversations(),
// deleteConversation(id), pruneOldest()
```

Same per-conversation shape as Phase 1. Phase 1 → Phase 2 is additive
(Phase 1 storage key keeps working as a separate "currently active"
pointer; sidebar reads `LIST_KEY`).

### Failure modes (handled gracefully)

| Failure | Behavior |
|---|---|
| `localStorage` disabled (Safari Private Mode) | Catch `SecurityError` in try/catch; fall back to in-memory state; one-time toast: "Private browsing detected — conversation won't persist across refreshes." |
| Quota exceeded | Prune oldest 10 conversations (Phase 2) or oldest 5 turn pairs from active (Phase 1); retry once |
| Stale conversation with old `prompt_version` | Load anyway; surface drift badge per G25 |
| User refreshes mid-stream | Streaming buffered into in-memory state only on `event: complete`; partial response is lost on refresh — documented as a known limitation |

---

## Conversation Reset (Fork 33)

### Phase 1 — Always ships

`Header` has a "+ New chat" button. Click handler:

```ts
function handleNewChat() {
  if (state.messages.length > 5) {
    if (!confirm("Start a new chat? Your current conversation will be cleared.")) return;
  }
  localStorage.removeItem(ACTIVE_KEY);
  dispatch({ type: "NEW_CHAT" });   // clears state.messages, re-renders empty state
}
```

Optional confirmation modal only when there are >5 messages to lose.

### Phase 2 — If time permits (Fork 57 cut candidate)

Collapsible sidebar with multi-conversation list:

```tsx
// frontend/src/components/ConversationSidebar.tsx
// Desktop: persistent left sidebar
// Mobile: shadcn <Sheet> slide-over via hamburger trigger

<aside className="hidden lg:flex w-64 flex-col border-r">
  <Button onClick={onNewChat}><Plus />New chat</Button>
  <ScrollArea>
    {conversations.map((c) => (
      <ConversationItem key={c.id} conv={c} active={c.id === activeId} onSelect={...} onDelete={...} />
    ))}
  </ScrollArea>
</aside>

<Sheet>
  {/* Mobile equivalent */}
  ...
</Sheet>
```

Each item: `title` (40-char from first message) + relative timestamp.
Hover/swipe → delete (with confirmation). Active item highlighted.

---

## Error Handling (G10)

Unified `ApiError` shape returned by `lib/api.ts`. Single mapping table
drives toast variants + copy + retry behavior.

### `lib/errors.ts`

```ts
// frontend/src/lib/errors.ts
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
  ) { super(message); this.name = "ApiError"; }
}

type ToastSpec = {
  variant: "error" | "warning" | "info";
  copy:    string;
  retryable: boolean;
};

export const ERROR_TOAST_MAP: Record<ApiErrorCode, (err: ApiError) => ToastSpec> = {
  missing_api_key: () => ({
    variant: "error",
    copy:    "Backend authentication misconfigured. Please notify the operator.",
    retryable: false,
  }),
  invalid_api_key: () => ({
    variant: "error",
    copy:    "Backend authentication misconfigured. Please notify the operator.",
    retryable: false,
  }),
  validation_error: () => ({
    variant: "warning",
    copy:    "Your message couldn't be processed. Please rephrase and try again.",
    retryable: true,
  }),
  rate_limited: (err) => ({
    variant: "warning",
    copy:    `You're sending requests too quickly. Retry in ${err.retryAfter ?? 60}s.`,
    retryable: true,
  }),
  server_error: () => ({
    variant: "error",
    copy:    "Something went wrong on the server. Please try again in a moment.",
    retryable: true,
  }),
  network_error: () => ({
    variant: "error",
    copy:    "Couldn't reach the backend. Check your connection and retry.",
    retryable: true,
  }),
  stream_interrupted: () => ({
    variant: "warning",
    copy:    "Response was interrupted. Showing what was received so far.",
    retryable: true,
  }),
};
```

### Mapping in `lib/api.ts`

```ts
async function sendChat({ messages, onEvent }: SendArgs) {
  let response: Response;
  try {
    response = await fetch("/api/chat/stream", {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ messages }),
    });
  } catch (err) {
    throw new ApiError("network_error", "Could not reach backend");
  }

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const code: ApiErrorCode =
      response.status === 401 ? "missing_api_key" :
      response.status === 403 ? "invalid_api_key" :
      response.status === 422 ? "validation_error" :
      response.status === 429 ? "rate_limited" :
      "server_error";
    throw new ApiError(code, body.message ?? "Request failed", body.retry_after);
  }

  // Successful — parse SSE stream
  const reader = response.body!.getReader();
  try {
    for await (const ev of parseSSEStream(reader)) {
      if (ev.type === "error") {
        throw new ApiError(
          (ev.payload.code as ApiErrorCode) ?? "server_error",
          ev.payload.message,
          ev.payload.retry_after,
        );
      }
      onEvent(ev);
    }
  } catch (err) {
    if (!(err instanceof ApiError)) {
      throw new ApiError("stream_interrupted", "Stream ended unexpectedly");
    }
    throw err;
  }
}
```

### Rate-limit countdown affordance

When `code === "rate_limited"`, disable the chat input for the
`retry_after` duration and show a countdown overlay. Auto-reenable
when countdown expires.

---

## Error Boundary (G20)

Top-level `<ErrorBoundary>` wrapping `<Chat>` in `app/layout.tsx`. Catches
synchronous React render errors that would otherwise white-screen the
whole app. Async errors (network, API) flow through the G10 toast system
above; this is the orthogonal sync-error catch.

```tsx
// frontend/src/components/ErrorBoundary.tsx
"use client";
import { Component, ReactNode } from "react";

type Props = { children: ReactNode };
type State = { error: Error | null };

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error("UI error:", error, info);
    // Future work: send to Sentry with breadcrumbs
  }

  render() {
    if (this.state.error) {
      return (
        <div className="flex h-[100dvh] flex-col items-center justify-center p-8 text-center">
          <h2 className="text-lg font-medium">Something went wrong.</h2>
          <p className="text-sm text-muted-foreground mt-2">
            Reload the page to try again. If the problem persists, contact the operator.
          </p>
          <button
            onClick={() => window.location.reload()}
            className="mt-4 px-4 py-2 rounded-md bg-primary text-primary-foreground"
          >
            Reload
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
```

Wired in `app/layout.tsx`:

```tsx
<body>
  <ErrorBoundary>
    <Toaster />
    {children}
  </ErrorBoundary>
</body>
```

---

## Page Metadata (G22)

```tsx
// frontend/src/app/layout.tsx
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Customs Analytics Agent",
  description: "Conversational Q&A over U.S. customs entry data, grounded in domain knowledge.",
  icons: { icon: "/favicon.ico" },
  openGraph: {
    title:       "Customs Analytics Agent",
    description: "Demo for Pedestal AI's Oracle Problem case study.",
    images:      ["/og-image.png"],
    type:        "website",
  },
  robots: { index: false, follow: false },   // demo URL — don't index
};
```

### 🚨 User-provided assets reminder

When the `feat/empty-state-chips` or `chore/mobile-responsive` branch
is reached (Day 5-6 per `PROGRESS.md`), Claude will prompt at the chunk-
completion message to place the assets at:

- `frontend/public/favicon.ico` (16×16 minimum, ICO format)
- `frontend/public/og-image.png` (1200×630 PNG)

Until these files exist, the `metadata.icons` and `metadata.openGraph.images`
references will 404 silently. Reviewers loading the demo would see a
broken icon in the Chrome tab and a generic OG card when the link is
shared — small but real polish hits.

---

## `PROMPT_VERSION` Drift Badge (G25)

Conversations saved in `localStorage` may have been generated under an
older `PROMPT_VERSION`. The frontend shows a subtle badge on those
messages.

```tsx
// frontend/src/components/MessageBubble.tsx (excerpt)
import { CURRENT_PROMPT_VERSION } from "@/lib/config";   // hardcoded; bumped manually

function VersionBadge({ messageVersion }: { messageVersion?: string }) {
  if (!messageVersion || messageVersion === CURRENT_PROMPT_VERSION) return null;
  return (
    <span
      className="text-xs text-muted-foreground ml-2"
      title={`Generated under prompt version ${messageVersion}; current is ${CURRENT_PROMPT_VERSION}`}
    >
      v{messageVersion}
    </span>
  );
}

// Inside MessageBubble's header:
<div className="flex items-center gap-2">
  <span className="font-medium">Assistant</span>
  <VersionBadge messageVersion={message.sidecar?.meta?.prompt_version} />
</div>
```

`CURRENT_PROMPT_VERSION` is hardcoded in `lib/config.ts` (or sourced
from the most recent `/health`/`/ready` response). When the backend
bumps `PROMPT_VERSION` (Fork 27), updating this constant lets the
frontend mark prior-version messages explicitly.

---

## Mobile Responsive (Fork 34)

Tailwind breakpoints applied throughout. Two real breakpoints:

| Breakpoint | Layout |
|---|---|
| (default) `<640px` | Single-column chips, sheet-style sidebar via shadcn `<Sheet>`, full-width message bubbles |
| `sm:` `≥640px` | Two-column chips, wider bubbles |
| `lg:` `≥1024px` | Persistent sidebar visible (Phase 2), max-width chat column |

### iOS Safari specifics

- Use `100dvh` (dynamic viewport height) not `100vh` on outermost
  container — accounts for the Safari bottom bar collapsing/expanding.
- Apply `pb-[env(safe-area-inset-bottom)]` to the input container so the
  iOS home indicator doesn't overlap the input.
- Markdown tables in messages: wrap in `overflow-x-auto` so they
  horizontally scroll without breaking layout.
- SQL blocks in the panel: `overflow-x-auto text-xs` so long SQL
  doesn't wrap awkwardly on narrow viewports.

### Citation pills on mobile

`<HoverCard>` is gated behind `(hover: hover)` media query — on touch
devices, single-tap = jump-to-panel (no two-tap pattern, which is a
known a11y footgun).

### Day 6 30-min mobile pass

Per Fork 57 item #51:

1. Chrome DevTools → device emulation → iPhone SE (375×667) + iPhone 14 Pro (390×844)
2. Verify each major state: empty state with chips, single message + panel expanded, multi-message scroll, streaming in progress, sidebar open via hamburger (Phase 2 only)
3. Real-device check on the developer's iPhone before submission

---

## Background SSE Caveat (G23)

Documented limitation, not mitigated for the demo:

> Browsers throttle background tabs. Streaming responses may stall if
> the tab is backgrounded mid-stream. The frontend shows the partial
> response with a Retry button (Fork 29); re-submitting the question
> generates a fresh response.

Mention in README's "Known limitations" section. Service Worker
buffering is future work.

---

## Frontend Testing (G2)

Vitest unit tests for pure-function modules in `src/lib/`. **No
component tests**, **no Playwright E2E** for the demo. See
`08-cicd-and-testing.md` for the full testing strategy.

Pure-function modules tested (~18-23 tests total):

- `lib/sse.test.ts` — SSE parser (chunk boundary buffering, all event types, malformed dispatch)
- `lib/storage.test.ts` — localStorage round-trip, quota handling, Private Mode fallback, version migration
- `lib/citations.test.ts` — marker resolution, orphan handling, kind classification
- `lib/api.test.ts` — `ApiError` construction, error code mapping, network failure synthesis

Component rendering is verified by: `pnpm typecheck` (catches prop
errors), `pnpm build` (catches render-time errors), and Vercel preview
deploys (visual verification per PR).

---

## Composition with Other Layers

- **`05-api-and-backend.md`** — frontend's `lib/api.ts` calls the
  Next.js server routes which proxy to the Fly endpoints. Error shapes
  from this file map to the G10 `ApiError` table here.
- **`04-agent-and-tools.md`** — `ChatResponse` shape (with `Citation`,
  `ToolCallTrace`, `Assumption`, `ResponseMeta`) is the authoritative
  contract. Frontend treats `args` and `result` on `ToolCallTrace` as
  `Record<string, unknown>` (G3 nuance — per-tool typing is future
  work).
- **`07-infrastructure.md`** — `package.json` `packageManager` field
  pins pnpm 9.x; Vercel project config (`vercel.json`) pins `iad1`
  region; deploy via GitHub integration (no GHA step needed for
  frontend per Fork 42).
- **`08-cicd-and-testing.md`** — `ci.yml` runs `pnpm lint`,
  `pnpm typecheck`, `pnpm test --run`, `pnpm build`; `api-contract`
  job verifies `openapi.json` ↔ `api-types.ts` are in sync (G3).
- **`09-security.md`** — server-side proxy isolating `BACKEND_API_KEY`
  from the browser is the primary frontend-side security
  contribution; `<ErrorBoundary>` is part of the defensive defense-in-
  depth.
- **`10-observability.md`** — frontend can opt into web-vitals
  reporting via Vercel Speed Insights (future work); per-request
  observability is server-side.

---

## Future Work

| Item | Trigger |
|---|---|
| React Testing Library component tests for `AgentPanel`, `EmptyState`, `Chat` | When component-level regression risk grows (e.g., dedicated frontend team) |
| Playwright E2E smoke (load → click chip → assert response) | When demo-URL outages must be caught before reviewer click |
| Per-message-bubble error boundaries | When one corrupted message shouldn't kill the conversation view (G20 future work) |
| Sentry integration with breadcrumbs | Production observability for client-side errors |
| "Reload conversation" button | UX recovery after error boundary trip |
| Visual regression (Chromatic / Playwright screenshots) | UI polish becomes contractually critical |
| Service Worker SSE buffer for backgrounded tabs (G23 follow-on) | When tab-throttling complaints arrive |
| Per-conversation OpenGraph image generation (Vercel OG) | When shared links should carry conversation context |
| Toast queue (instead of single-toast replacement) | When multiple simultaneous errors become common |
| Retry-with-exponential-backoff for transient 5xx + network errors | When connection reliability becomes a real issue |
| `offline` detection via `navigator.onLine` with banner | Mobile-heavy usage on flaky connections |
| Web Vitals reporting via Vercel Speed Insights | Production performance monitoring |
| Per-tool discriminated unions for `ToolCallTrace.args` / `result` rendering | When specialized chart components per tool become valuable |
| Storybook for component sandboxes | Multi-developer frontend team |
| MSW (Mock Service Worker) for richer `lib/api.ts` tests | When the API mock surface grows |
| BrowserslistDB pinning + polyfill bundle for older browsers (G15 follow-on) | When the demo audience extends beyond modern evergreen browsers |
