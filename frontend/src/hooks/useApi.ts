import { useCallback } from 'react';
import type { HistoryRecord, SessionDetail } from '../types';

const BASE = '/api';

export function useApi(token: string | null) {
  const headers = useCallback((): HeadersInit => {
    const h: HeadersInit = { 'Content-Type': 'application/json' };
    if (token) h['Authorization'] = `Bearer ${token}`;
    return h;
  }, [token]);

  const submitAnalysis = useCallback(
    async (
      message: string,
      messageType: string,
      history: { role: string; content: string }[] = [],
    ): Promise<string> => {
      const res = await fetch(`${BASE}/analyze`, {
        method: 'POST',
        headers: headers(),
        body: JSON.stringify({ message, message_type: messageType, history }),
      });
      if (res.status === 401) throw new Error('Unauthorized');
      if (!res.ok) throw new Error('Failed to submit analysis');
      const data = await res.json();
      return data.session_id as string;
    },
    [headers],
  );

  const fetchHistory = useCallback(async (): Promise<HistoryRecord[]> => {
    const res = await fetch(`${BASE}/history`, { headers: headers() });
    if (res.status === 401) throw new Error('Unauthorized');
    if (!res.ok) throw new Error('Failed to fetch history');
    const data = await res.json();
    return data.records as HistoryRecord[];
  }, [headers]);

  const fetchSessionDetail = useCallback(
    async (sessionId: string): Promise<SessionDetail> => {
      const res = await fetch(`${BASE}/history/${sessionId}`, { headers: headers() });
      if (res.status === 401) throw new Error('Unauthorized');
      if (!res.ok) throw new Error('Session not found');
      return (await res.json()) as SessionDetail;
    },
    [headers],
  );

  return { submitAnalysis, fetchHistory, fetchSessionDetail };
}
