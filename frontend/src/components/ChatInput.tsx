"use client";

import { useState, type KeyboardEvent } from "react";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";

export default function ChatInput({ disabled, onSubmit }: { disabled: boolean; onSubmit: (prompt: string) => void }) {
  const [value, setValue] = useState("");

  function submit() {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSubmit(trimmed);
    setValue("");
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  return (
    <div className="flex gap-2 border-t pt-4">
      <Textarea
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="e.g. 4 days in Lisbon, love food and walking, mid-range budget"
        disabled={disabled}
        rows={2}
      />
      <Button onClick={submit} disabled={disabled || !value.trim()} size="lg" className="px-5">
        Send
      </Button>
    </div>
  );
}
