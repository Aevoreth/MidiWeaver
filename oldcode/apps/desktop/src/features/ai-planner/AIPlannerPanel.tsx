import { useState } from "react";
import type { OperationPlan, TempoOption, RevisionDiff } from "@/lib/api";
import { Button, Input, Label, Panel } from "@/components/ui/button";

interface AIPlannerPanelProps {
  aiMode: "live" | "mock";
  onGenerate: (
    prompt: string,
    constraints: Record<string, unknown>,
  ) => Promise<{ plan: OperationPlan; mode: "live" | "mock" }>;
  onApply: (plan: OperationPlan, enabledIndices: number[], tempoIndex: number) => Promise<void>;
  diff: RevisionDiff | null;
}

export function AIPlannerPanel({ aiMode, onGenerate, onApply, diff }: AIPlannerPanelProps) {
  const [prompt, setPrompt] = useState("Create a smooth drum-heavy transition with a tempo ramp.");
  const [plan, setPlan] = useState<OperationPlan | null>(null);
  const [planMode, setPlanMode] = useState<"live" | "mock" | null>(null);
  const [enabledOps, setEnabledOps] = useState<Set<number>>(new Set());
  const [tempoIndex, setTempoIndex] = useState(0);
  const [constraints, setConstraints] = useState({
    max_transpose_semitones: 6,
    max_tempo_delta: 40,
    max_transition_bars: 8,
    drum_only_mode: false,
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const effectiveMode = planMode ?? aiMode;
  const generateLabel =
    effectiveMode === "live"
      ? loading
        ? "Planning…"
        : "Generate plan"
      : loading
        ? "Planning…"
        : "Generate plan (mock — no API key)";

  const runPlan = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await onGenerate(prompt, constraints);
      setPlan(result.plan);
      setPlanMode(result.mode);
      setEnabledOps(new Set(result.plan.ops.map((_, i) => i)));
      setTempoIndex(result.plan.selected_tempo_option_index ?? 0);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Plan failed");
    } finally {
      setLoading(false);
    }
  };

  const apply = async () => {
    if (!plan) return;
    setLoading(true);
    try {
      await onApply(plan, [...enabledOps], tempoIndex);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Apply failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-3 text-sm">
      {aiMode === "mock" && (
        <Panel className="text-xs text-muted">
          No API key configured. Plans use offline mock data. Add a key in Settings to use live AI.
        </Panel>
      )}

      <div>
        <Label>Prompt</Label>
        <textarea
          className="mt-1 min-h-20 w-full rounded-md border border-border bg-surface p-2 text-sm"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
        />
      </div>

      <Panel>
        <div className="mb-2 font-medium">Constraints</div>
        <div className="grid grid-cols-2 gap-2">
          <label className="text-xs text-muted">
            Max transpose
            <Input
              type="number"
              value={constraints.max_transpose_semitones}
              onChange={(e) =>
                setConstraints((c) => ({ ...c, max_transpose_semitones: Number(e.target.value) }))
              }
            />
          </label>
          <label className="text-xs text-muted">
            Max tempo Δ
            <Input
              type="number"
              value={constraints.max_tempo_delta}
              onChange={(e) => setConstraints((c) => ({ ...c, max_tempo_delta: Number(e.target.value) }))}
            />
          </label>
        </div>
        <label className="mt-2 flex items-center gap-2 text-xs">
          <input
            type="checkbox"
            checked={constraints.drum_only_mode}
            onChange={(e) => setConstraints((c) => ({ ...c, drum_only_mode: e.target.checked }))}
          />
          Drum-only mode
        </label>
      </Panel>

      <Button onClick={runPlan} disabled={loading}>
        {generateLabel}
      </Button>
      {error && <div className="text-error text-xs">{error}</div>}

      {plan && (
        <Panel className="space-y-2">
          <div className="text-xs text-muted">
            {effectiveMode === "live" ? "Live AI plan" : "Mock plan"}
          </div>
          <div className="font-medium">{plan.plan_summary}</div>

          <div>
            <div className="mb-1 text-xs text-muted">Tempo options — pick one</div>
            <div className="space-y-2">
              {plan.tempo_options.map((opt: TempoOption, i: number) => (
                <label
                  key={opt.label}
                  className={`flex cursor-pointer items-start gap-2 rounded border p-2 ${
                    tempoIndex === i ? "border-accent bg-accent/10" : "border-border"
                  }`}
                >
                  <input type="radio" checked={tempoIndex === i} onChange={() => setTempoIndex(i)} />
                  <div>
                    <div className="font-medium">{opt.label}</div>
                    <div className="text-xs text-muted">
                      {opt.policy} · {opt.duration_bars} bars · {opt.start_bpm}→{opt.end_bpm} BPM
                    </div>
                  </div>
                </label>
              ))}
            </div>
          </div>

          <div>
            <div className="mb-1 text-xs text-muted">Operations — toggle before apply</div>
            {plan.ops.map((op, i) => (
              <label key={i} className="flex items-start gap-2 border-t border-border py-2 text-xs">
                <input
                  type="checkbox"
                  checked={enabledOps.has(i)}
                  onChange={(e) => {
                    const next = new Set(enabledOps);
                    if (e.target.checked) next.add(i);
                    else next.delete(i);
                    setEnabledOps(next);
                  }}
                />
                <div>
                  <div className="font-medium">{op.op_type}</div>
                  <div className="text-muted">{op.description || JSON.stringify(op.params)}</div>
                </div>
              </label>
            ))}
          </div>

          <Button onClick={apply} disabled={loading || enabledOps.size === 0}>
            Apply selected ops
          </Button>
        </Panel>
      )}

      {diff && (
        <Panel>
          <div className="mb-1 font-medium">Before / After diff</div>
          <div className="grid grid-cols-3 gap-2 text-xs text-muted">
            <span>+{diff.added_notes.length} notes</span>
            <span>-{diff.removed_notes.length} notes</span>
            <span>{diff.moved_notes.length} moved</span>
          </div>
        </Panel>
      )}
    </div>
  );
}
