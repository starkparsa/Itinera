import type { MessageOut } from "@/lib/types";
import TripView from "./TripView";

export default function ChatMessage({ message }: { message: MessageOut }) {
  const isUser = message.role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[80%] rounded-xl px-4 py-3 text-sm ${
          isUser
            ? "bg-primary text-primary-foreground"
            : "border-chat-assistant-border bg-chat-assistant-bg text-chat-assistant-fg border"
        }`}
      >
        {/* Speaker is otherwise conveyed only by left/right position and
            bubble color -- both invisible to a screen reader reading
            through the role="log" transcript in ChatApp.tsx. sr-only text
            gives the same "who said this" cue sighted users get for free. */}
        <p className="whitespace-pre-wrap">
          <span className="sr-only">{isUser ? "You: " : "Itinera: "}</span>
          {message.content}
        </p>
        {message.trip && <TripView trip={message.trip} />}
      </div>
    </div>
  );
}
