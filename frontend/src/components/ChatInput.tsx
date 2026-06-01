"use client";

import { useState, type KeyboardEvent } from "react";
import { SendHorizontal } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

// Matches the backend Message.content cap (Fork 49 layer-1, 2000 chars) so the
// UI can't submit something the backend would 422.
const MAX_CHARS = 2000;

export function ChatInput({
  onSubmit,
  disabled,
}: {
  onSubmit: (text: string) => void;
  disabled: boolean;
}) {
  const [value, setValue] = useState("");

  function submit() {
    const text = value.trim();
    if (!text || disabled) return;
    onSubmit(text);
    setValue("");
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    // Enter submits; Shift+Enter inserts a newline.
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  return (
    <div className="border-t bg-background px-4 py-3 pb-[env(safe-area-inset-bottom)] sm:px-6">
      <div className="mx-auto flex max-w-3xl items-end gap-2">
        <Textarea
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          maxLength={MAX_CHARS}
          rows={1}
          disabled={disabled}
          placeholder="Ask about customs entries, duties, holds…"
          aria-label="Message input"
          className="max-h-40 resize-none"
        />
        <Button
          onClick={submit}
          disabled={disabled || value.trim().length === 0}
          size="icon"
          aria-label="Send message"
        >
          <SendHorizontal className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}
