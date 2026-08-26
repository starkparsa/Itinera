import type { MessageOut } from "@/lib/types";
import TripView from "./TripView";

export default function ChatMessage({ message }: { message: MessageOut }) {
  return (
    <div className={`chat-message chat-message--${message.role}`}>
      <div className="chat-message__bubble">
        <p>{message.content}</p>
        {message.trip && <TripView trip={message.trip} />}
      </div>
    </div>
  );
}
