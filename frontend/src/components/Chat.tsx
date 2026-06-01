"use client";

import { useEffect, useReducer } from "react";

import { Header } from "./Header";
import { ChatInput } from "./ChatInput";
import { MessageBubble } from "./MessageBubble";
import { sendChat } from "@/lib/api";
import { ApiError } from "@/lib/errors";
import {
  clearActiveConversation,
  loadActiveConversation,
  saveActiveConversation,
} from "@/lib/storage";
import type { ChatMessage, ChatResponse } from "@/lib/types";

interface State {
  messages: ChatMessage[];
  isLoading: boolean;
  isHydrated: boolean;
  error: string | null;
}

type Action =
  | { type: "HYDRATE"; messages: ChatMessage[] }
  | { type: "USER_MESSAGE"; content: string }
  | { type: "ASSISTANT_MESSAGE"; response: ChatResponse }
  | { type: "REQUEST_START" }
  | { type: "REQUEST_END" }
  | { type: "REQUEST_ERROR"; message: string }
  | { type: "NEW_CHAT" };

const initialState: State = {
  messages: [],
  isLoading: false,
  isHydrated: false,
  error: null,
};

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "HYDRATE":
      return { ...state, messages: action.messages, isHydrated: true };
    case "USER_MESSAGE":
      return {
        ...state,
        error: null,
        messages: [...state.messages, { role: "user", content: action.content }],
      };
    case "ASSISTANT_MESSAGE":
      return {
        ...state,
        messages: [
          ...state.messages,
          {
            role: "assistant",
            content: action.response.answer,
            sidecar: action.response,
          },
        ],
      };
    case "REQUEST_START":
      return { ...state, isLoading: true };
    case "REQUEST_END":
      return { ...state, isLoading: false };
    case "REQUEST_ERROR":
      return { ...state, error: action.message };
    case "NEW_CHAT":
      return { ...initialState, isHydrated: true };
    default:
      return state;
  }
}

export function Chat() {
  const [state, dispatch] = useReducer(reducer, initialState);

  // Hydrate from localStorage on mount (Fork 7).
  useEffect(() => {
    const stored = loadActiveConversation();
    dispatch({ type: "HYDRATE", messages: stored?.messages ?? [] });
  }, []);

  // Persist on every change after hydration (Fork 7). Guarding on isHydrated
  // avoids clobbering stored state with the empty initial array on first render.
  useEffect(() => {
    if (state.isHydrated) saveActiveConversation(state.messages);
  }, [state.messages, state.isHydrated]);

  async function handleSubmit(text: string) {
    // Build the outgoing history explicitly (state updates are async, so we
    // can't rely on state.messages reflecting the just-dispatched user turn).
    const outgoing: ChatMessage[] = [...state.messages, { role: "user", content: text }];
    dispatch({ type: "USER_MESSAGE", content: text });
    dispatch({ type: "REQUEST_START" });
    try {
      const response = await sendChat(outgoing);
      dispatch({ type: "ASSISTANT_MESSAGE", response });
    } catch (err) {
      const message =
        err instanceof ApiError ? err.message : "Something went wrong. Please try again.";
      dispatch({ type: "REQUEST_ERROR", message });
    } finally {
      dispatch({ type: "REQUEST_END" });
    }
  }

  function handleNewChat() {
    if (
      state.messages.length > 5 &&
      !window.confirm("Start a new chat? Your current conversation will be cleared.")
    ) {
      return;
    }
    clearActiveConversation();
    dispatch({ type: "NEW_CHAT" });
  }

  return (
    <div className="flex h-[100dvh] flex-col">
      <Header onNewChat={handleNewChat} />
      <main className="flex-1 overflow-y-auto px-4 sm:px-6">
        <div className="mx-auto flex max-w-3xl flex-col gap-4 py-6">
          {state.isHydrated && state.messages.length === 0 && (
            <div className="mt-16 flex flex-col items-center gap-2 text-center">
              <h1 className="text-2xl font-medium">Ask anything about customs data</h1>
              <p className="text-sm text-muted-foreground">
                MHF · PCA · SAG — October 2024 to March 2025
              </p>
            </div>
          )}

          {state.messages.map((m, i) => (
            <MessageBubble key={i} message={m} />
          ))}

          {state.isLoading && (
            <div className="flex justify-start">
              <div className="rounded-2xl bg-muted px-4 py-2.5 text-sm text-muted-foreground">
                Thinking…
              </div>
            </div>
          )}

          {state.error && (
            <div className="flex justify-start">
              <div className="rounded-2xl border border-destructive/40 bg-destructive/10 px-4 py-2.5 text-sm text-destructive">
                {state.error}
              </div>
            </div>
          )}
        </div>
      </main>
      <ChatInput onSubmit={handleSubmit} disabled={state.isLoading} />
    </div>
  );
}
