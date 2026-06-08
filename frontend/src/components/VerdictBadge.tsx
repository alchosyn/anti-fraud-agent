import type { Verdict } from '../types';

const CONFIG: Record<Verdict, { label: string; color: string; border: string }> = {
  high_risk:   { label: '高风险', color: 'text-red-600',    border: 'border-red-400' },
  medium_risk: { label: '中风险', color: 'text-rl-accent',  border: 'border-rl-accent' },
  low_risk:    { label: '低风险', color: 'text-yellow-600', border: 'border-yellow-400' },
  safe:        { label: '安全',   color: 'text-emerald-600', border: 'border-emerald-400' },
};

export default function VerdictBadge({ verdict }: { verdict: Verdict }) {
  const c = CONFIG[verdict] ?? CONFIG.safe;
  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 text-[10px] font-bold uppercase tracking-[1px] border ${c.color} ${c.border} bg-transparent`}>
      <span className={`w-1.5 h-1.5 ${c.color.replace('text-', 'bg-')}`} />
      {c.label}
    </span>
  );
}
