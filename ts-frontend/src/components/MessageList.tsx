import type { ChatMessage } from "../lib/types";

export default function MessageList({ messages }: { messages: ChatMessage[] }) {
    return (
      <div style={{ overflowY: "auto", flex: 1 }}>
        {messages.map(m => (
            <div
                key={m.id}
                style={{
                margin: "0.5rem 0",
                padding: "0.5rem 0.75rem",
                borderRadius: "8px",
                background: m.role === "user" ? "#dbeafe" : "#e5e7eb",
                alignSelf: m.role === "user" ? "flex-end" : "flex-start",
                maxWidth: "75%",
                }}
            >
                {m.text}
            </div>
        ))}
      </div>
    );
  }