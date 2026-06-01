"use client";

import { Plus } from "lucide-react";

import { Button } from "@/components/ui/button";

export function Header({ onNewChat }: { onNewChat: () => void }) {
  return (
    <header className="flex items-center justify-between border-b px-4 py-3 sm:px-6">
      <div className="flex flex-col">
        <span className="text-sm font-semibold">Customs Analytics Agent</span>
        <span className="text-xs text-muted-foreground">
          U.S. customs entry data · Oct 2024 – Mar 2025
        </span>
      </div>
      <Button variant="outline" size="sm" onClick={onNewChat}>
        <Plus className="h-4 w-4" />
        New chat
      </Button>
    </header>
  );
}
