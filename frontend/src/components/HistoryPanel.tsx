import type { HistoryRecord, Verdict } from '../types';
import VerdictBadge from './VerdictBadge';

interface Props {
  records: HistoryRecord[];
  activeId: string | null;
  onSelect: (sessionId: string) => void;
}

function timeAgo(dateStr: string): string {
  const d = new Date(dateStr + 'Z');
  const now = Date.now();
  const diff = Math.floor((now - d.getTime()) / 1000);
  if (diff < 60) return '刚刚';
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`;
  return `${Math.floor(diff / 86400)} 天前`;
}

export default function HistoryPanel({ records, activeId, onSelect }: Props) {
  return (
    <div className="flex flex-col h-full">
      <div className="px-4 py-3 border-b border-rl-border flex items-center gap-3">
        <span className="text-[11px] font-bold text-rl-text tracking-[2px] uppercase">历史记录</span>
        <div className="flex-1 h-px bg-rl-border" />
        <span className="text-[10px] text-rl-muted font-bold">{records.length}</span>
      </div>

      <div className="flex-1 overflow-y-auto">
        {records.length === 0 && (
          <p className="text-[11px] text-rl-border-warm text-center mt-16 tracking-[1px]">暂无记录</p>
        )}

        {records.map((r) => (
          <button
            key={r.session_id}
            onClick={() => onSelect(r.session_id)}
            className={`w-full text-left px-4 py-3 border-b border-rl-border transition-colors ${
              activeId === r.session_id
                ? 'bg-white border-l-2 border-l-rl-accent'
                : 'hover:bg-white/60 border-l-2 border-l-transparent'
            }`}
          >
            <p className="text-[12px] text-rl-text/70 truncate leading-snug">{r.message_preview}</p>
            <div className="flex items-center gap-2 mt-1.5">
              {r.verdict && <VerdictBadge verdict={r.verdict as Verdict} />}
              <span className="text-[10px] text-rl-muted">{timeAgo(r.created_at)}</span>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
