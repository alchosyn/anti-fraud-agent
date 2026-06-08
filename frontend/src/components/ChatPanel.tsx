import { useEffect, useRef } from 'react';
import type { ChatMessage } from '../types';
import VerdictBadge from './VerdictBadge';

interface Props {
  messages: ChatMessage[];
}

export default function ChatPanel({ messages }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  return (
    <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
      {messages.length === 0 && (
        <div className="flex flex-col items-center justify-center h-full gap-4">
          {/* geometric empty state */}
          <div className="relative w-20 h-20 rl-crosshair flex items-center justify-center">
            <div className="w-12 h-12 border border-rl-border flex items-center justify-center">
              <svg className="w-6 h-6 text-rl-border-warm" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round"
                  d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126z" />
              </svg>
            </div>
          </div>
          <div className="text-center">
            <p className="text-[11px] font-bold tracking-[2px] uppercase text-rl-muted">Paste Suspicious Message</p>
            <p className="text-[11px] text-rl-border-warm mt-1">粘贴可疑消息，信噪帮你识别诈骗风险</p>
          </div>
        </div>
      )}

      {messages.map((msg) => (
        <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
          <div
            className={`max-w-[85%] px-4 py-3 text-sm leading-relaxed ${
              msg.role === 'user'
                ? 'bg-rl-dark text-white'
                : 'bg-white border border-rl-border text-rl-text'
            }`}
          >
            {msg.role === 'user' ? (
              <p className="whitespace-pre-wrap">{msg.content}</p>
            ) : msg.result ? (
              <div className="space-y-3">
                {/* verdict */}
                <div className="flex items-center gap-3">
                  <VerdictBadge verdict={msg.result.verdict} />
                  <span className="text-[10px] text-rl-muted font-bold tracking-[1px]">
                    CONFIDENCE {(msg.result.confidence * 100).toFixed(0)}%
                  </span>
                </div>

                {/* divider */}
                <div className="h-px bg-rl-border" />

                {/* summary */}
                <p className="whitespace-pre-wrap text-rl-text/80 text-[13px]">{msg.result.summary}</p>

                {/* advice */}
                <div className="border border-rl-border p-3">
                  <p className="text-[10px] font-bold text-rl-accent tracking-[1.5px] uppercase mb-2">建议操作</p>
                  <ul className="space-y-1">
                    {msg.result.advice.map((a, i) => (
                      <li key={i} className="flex gap-2 text-[12px] text-rl-text/70">
                        <span className="text-rl-accent shrink-0">—</span>
                        {a}
                      </li>
                    ))}
                  </ul>
                </div>

                {/* evidence */}
                <details className="group">
                  <summary className="text-[10px] text-rl-muted cursor-pointer hover:text-rl-text font-bold tracking-[1px] uppercase">
                    ▸ Evidence ({msg.result.evidence.length})
                  </summary>
                  <div className="mt-2 space-y-1">
                    {msg.result.evidence.map((e, i) => (
                      <div key={i} className="text-[11px] text-rl-text/60 bg-rl-surface border border-rl-border px-2.5 py-1.5">
                        <span className="font-bold text-rl-text/80">[{e.source}]</span>{' '}
                        {e.finding}
                      </div>
                    ))}
                  </div>
                </details>
              </div>
            ) : (
              <p className="whitespace-pre-wrap">{msg.content}</p>
            )}
          </div>
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  );
}
