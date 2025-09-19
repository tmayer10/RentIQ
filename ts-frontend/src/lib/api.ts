export const ChatAPI = {
    send: async (text: string) => {
      // placeholder – integrate with backend later
      return { role: "assistant", text: `Echo: ${text}` };
    }
  };
  