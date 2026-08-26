"use client";

import type { ConversationSummary } from "@/lib/types";
import { signOutAction } from "@/lib/authActions";

interface SidebarProps {
  conversations: ConversationSummary[];
  activeConversationId: number | null;
  onSelect: (id: number) => void;
  onNewChat: () => void;
  onDelete: (id: number) => void;
  userEmail: string | null;
}

export default function Sidebar({
  conversations,
  activeConversationId,
  onSelect,
  onNewChat,
  onDelete,
  userEmail,
}: SidebarProps) {
  return (
    <aside className="sidebar">
      <h3>🧭 Travel Planner</h3>
      <button className="new-chat-button" onClick={onNewChat}>
        + New chat
      </button>

      <p className="sidebar__label">Chats</p>
      {conversations.length === 0 && <p className="sidebar__empty">No chats yet — start one below.</p>}
      <ul className="conversation-list">
        {conversations.map((conv) => (
          <li key={conv.id} className={conv.id === activeConversationId ? "conversation--active" : ""}>
            <button className="conversation-title" onClick={() => onSelect(conv.id)}>
              {conv.title || "New chat"}
            </button>
            <button
              className="conversation-delete"
              title="Delete this chat"
              onClick={() => onDelete(conv.id)}
              aria-label={`Delete ${conv.title}`}
            >
              🗑
            </button>
          </li>
        ))}
      </ul>

      {userEmail && (
        <div className="sidebar__footer">
          <span className="sidebar__user-email" title={userEmail}>
            {userEmail}
          </span>
          <button className="sign-out-button" onClick={() => signOutAction()}>
            Sign out
          </button>
        </div>
      )}
    </aside>
  );
}
