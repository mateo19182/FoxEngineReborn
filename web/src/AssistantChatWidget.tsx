import { useCallback, useEffect, useRef } from "react";
import { Widget, addResponseMessage, dropMessages } from "react-chat-widget";
import "react-chat-widget/lib/styles.css";
import "./assistantChat.css";
import { api } from "./api";

type Turn = { role: "user" | "assistant"; content: string };

export function AssistantChatWidget() {
  const transcript = useRef<Turn[]>([]);

  const handleNewUserMessage = useCallback(async (content: string) => {
    transcript.current.push({ role: "user", content });
    try {
      const r = await api<{ reply: string }>("/assistant/chat", {
        method: "POST",
        json: { messages: transcript.current },
      });
      transcript.current.push({ role: "assistant", content: r.reply });
      addResponseMessage(r.reply);
    } catch (e) {
      addResponseMessage(`Error: ${String(e)}`);
    }
  }, []);

  useEffect(() => {
    return () => {
      dropMessages();
      transcript.current = [];
    };
  }, []);

  return (
    <Widget
      title="Assistant"
      subtitle="Jobs, batches, tags"
      senderPlaceHolder="Ask anything…"
      handleNewUserMessage={handleNewUserMessage}
      emojis={false}
      showBadge={false}
    />
  );
}
