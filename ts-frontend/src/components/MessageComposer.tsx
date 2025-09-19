import { useState } from "react";

export default function MessageComposer({ onSend }: { onSend: (text: string) => void }) {
  const [text, setText] = useState("");
  return (
    <form
      onSubmit={e => {
        e.preventDefault();
        if (!text.trim()) return;
        onSend(text);
        setText("");
      }}
      style={{ display: "flex", gap: "0.5rem", marginTop: "1rem" }}
    >
      <input
        style={{
            flex: 1,
            padding: "0.5rem",
            border: "1px solid #d1d5db",
            borderRadius: "6px",
        }}
        value={text}
        onChange={e => setText(e.target.value)}
        placeholder="Type a message..."
      />
      <button 
        type="submit"
        style={{
            padding: "0.5rem 1rem",
            background: "#2563eb",
            color: "white",
            border: "none",
            borderRadius: "6px",
            cursor: "pointer",
          }}
        >
            Send
        </button>
    </form>
  );
}
