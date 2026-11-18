import { create } from "zustand";

export type Lang = "en" | "hi" | "ur";
export type Phase = "boot" | "connecting" | "live" | "ended";
export type UiState = "idle" | "listening" | "thinking" | "speaking" | "handover" | "connected" | "ended";
export type Mode = "normal" | "handover" | "emergency" | "connected";
export type StepStatus = "run" | "ok" | "alert" | "skip";

export interface Caption { id: number; role: "caller" | "assistant"; text: string }
export interface TraceItem { id: number; step: string; status: StepStatus; detail: string; t: number }
export interface Timing { stt_ms?: number | null; nlu_ms?: number | null; tts_first_ms?: number | null; server_ms?: number | null; e2e_ms?: number | null }
export interface Source { title: string; version: number; score: number; chunk_id: string }
export interface Triage { tier: "self_care" | "see_doctor_soon" | "same_day" | "emergency"; label: string; topic: string; age_group: string; reasons: string[] }
export interface Status {
  llm: boolean; llm_busy?: boolean; stt: boolean; voice: boolean; voice_cache: boolean; records: boolean; knowledge: boolean; db: boolean;
}

interface S {
  phase: Phase;
  ui: UiState;
  mode: Mode;
  playing: boolean;
  muted: boolean;
  sfx: boolean;
  lang: Lang;
  consent: boolean;
  triage: Triage | null;
  rated: Record<number, "up" | "down">;
  micError: string | null;
  audioBlocked: boolean;
  error: string | null;
  captions: Caption[];
  trace: TraceItem[];
  steps: Record<string, { status: StepStatus; detail: string }>;
  safety: Record<string, string>;
  sources: Source[];
  timing: Timing;
  intent: string | null;
  session: { id: string; hospital: string; assistant: string; emergency: string } | null;
  handover: { status: "waiting" | "connected"; id: string; staff?: string; urgency?: string; reason?: string } | null;
  status: Status | null;
  drawer: boolean;
  set: (p: Partial<S>) => void;
  addCaption: (c: Omit<Caption, "id">) => void;
  addTrace: (t: Omit<TraceItem, "id">) => void;
  resetTurn: () => void;
  reset: () => void;
}

let seq = 1;
function readLang(): Lang {
  try { const v = localStorage.getItem("hania_lang"); return v === "hi" || v === "ur" ? v : "en"; } catch { return "en"; }
}
const initial = {
  phase: "boot" as Phase, ui: "idle" as UiState, mode: "normal" as Mode, playing: false, muted: false, sfx: true, lang: "en" as Lang,
  micError: null, audioBlocked: false, error: null, captions: [], trace: [], steps: {}, safety: { redflag: "ok", scope: "ok", pii: "on", llm_check: "ok" },
  sources: [], timing: {}, intent: null, session: null, handover: null, triage: null as Triage | null, rated: {} as Record<number, "up" | "down">,
};

export const useStore = create<S>((set) => ({
  ...initial,
  status: null,
  lang: readLang(),
  consent: false,
  drawer: false,
  set: (p) => set(p),
  addCaption: (c) => set((s) => ({ captions: [...s.captions.slice(-40), { ...c, id: seq++ }] })),
  addTrace: (t) =>
    set((s) => ({
      trace: [...s.trace.slice(-60), { ...t, id: seq++ }],
      steps: { ...s.steps, [t.step]: { status: t.status, detail: t.detail } },
    })),
  resetTurn: () => set({ steps: {}, sources: [] }),
  reset: () => set((s) => ({ ...initial, lang: s.lang, consent: s.consent })),
}));
