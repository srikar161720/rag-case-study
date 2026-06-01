/**
 * localStorage persistence — Phase 1, single active conversation (Fork 7).
 *
 * The backend is stateless; the frontend holds all conversation state here so a
 * page refresh restores the in-progress chat without any backend infra. Phase 2
 * (multi-conversation sidebar, Fork 33) is additive and lands on a later branch
 * — this `ACTIVE_KEY` keeps working as the "currently active" pointer.
 *
 * All access is wrapped in try/catch: Safari Private Mode throws on
 * `localStorage` writes, and quota can be exceeded. Both degrade gracefully to
 * in-memory state rather than crashing the app.
 */

import type { ChatMessage } from "./types";

const ACTIVE_KEY = "customs-agent.activeConversation";

export interface StoredConversation {
  id: string; // UUID, generated on first message
  title: string; // first 40 chars of the first user message
  createdAt: string; // ISO timestamp
  updatedAt: string; // ISO timestamp
  messages: ChatMessage[]; // includes the sidecar on assistant messages
}

/** Load the active conversation, or null if absent / unreadable / malformed. */
export function loadActiveConversation(): StoredConversation | null {
  try {
    const raw = localStorage.getItem(ACTIVE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as StoredConversation;
    // Validate the minimal shape we actually depend on: `messages` MUST be an
    // array, or Chat's `state.messages.map(...)` throws on hydrate. The stored
    // value is persisted, so a corrupt/legacy shape would re-crash on every
    // reload (and there's no ErrorBoundary yet — that's G20). Degrade to a
    // fresh conversation instead of trusting the cast.
    if (!parsed || !Array.isArray(parsed.messages)) return null;
    return parsed;
  } catch {
    // Private mode, corrupt JSON, or quota — degrade to no stored state.
    return null;
  }
}

/**
 * Persist the active conversation. Passing an empty `messages` array clears the
 * stored conversation (used by "+ New chat"). Preserves the existing id / title
 * / createdAt across saves so a conversation keeps its identity.
 */
export function saveActiveConversation(messages: ChatMessage[]): void {
  if (messages.length === 0) {
    clearActiveConversation();
    return;
  }
  const existing = loadActiveConversation();
  const now = new Date().toISOString();
  const conv: StoredConversation = {
    id: existing?.id ?? crypto.randomUUID(),
    title: existing?.title ?? messages[0].content.slice(0, 40),
    createdAt: existing?.createdAt ?? now,
    updatedAt: now,
    messages,
  };
  try {
    localStorage.setItem(ACTIVE_KEY, JSON.stringify(conv));
  } catch {
    // QuotaExceededError (or private mode) → trim the oldest turn pairs and
    // retry once. If it still fails, give up silently (in-memory state remains
    // the source of truth for this session).
    handleQuotaExceeded(conv);
  }
}

/** Remove the active conversation entirely. */
export function clearActiveConversation(): void {
  try {
    localStorage.removeItem(ACTIVE_KEY);
  } catch {
    // Nothing actionable if removal fails; ignore.
  }
}

/**
 * Quota fallback: drop the oldest 5 turn pairs (10 messages) and retry the
 * write once. Keeps the most recent context rather than losing everything.
 */
function handleQuotaExceeded(conv: StoredConversation): void {
  const trimmed: StoredConversation = {
    ...conv,
    messages: conv.messages.slice(10),
  };
  if (trimmed.messages.length === conv.messages.length) return; // nothing to trim
  try {
    localStorage.setItem(ACTIVE_KEY, JSON.stringify(trimmed));
  } catch {
    // Still over quota — leave in-memory state as the source of truth.
  }
}
