import { useRef, useCallback } from 'react';
import type { WSMessage } from '../types';

export function useWebSocket(token: string | null) {
  const wsRef = useRef<WebSocket | null>(null);

  const connect = useCallback(
    (sessionId: string, onMessage: (msg: WSMessage) => void) => {
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      // Pass JWT via query param since WS doesn't support Authorization header
      const url = `${protocol}//${window.location.host}/api/ws/${sessionId}?token=${encodeURIComponent(token ?? '')}`;
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onmessage = (event) => {
        try {
          const msg: WSMessage = JSON.parse(event.data);
          onMessage(msg);

          // auto-close on terminal messages
          if (msg.type === 'result' || msg.type === 'error') {
            ws.close();
          }
        } catch {
          // ignore parse errors
        }
      };

      ws.onerror = () => {
        onMessage({ type: 'error', message: '连接出错，请重试' });
      };

      ws.onclose = () => {
        wsRef.current = null;
      };
    },
    [token],
  );

  const disconnect = useCallback(() => {
    wsRef.current?.close();
    wsRef.current = null;
  }, []);

  return { connect, disconnect };
}
