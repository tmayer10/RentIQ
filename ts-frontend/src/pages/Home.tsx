import { useState } from "react";
import type { ChatMessage } from "../lib/types";
import MessageList from "../components/MessageList";
import MessageComposer from "../components/MessageComposer";

export default function Home() {
  const [messages, setMessages] = useState<ChatMessage[]>([
    { id: "1", role: "assistant", text: "Hi! Ask me about housing." },
  ]);

  return (
    <div style={{ flex: 2, display: "flex", flexDirection: "column", borderRight: "1px solid #e5e7eb", padding: "1rem", background: "#fff" }}>
      <div style={{ flex: 2, display: "flex", flexDirection: "column", borderRight: "1px solid #ccc", padding: "1rem" }}>
        <h2>Chat</h2>
        <div style={{ overflowY: "auto", flex: 1 }}>
          <MessageList messages={messages} />
        </div>
        <MessageComposer
          onSend={text =>
            setMessages(prev => [
              ...prev,
              { id: Date.now().toString(), role: "user", text },
            ])
          }
        />
      </div>
      <div style={{
          background: "#fff",
          padding: "1rem",
          borderRadius: "8px",
          boxShadow: "0 1px 3px rgba(0,0,0,0.1)",
      }}>
        <h2>Insights Panel</h2>
        <p>[Charts / Forecasts / Map will go here]</p>
      </div>
    </div>
  );
}
