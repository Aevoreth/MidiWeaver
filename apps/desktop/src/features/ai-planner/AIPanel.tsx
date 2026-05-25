import { useState } from "react";
import type {
  AgentStepLog,
  ArrangementPlan,
  PlanStep,
  RevisionDiff,
  TempoOption,
} from "@/lib/api";
import { Button, Input, Label, Panel } from "@/components/ui/button";

type AiMode = "ask" | "plan" | "agent";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

interface AIPanelProps {
  aiMode: "live" | "mock";
  diff: RevisionDiff | null;
  onAsk: (messages: ChatMessage[]) => Promise<{ message: string; tool_calls?: unknown[] }>;
  onPlan: (
    prompt: string,
    constraints: Record<string, unknown>,
  ) => Promise<{ plan: ArrangementPlan; planId: string; mode: "live" | "mock" }>;
  onAgentRun: (
    prompt: string,
    planId?: string,
  ) => Promise<{
    session_id: string;
    status: string;
    summary?: string;
    steps: AgentStepLog[];
  }>;
  onAgentCancel: (sessionId: string) => Promise<void>;
  onTimelineRefresh?: () => void;
}

export function AIPanel({
  aiMode,
  diff,
  onAsk,
  onPlan,
  onAgentRun,
  onAgentCancel,
  onTimelineRefresh,
}: AIPanelProps) {
  const [mode, setMode] = useState<AiMode>("agent");
  const [prompt, setPrompt] = useState(
    "Create a smooth drum-heavy transition with a tempo ramp.",
  );
  const [constraints, setConstraints] = useState({
    max_transpose_semitones: 6,
    max_tempo_delta: 40,
    max_transition_bars: 16,
    drum_only_mode: false,
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [askInput, setAskInput] = useState("");

  const [plan, setPlan] = useState<ArrangementPlan | null>(null);
  const [planId, setPlanId] = useState<string | null>(null);
  const [planMode, setPlanMode] = useState<"live" | "mock" | null>(null);
  const [editableSteps, setEditableSteps] = useState<PlanStep[]>([]);
  const [tempoIndex, setTempoIndex] = useState(0);

  const [agentSessionId, setAgentSessionId] = useState<string | null>(null);
  const [agentSteps, setAgentSteps] = useState<AgentStepLog[]>([]);
  const [agentSummary, setAgentSummary] = useState<string | null>(null);
  const [agentStatus, setAgentStatus] = useState<string | null>(null);

  const runAsk = async () => {
    if (!askInput.trim()) return;
    setLoading(true);
    setError(null);
    const nextMessages: ChatMessage[] = [
      ...chatMessages,
      { role: "user", content: askInput.trim() },
    ];
    setChatMessages(nextMessages);
    setAskInput("");
    try {
      const result = await onAsk(nextMessages);
      setChatMessages((m) => [...m, { role: "assistant", content: result.message }]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ask failed");
    } finally {
      setLoading(false);
    }
  };

  const runPlan = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await onPlan(prompt, constraints);
      setPlan(result.plan);
      setPlanId(result.planId);
      setPlanMode(result.mode);
      setEditableSteps(result.plan.steps.map((s) => ({ ...s })));
      setTempoIndex(result.plan.selected_tempo_option_index ?? 0);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Plan failed");
    } finally {
      setLoading(false);
    }
  };

  const runAgent = async (usePlan?: boolean) => {
    setLoading(true);
    setError(null);
    setAgentSteps([]);
    setAgentSummary(null);
    setAgentStatus("running");
    try {
      const agentPrompt = usePlan && plan
        ? `${prompt}\n\nExecute this arrangement plan:\n${JSON.stringify({ ...plan, steps: editableSteps }, null, 2)}`
        : prompt;
      const result = await onAgentRun(agentPrompt, usePlan ? planId ?? undefined : undefined);
      setAgentSessionId(result.session_id);
      setAgentSteps(result.steps);
      setAgentSummary(result.summary ?? null);
      setAgentStatus(result.status);
      onTimelineRefresh?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Agent failed");
      setAgentStatus("error");
    } finally {
      setLoading(false);
    }
  };

  const cancelAgent = async () => {
    if (!agentSessionId) return;
    setLoading(true);
    try {
      await onAgentCancel(agentSessionId);
      setAgentStatus("cancelled");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-3 text-sm">
      {aiMode === "mock" && (
        <Panel className="text-xs text-muted">
          No API key configured. AI uses offline mock responses. Add a key in Settings for live models.
        </Panel>
      )}

      <div className="flex gap-1 rounded-md border border-border p-1">
        {(["ask", "plan", "agent"] as AiMode[]).map((m) => (
          <button
            key={m}
            type="button"
            className={`flex-1 rounded px-2 py-1 capitalize ${
              mode === m ? "bg-accent/20 text-accent" : "text-muted hover:text-foreground"
            }`}
            onClick={() => setMode(m)}
          >
            {m}
          </button>
        ))}
      </div>

      {mode !== "ask" && (
        <div>
          <Label>{mode === "plan" ? "Plan prompt" : "Agent prompt"}</Label>
          <textarea
            className="mt-1 min-h-20 w-full rounded-md border border-border bg-surface p-2 text-sm"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
          />
        </div>
      )}

      {mode === "plan" && (
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
                onChange={(e) =>
                  setConstraints((c) => ({ ...c, max_tempo_delta: Number(e.target.value) }))
                }
              />
            </label>
          </div>
        </Panel>
      )}

      {mode === "ask" && (
        <Panel className="max-h-48 space-y-2 overflow-y-auto">
          {chatMessages.length === 0 && (
            <div className="text-xs text-muted">
              Ask about your timeline, transitions, or notes in the edit range.
            </div>
          )}
          {chatMessages.map((m, i) => (
            <div
              key={i}
              className={`rounded p-2 text-xs ${m.role === "user" ? "bg-accent/10" : "bg-surface-elevated"}`}
            >
              <div className="mb-1 font-medium capitalize text-muted">{m.role}</div>
              <div className="whitespace-pre-wrap">{m.content}</div>
            </div>
          ))}
        </Panel>
      )}

      {mode === "ask" && (
        <div className="flex gap-2">
          <Input
            className="flex-1"
            placeholder="Ask about this project…"
            value={askInput}
            onChange={(e) => setAskInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && runAsk()}
          />
          <Button onClick={runAsk} disabled={loading}>
            Send
          </Button>
        </div>
      )}

      {mode === "plan" && (
        <Button onClick={runPlan} disabled={loading}>
          {loading ? "Planning…" : planMode === "mock" || aiMode === "mock" ? "Generate plan (mock)" : "Generate plan"}
        </Button>
      )}

      {mode === "agent" && (
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => runAgent(false)} disabled={loading}>
            {loading ? "Running…" : "Run agent"}
          </Button>
          {planId && (
            <Button variant="secondary" onClick={() => runAgent(true)} disabled={loading}>
              Run with plan
            </Button>
          )}
          {agentSessionId && agentStatus === "running" && (
            <Button variant="secondary" onClick={cancelAgent} disabled={loading}>
              Stop
            </Button>
          )}
        </div>
      )}

      {error && <div className="text-error text-xs">{error}</div>}

      {mode === "plan" && plan && (
        <Panel className="space-y-2">
          <div className="text-xs text-muted">{planMode === "live" ? "Live plan" : "Mock plan"}</div>
          <div className="font-medium">{plan.plan_summary}</div>

          {plan.tempo_options.length > 0 && (
            <div>
              <div className="mb-1 text-xs text-muted">Tempo options</div>
              {plan.tempo_options.map((opt: TempoOption, i: number) => (
                <label
                  key={opt.label}
                  className={`mb-1 flex cursor-pointer items-start gap-2 rounded border p-2 ${
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
          )}

          <div>
            <div className="mb-1 text-xs text-muted">Steps — edit before running with agent</div>
            {editableSteps.map((step, i) => (
              <div key={step.id} className="mb-2 border-t border-border pt-2">
                <div className="text-xs font-medium text-muted">
                  {step.id} · {step.suggested_tool ?? step.intent}
                </div>
                <textarea
                  className="mt-1 w-full rounded border border-border bg-surface p-1 text-xs"
                  value={step.description}
                  onChange={(e) => {
                    const next = [...editableSteps];
                    next[i] = { ...step, description: e.target.value };
                    setEditableSteps(next);
                  }}
                />
              </div>
            ))}
          </div>

          <Button onClick={() => runAgent(true)} disabled={loading || !planId}>
            Run with Agent
          </Button>
        </Panel>
      )}

      {mode === "agent" && (agentSteps.length > 0 || agentSummary) && (
        <Panel className="space-y-2">
          <div className="flex items-center justify-between">
            <div className="font-medium">Agent run</div>
            {agentStatus && <span className="text-xs text-muted capitalize">{agentStatus}</span>}
          </div>
          {agentSummary && <div className="text-xs whitespace-pre-wrap">{agentSummary}</div>}
          {agentSteps.map((step) => (
            <div key={step.step_index} className="border-t border-border pt-2 text-xs">
              <div className="font-medium">{step.tool_name}</div>
              <div className="text-muted">
                {step.revision_id != null && `rev ${step.revision_id} · `}
                +{(step.result?.diff as { added_notes?: unknown[] })?.added_notes?.length ?? 0} / -
                {(step.result?.diff as { removed_notes?: unknown[] })?.removed_notes?.length ?? 0} notes
              </div>
              {step.error && <div className="text-error">{step.error}</div>}
            </div>
          ))}
        </Panel>
      )}

      {diff && (
        <Panel>
          <div className="mb-1 font-medium">Last revision diff</div>
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
