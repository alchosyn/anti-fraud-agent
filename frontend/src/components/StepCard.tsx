import type { StepMessage } from '../types';

const TOOL_LABELS: Record<string, string> = {
  risk_score: '风险评分',
  search_knowledge: '知识库检索',
  web_search: '网络搜索',
  calculator: '计算器',
  get_current_time: '获取时间',
};

export default function StepCard({ step }: { step: StepMessage }) {
  return (
    <div className="animate-fade-in border border-rl-border bg-white p-4">
      {/* header bar */}
      <div className="flex items-center gap-3 mb-3">
        <div className="flex items-center justify-center w-6 h-6 bg-rl-dark text-white text-[10px] font-bold">
          {step.step_number}
        </div>
        <span className="text-[10px] text-rl-muted font-bold tracking-[2px] uppercase">
          Step {step.step_number} / {step.total_steps}
        </span>
        <div className="flex-1 h-px bg-rl-border" />
        <span className="text-[10px] text-rl-muted">
          {new Date(step.timestamp).toLocaleTimeString()}
        </span>
      </div>

      {/* thought */}
      <p className="text-[13px] text-rl-text/70 mb-3 leading-relaxed pl-9">
        {step.thought}
      </p>

      {/* tool call */}
      <div className="border border-rl-border bg-rl-surface p-3 ml-9">
        <div className="flex items-center gap-2 mb-2">
          <div className="w-1.5 h-1.5 bg-rl-accent" />
          <span className="text-[11px] font-bold text-rl-text tracking-[1px] uppercase">
            {TOOL_LABELS[step.tool_name] ?? step.tool_name}
          </span>
        </div>

        <div className="space-y-2">
          <div>
            <span className="text-[10px] text-rl-muted font-bold tracking-[1.5px] uppercase">Input</span>
            <pre className="mt-1 rl-mono whitespace-pre-wrap break-all text-rl-text/80 bg-white border border-rl-border p-2">
{JSON.stringify(step.tool_input, null, 2)}</pre>
          </div>

          <div>
            <span className="text-[10px] text-rl-muted font-bold tracking-[1.5px] uppercase">Output</span>
            <pre className="mt-1 rl-mono whitespace-pre-wrap break-all text-rl-text/80 bg-white border border-rl-border p-2">
{JSON.stringify(step.tool_output, null, 2)}</pre>
          </div>
        </div>
      </div>
    </div>
  );
}
