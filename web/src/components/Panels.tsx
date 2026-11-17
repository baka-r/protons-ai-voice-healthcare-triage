import { Box, Flex, Text } from "@chakra-ui/react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useRef, type ReactNode } from "react";
import { FiVolume2, FiVolumeX, FiX } from "react-icons/fi";
import { setSfxEnabled } from "../audio/sfx";
import { useStore } from "../store";

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Box py="18px" borderTop="1px solid var(--line)">
      <div className="label" style={{ marginBottom: 12 }}>{title}</div>
      {children}
    </Box>
  );
}

const SAFETY_ITEMS: { key: string; label: string; hint: Record<string, string> }[] = [
  { key: "redflag", label: "Red-flag check", hint: { ok: "clear", alert: "flagged" } },
  { key: "scope", label: "Scope guard", hint: { ok: "in scope", block: "redirected" } },
  { key: "pii", label: "Privacy shield", hint: { on: "on" } },
  { key: "llm_check", label: "AI safety net", hint: { ok: "clear", alert: "flagged", skip: "n/a", offline: "offline", pending: "checking" } },
];

function SafetySection() {
  const safety = useStore((s) => s.safety);
  return (
    <Section title="Safety">
      <Flex direction="column" gap="11px">
        {SAFETY_ITEMS.map((it) => {
          const v = safety[it.key] ?? "idle";
          return (
            <Flex key={it.key} align="center" gap="10px" fontSize="14px">
              <span className={`dot ${v === "pending" ? "run" : v}`} />
              <Text flex="1">{it.label}</Text>
              <Text fontSize="12.5px" color="var(--muted)">{it.hint[v] ?? v}</Text>
            </Flex>
          );
        })}
      </Flex>
      <Text mt="14px" fontSize="12.5px" color="var(--muted)" lineHeight="1.55">
        Fixed rules decide safety; the AI can only add caution. Hania shares approved general guidance but never diagnoses or advises on medicines.
      </Text>
    </Section>
  );
}

const STEPS = [["listen", "Listen"], ["transcribe", "Transcribe"], ["safety", "Safety check"], ["understand", "Understand"], ["route", "Decide"], ["respond", "Respond"]] as const;

function PipelineSection() {
  const steps = useStore((s) => s.steps);
  return (
    <Section title="How she thinks">
      <Flex direction="column" gap="10px">
        {STEPS.map(([key, label]) => {
          const cur = steps[key];
          return (
            <Flex key={key} align="center" gap="10px" fontSize="14px" opacity={cur ? 1 : 0.45}>
              <span className={`dot ${cur?.status ?? "idle"}`} />
              <Text flex="1">{label}</Text>
              <Text fontSize="12px" color="var(--muted)" maxW="170px" lineClamp={1}>{cur?.detail}</Text>
            </Flex>
          );
        })}
      </Flex>
    </Section>
  );
}

function Stat({ label, v, good }: { label: string; v?: number | null; good: number }) {
  return (
    <Box>
      <Text fontSize="12px" color="var(--muted)">{label}</Text>
      <Text fontSize="22px" fontWeight="500" letterSpacing="-0.02em" color={v == null ? "var(--muted)" : v <= good ? "var(--fg)" : "var(--warn)"}>
        {v == null ? "—" : v}<span style={{ fontSize: 12, marginLeft: 3, color: "var(--muted)", fontWeight: 400 }}>ms</span>
      </Text>
    </Box>
  );
}

function LatencySection() {
  const t = useStore((s) => s.timing);
  return (
    <Section title="Speed">
      <Flex wrap="wrap" gap="16px 30px">
        <Stat label="Voice to voice" v={t.e2e_ms} good={2000} />
        <Stat label="Speech to text" v={t.stt_ms} good={700} />
        <Stat label="Understanding" v={t.nlu_ms} good={800} />
        <Stat label="First audio" v={t.tts_first_ms} good={400} />
      </Flex>
    </Section>
  );
}

function SourcesSection() {
  const sources = useStore((s) => s.sources);
  if (!sources.length) return null;
  return (
    <Section title="Approved source">
      {sources.map((s) => (
        <Text key={s.chunk_id} fontSize="14px">{s.title} {s.version > 0 && <span style={{ color: "var(--muted)", fontSize: 12.5 }}>v{s.version} · {(s.score * 100).toFixed(0)}% match</span>}</Text>
      ))}
    </Section>
  );
}

function TraceSection() {
  const trace = useStore((s) => s.trace);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [trace.length]);
  return (
    <Section title="Activity">
      <Box maxH="200px" overflowY="auto" fontSize="12.5px" lineHeight="1.6" fontFamily="mono">
        {trace.slice(-30).map((t) => (
          <div key={t.id} style={{ display: "flex", gap: 8 }}>
            <span style={{ color: t.status === "alert" ? "var(--bad)" : t.status === "ok" ? "var(--ok)" : "var(--muted)" }}>{t.status === "alert" ? "!" : t.status === "ok" ? "✓" : "·"}</span>
            <span style={{ color: "var(--muted)", minWidth: 72 }}>{t.step}</span>
            <span style={{ flex: 1 }}>{t.detail}</span>
          </div>
        ))}
        {trace.length === 0 && <Text color="var(--muted)">Nothing yet.</Text>}
        <div ref={end} />
      </Box>
    </Section>
  );
}

export function DetailsDrawer() {
  const open = useStore((s) => s.drawer);
  const sfxOn = useStore((s) => s.sfx);
  const session = useStore((s) => s.session);
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement) return;
      if (e.key === "d") useStore.getState().set({ drawer: !useStore.getState().drawer });
      if (e.key === "Escape") useStore.getState().set({ drawer: false });
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, []);
  return (
    <AnimatePresence>
      {open && (
        <motion.aside initial={{ x: 420 }} animate={{ x: 0 }} exit={{ x: 420 }} transition={{ type: "spring", stiffness: 300, damping: 34 }} aria-label="Details"
          style={{ position: "absolute", top: 0, right: 0, bottom: 0, width: "min(400px, 100vw)", zIndex: 8, background: "#fff", borderLeft: "1px solid var(--line)", padding: "22px 22px 28px", overflowY: "auto" }}>
          <Flex justify="space-between" align="center" mb="14px">
            <Box>
              <Text fontWeight="600" fontSize="20px" letterSpacing="-0.015em">Details</Text>
              <Text fontSize="12.5px" color="var(--muted)" mt="2px">{session?.hospital ?? "Demo"} · session {session?.id ?? "-"}</Text>
            </Box>
            <Flex gap="8px">
              <button className="ctl round" style={{ width: 36, height: 36, fontSize: 16 }} aria-label="Toggle sounds" onClick={() => { useStore.getState().set({ sfx: !sfxOn }); setSfxEnabled(!sfxOn); }}>{sfxOn ? <FiVolume2 /> : <FiVolumeX />}</button>
              <button className="ctl round" style={{ width: 36, height: 36, fontSize: 16 }} aria-label="Close details" onClick={() => useStore.getState().set({ drawer: false })}><FiX /></button>
            </Flex>
          </Flex>
          <SafetySection />
          <PipelineSection />
          <LatencySection />
          <SourcesSection />
          <TraceSection />
        </motion.aside>
      )}
    </AnimatePresence>
  );
}
