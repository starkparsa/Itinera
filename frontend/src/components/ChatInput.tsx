"use client";

import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";

export default function ChatInput({ disabled, onSubmit }: { disabled: boolean; onSubmit: (prompt: string) => void }) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const wasDisabled = useRef(disabled);

  // Return focus to the composer once a pending request resolves (disabled
  // flips true -> false) -- without this, focus is left wherever it was
  // (often nowhere useful) after every send, forcing a re-click to type
  // the next message or a follow-up.
  useEffect(() => {
    if (wasDisabled.current && !disabled) textareaRef.current?.focus();
    wasDisabled.current = disabled;
  }, [disabled]);

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
      {/* aria-label, not just the placeholder -- placeholder text isn't a
          reliable accessible name (it disappears once typed, and several
          screen reader/browser combinations never expose it as the field's
          name at all). */}
      <Textarea
        ref={textareaRef}
        aria-label="Describe your trip"
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
