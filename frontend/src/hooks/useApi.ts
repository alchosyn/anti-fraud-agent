import { useCallback } from 'react';
import type { HistoryRecord, SessionDetail } from '../types';

const BASE = '/api';

export function useApi() {
  const submitAnalysis = useCallback(
    async (message: string, messageType: string): Promise<string> => {
      const res = await fetch(`${BASE}/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message, message_type: messageType }),
      });
      if (!res.ok) throw new Error('Failed to submit analysis');
      const data = await res.json();
      return data.session_id as string;
    },
    [],
  );

  const fetchHistory = useCallback(async (): Promise<HistoryRecord[]> => {
    const res = await fetch(`${BASE}/history`);
    if (!res.ok) throw new Error('Failed to fetch history');
    const data = await res.json();
    return data.records as HistoryRecord[];
  }, []);

  const fetchSessionDetail = useCallback(
    async (sessionId: string): Promise<SessionDetail> => {
      const res = await fetch(`${BASE}/history/${sessionId}`);
      if (!res.ok) throw new Error('Session not found');
      return (await res.json()) as SessionDetail;
    },
    [],
  );

  return { submitAnalysis, fetchHistory, fetchSessionDetail };
}
