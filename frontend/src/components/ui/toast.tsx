"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

interface ToastOptions {
  title: string;
  description?: string;
  variant?: "default" | "destructive";
}

interface ToastItem extends ToastOptions {
  id: number;
}

interface ToastContextValue {
  toast: (options: ToastOptions) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within <ToastProvider>");
  return ctx;
}

const AUTO_DISMISS_MS = 4000;
let nextId = 0;

// Mounted once at the app root (see app/layout.tsx) -- every future
// celebration/confirmation moment (onboarding saved, a badge earned, an
// export succeeding) routes through this one provider instead of each
// feature inventing its own notification.
export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((item) => item.id !== id));
  }, []);

  const toast = useCallback((options: ToastOptions) => {
    const id = nextId++;
    setToasts((current) => [...current, { id, ...options }]);
  }, []);

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-full max-w-sm flex-col gap-2">
        {toasts.map((item) => (
          <ToastCard key={item.id} item={item} onDismiss={() => dismiss(item.id)} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}

function ToastCard({ item, onDismiss }: { item: ToastItem; onDismiss: () => void }) {
  useEffect(() => {
    const timer = setTimeout(onDismiss, AUTO_DISMISS_MS);
    return () => clearTimeout(timer);
  }, [onDismiss]);

  return (
    <div
      role="status"
      aria-live="polite"
      className={cn(
        "pointer-events-auto flex items-start gap-2 rounded-lg border bg-card p-3 text-sm shadow-lg animate-in fade-in slide-in-from-bottom-2 motion-reduce:animate-none",
        item.variant === "destructive" ? "border-destructive/30 text-destructive" : "border-border text-card-foreground"
      )}
    >
      <div className="flex-1">
        <p className="font-medium">{item.title}</p>
        {item.description && <p className="text-muted-foreground">{item.description}</p>}
      </div>
      <button onClick={onDismiss} aria-label="Dismiss notification" className="text-muted-foreground hover:text-foreground">
        <X className="size-4" />
      </button>
    </div>
  );
}
