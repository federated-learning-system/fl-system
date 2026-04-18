import { useEffect, useRef, useCallback } from "react";

export interface WSMessage {
  event: string;
  payload?: Record<string, unknown>;
  [key: string]: unknown;
}

interface UseWebSocketOptions {
  url: string;
  onMessage: (msg: WSMessage) => void;
  reconnectIntervalMs?: number;
}

export function useWebSocket({
  url,
  onMessage,
  reconnectIntervalMs = 5000,
}: UseWebSocketOptions) {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onmessage = (evt) => {
      try {
        const data = JSON.parse(evt.data) as WSMessage;
        onMessage(data);
      } catch {
        // ignore non-JSON messages
      }
    };

    ws.onclose = () => {
      reconnectTimer.current = setTimeout(connect, reconnectIntervalMs);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, [url, onMessage, reconnectIntervalMs]);

  useEffect(() => {
    connect();
    return () => {
      clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);
}
