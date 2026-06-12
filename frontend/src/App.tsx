import { useState, useEffect, useCallback } from 'react';
import type { ChatMessage, StepMessage, ResultMessage, HistoryRecord, MessageType, WSMessage } from './types';
import { useAuth } from './hooks/useAuth';
import { useApi } from './hooks/useApi';
import { useWebSocket } from './hooks/useWebSocket';
import LoginPage from './components/LoginPage';
import ChatPanel from './components/ChatPanel';
import ReasoningPanel from './components/ReasoningPanel';
import HistoryPanel from './components/HistoryPanel';
import MessageInput from './components/MessageInput';

type MobileTab = 'chat' | 'reasoning' | 'history';

export default function App() {
  const { auth, isLoggedIn, token, user, login, register, logout } = useAuth();

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [steps, setSteps] = useState<StepMessage[]>([]);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [history, setHistory] = useState<HistoryRecord[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [mobileTab, setMobileTab] = useState<MobileTab>('chat');

  const { submitAnalysis, fetchHistory, fetchSessionDetail } = useApi(token);
  const { connect } = useWebSocket(token);

  // Fetch history on login
  useEffect(() => {
    if (isLoggedIn) {
      fetchHistory().then(setHistory).catch(console.error);
    }
  }, [isLoggedIn, fetchHistory]);

  const handleWSMessage = useCallback((msg: WSMessage) => {
    if (msg.type === 'step') {
      setSteps((prev) => [...prev, msg]);
    } else if (msg.type === 'result') {
      const result = msg as ResultMessage;
      setMessages((prev) => [
        ...prev,
        { id: `agent-${Date.now()}`, role: 'agent', content: result.summary, result },
      ]);
      setIsAnalyzing(false);
      fetchHistory().then(setHistory).catch(console.error);
    } else if (msg.type === 'error') {
      setMessages((prev) => [
        ...prev,
        { id: `error-${Date.now()}`, role: 'agent', content: `错误: ${msg.message}` },
      ]);
      setIsAnalyzing(false);
    }
  }, [fetchHistory]);

  const handleSubmit = useCallback(
    async (message: string, messageType: MessageType) => {
      // Build conversation history from existing messages for context
      const chatHistory = messages
        .filter((m) => m.role === 'user' || (m.role === 'agent' && m.result))
        .map((m) => ({
          role: m.role === 'user' ? 'user' : 'assistant',
          content: m.role === 'user' ? m.content : (m.result?.summary ?? m.content),
        }));

      setMessages((prev) => [
        ...prev,
        { id: `user-${Date.now()}`, role: 'user', content: message, messageType },
      ]);
      setSteps([]);
      setIsAnalyzing(true);
      try {
        const sessionId = await submitAnalysis(message, messageType, chatHistory);
        setActiveSessionId(sessionId);
        connect(sessionId, handleWSMessage);
      } catch {
        setIsAnalyzing(false);
        setMessages((prev) => [
          ...prev,
          { id: `error-${Date.now()}`, role: 'agent', content: '提交失败，请重试' },
        ]);
      }
    },
    [messages, submitAnalysis, connect, handleWSMessage],
  );

  const handleHistorySelect = useCallback(
    async (sessionId: string) => {
      try {
        const detail = await fetchSessionDetail(sessionId);
        setActiveSessionId(sessionId);
        setSteps(detail.steps);
        setIsAnalyzing(false);
        const chatMessages: ChatMessage[] = [
          { id: `user-${sessionId}`, role: 'user', content: detail.message, messageType: detail.message_type },
        ];
        if (detail.summary) {
          chatMessages.push({
            id: `agent-${sessionId}`,
            role: 'agent',
            content: detail.summary,
            result: {
              type: 'result',
              verdict: detail.verdict ?? null,
              confidence: detail.confidence ?? null,
              summary: detail.summary,
              advice: detail.advice,
              evidence: [],
            },
          });
        }
        setMessages(chatMessages);
        setMobileTab('chat');
      } catch (e) {
        console.error(e);
      }
    },
    [fetchSessionDetail],
  );

  const handleLogin = useCallback(
    async (username: string, password: string) => {
      await login(username, password);
    },
    [login],
  );

  const handleRegister = useCallback(
    async (username: string, password: string, displayName: string) => {
      await register(username, password, displayName);
    },
    [register],
  );

  // ── Not logged in → show login page ──
  if (!isLoggedIn) {
    return <LoginPage onLogin={handleLogin} onRegister={handleRegister} />;
  }

  // ── Logged in → main app ──
  return (
    <div className="h-screen flex flex-col" style={{ background: 'linear-gradient(135deg, #e7e7dd, #eee, #dad8d4)' }}>
      {/* ── Rhine Lab Header ── */}
      <header className="bg-rl-dark text-white px-6 py-2.5 flex items-center gap-4 shrink-0">
        {/* Logo mark */}
        <div className="w-7 h-7 border border-rl-accent flex items-center justify-center">
          <svg className="w-4 h-4 text-rl-accent" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round"
              d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z" />
          </svg>
        </div>
        <div>
          <h1 className="text-sm font-bold tracking-[3px] uppercase leading-tight">RHINE LAB</h1>
          <p className="text-[10px] tracking-[2px] uppercase text-rl-muted">Anti-Fraud Detection System</p>
        </div>
        {/* decorative line */}
        <div className="flex-1 h-px bg-white/10 mx-4" />
        <span className="text-base tracking-[2px] text-rl-accent font-bold">信噪</span>
        {/* user info + logout */}
        <div className="h-4 w-px bg-white/20 mx-2" />
        <span className="text-[10px] text-rl-muted tracking-[1px]">{user?.display_name}</span>
        <button
          onClick={logout}
          className="text-[10px] text-rl-muted hover:text-rl-accent tracking-[1px] uppercase transition-colors"
        >
          LOGOUT
        </button>
      </header>

      {/* ── 2px accent bar ── */}
      <div className="h-[2px] bg-rl-accent shrink-0" />

      {/* ── Mobile tabs ── */}
      <div className="lg:hidden flex border-b border-rl-border bg-rl-bg2 shrink-0">
        {(['chat', 'reasoning', 'history'] as MobileTab[]).map((tab) => (
          <button
            key={tab}
            onClick={() => setMobileTab(tab)}
            className={`flex-1 py-2.5 text-[11px] font-bold text-center uppercase tracking-[1.5px] border-b-2 transition-colors ${
              mobileTab === tab
                ? 'border-rl-accent text-rl-text'
                : 'border-transparent text-rl-muted'
            }`}
          >
            {tab === 'chat' ? '对话' : tab === 'reasoning' ? `推理 ${steps.length}` : `历史 ${history.length}`}
          </button>
        ))}
      </div>

      {/* ── Main content ── */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left: Chat */}
        <div className={`flex flex-col bg-rl-bg2 lg:w-[40%] lg:border-r lg:border-rl-border ${
          mobileTab === 'chat' ? 'flex' : 'hidden lg:flex'
        } w-full`}>
          <ChatPanel messages={messages} />
          <MessageInput onSubmit={handleSubmit} disabled={isAnalyzing} />
        </div>

        {/* Center: Reasoning */}
        <div className={`bg-rl-surface lg:flex-1 lg:border-r lg:border-rl-border ${
          mobileTab === 'reasoning' ? 'flex flex-col' : 'hidden lg:flex lg:flex-col'
        } w-full`}>
          <ReasoningPanel steps={steps} isAnalyzing={isAnalyzing} />
        </div>

        {/* Right: History */}
        <div className={`bg-rl-bg2 lg:w-[25%] ${
          mobileTab === 'history' ? 'flex flex-col' : 'hidden lg:flex lg:flex-col'
        } w-full`}>
          <HistoryPanel records={history} activeId={activeSessionId} onSelect={handleHistorySelect} />
        </div>
      </div>
    </div>
  );
}
