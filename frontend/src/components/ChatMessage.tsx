import type { MessageOut } from "@/lib/types";
import TripView from "./TripView";

export default function ChatMessage({ message }: { message: MessageOut }) {
  const isUser = message.role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[80%] rounded-xl px-4 py-3 text-sm ${
          isUser ? "bg-primary text-primary-foreground" : "border bg-card text-card-foreground"
        }`}
      >
        <p className="whitespace-pre-wrap">{message.content}</p>
        {message.trip && <TripView trip={message.trip} />}
      </div>
    </div>
  );
}
