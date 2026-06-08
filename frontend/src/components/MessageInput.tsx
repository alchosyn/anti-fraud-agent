import { useState, useRef, useEffect } from 'react';
import type { MessageType } from '../types';

const TYPE_OPTIONS: { value: MessageType; label: string }[] = [
  { value: 'sms', label: '短信' },
  { value: 'email', label: '邮件' },
  { value: 'phone_transcript', label: '电话记录' },
];

interface Props {
  onSubmit: (message: string, messageType: MessageType) => void;
  disabled: boolean;
}

export default function MessageInput({ onSubmit, disabled }: Props) {
  const [text, setText] = useState('');
  const [msgType, setMsgType] = useState<MessageType>('sms');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = textareaRef.current;
    if (el) {
      el.style.height = 'auto';
      el.style.height = Math.min(el.scrollHeight, 160) + 'px';
    }
  }, [text]);

  const handleSubmit = () => {
    const trimmed = text.trim();
    if (!trimmed || disabled) return;
    onSubmit(trimmed, msgType);
    setText('');
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div className="border-t border-rl-border bg-white p-4">
      {/* type selector */}
      <div className="flex gap-1 mb-3">
        {TYPE_OPTIONS.map((opt) => (
          <button
            key={opt.value}
            onClick={() => setMsgType(opt.value)}
            className={`px-3 py-1 text-[11px] font-bold tracking-[1px] uppercase border transition-colors ${
              msgType === opt.value
                ? 'bg-rl-dark text-white border-rl-dark'
                : 'bg-transparent text-rl-muted border-rl-border hover:border-rl-text'
            }`}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {/* input row */}
      <div className="flex items-end gap-2">
        <textarea
          ref={textareaRef}
          rows={1}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="粘贴可疑短信 / 邮件内容..."
          disabled={disabled}
          className="flex-1 resize-none border border-rl-border px-3 py-2.5 text-sm outline-none transition-colors focus:border-rl-accent disabled:opacity-40 disabled:bg-rl-surface placeholder:text-rl-border-warm"
        />
        <button
          onClick={handleSubmit}
          disabled={disabled || !text.trim()}
          className="shrink-0 h-10 px-5 bg-rl-accent text-white text-[12px] font-bold tracking-[1.5px] uppercase hover:brightness-110 disabled:opacity-30 disabled:cursor-not-allowed transition-all flex items-center gap-2"
        >
          {disabled ? (
            <>
              <span className="w-3 h-3 border-2 border-white/30 border-t-white animate-spin" />
              分析中
            </>
          ) : (
            '发送 →'
          )}
        </button>
      </div>
    </div>
  );
}
