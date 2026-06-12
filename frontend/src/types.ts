/* ---- Auth ---- */

export interface UserInfo {
  user_id: number;
  username: string;
  display_name: string;
}

export interface AuthState {
  token: string;
  user: UserInfo;
}

/* ---- WebSocket message types ---- */

export interface StepMessage {
  type: 'step';
  step_number: number;
  total_steps: number;
  thought: string;
  tool_name: string;
  tool_input: Record<string, unknown>;
  tool_output: Record<string, unknown>;
  timestamp: string;
}

export interface ResultMessage {
  type: 'result';
  verdict: Verdict | null;
  confidence: number | null;
  summary: string;
  advice: string[];
  evidence: Evidence[];
}

export interface ErrorMessage {
  type: 'error';
  message: string;
}

export type WSMessage = StepMessage | ResultMessage | ErrorMessage;

/* ---- Domain types ---- */

export type Verdict = 'high_risk' | 'medium_risk' | 'low_risk' | 'safe';
export type MessageType = 'sms' | 'email' | 'phone_transcript';

export interface Evidence {
  source: string;
  finding: string;
}

/* ---- Chat bubble ---- */

export interface ChatMessage {
  id: string;
  role: 'user' | 'agent';
  content: string;
  messageType?: MessageType;
  result?: ResultMessage;
}

/* ---- History ---- */

export interface HistoryRecord {
  session_id: string;
  message_preview: string;
  message_type: MessageType;
  verdict: Verdict | null;
  created_at: string;
}

export interface SessionDetail {
  session_id: string;
  message: string;
  message_type: MessageType;
  verdict: Verdict | null;
  confidence: number | null;
  summary: string | null;
  advice: string[];
  steps: StepMessage[];
  created_at: string;
}
