import { useEffect, useRef } from 'react';
import type { StepMessage } from '../types';
import StepCard from './StepCard';

interface Props {
  steps: StepMessage[];
  isAnalyzing: boolean;
}

export default function ReasoningPanel({ steps, isAnalyzing }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [steps]);

  return (
    <div className="flex flex-col h-full">
      <div className="px-4 py-3 border-b border-rl-border flex items-center gap-3">
        <span className="text-[11px] font-bold text-rl-text tracking-[2px] uppercase">推理过程</span>
        <div className="flex-1 h-px bg-rl-border" />
        {isAnalyzing && (
          <span className="flex items-center gap-2 text-[10px] text-rl-accent font-bold tracking-[1px] uppercase">
            <span className="w-2 h-2 bg-rl-accent animate-pulse" />
            Processing
          </span>
        )}
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
        {steps.length === 0 && !isAnalyzing && (
          <div className="flex flex-col items-center justify-center h-full gap-3">
            <div className="w-12 h-12 border border-rl-border flex items-center justify-center">
              <svg className="w-5 h-5 text-rl-border-warm" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round"
                  d="M9.75 3.104v5.714a2.25 2.25 0 01-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 014.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19.8 15.3M14.25 3.104c.251.023.501.05.75.082M19.8 15.3l-1.57.393A9.065 9.065 0 0112 15a9.065 9.065 0 00-6.23.693L5 14.5m14.8.8l1.402 1.402c1.232 1.232.65 3.318-1.067 3.611A48.309 48.309 0 0112 21c-2.773 0-5.491-.235-8.135-.687-1.718-.293-2.3-2.379-1.067-3.61L5 14.5" />
              </svg>
            </div>
            <p className="text-[10px] text-rl-muted tracking-[1.5px] uppercase font-bold">
              Awaiting Input
            </p>
            <p className="text-[11px] text-rl-border-warm">提交消息后显示推理过程</p>
          </div>
        )}

        {steps.map((s) => (
          <StepCard key={s.step_number} step={s} />
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
