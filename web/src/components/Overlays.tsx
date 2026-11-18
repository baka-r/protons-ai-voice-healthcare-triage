import { Box, Text } from "@chakra-ui/react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect } from "react";
import { call } from "../net/call";
import { useStore, type Status, type Tester } from "../store";

const TESTERS: [Tester, string][] = [["patient", "Patient"], ["qa", "QA tester"], ["doctor", "Doctor"], ["owner", "Owner"]];

/** Shown under the idle orb before a call begins. */
export function StartBlock() {
  const phase = useStore((s) => s.phase);
  const status = useStore((s) => s.status);
  useEffect(() => {
    let stop = false;
    const poll = async () => {
      try {
        const s: Status = await (await fetch("/api/status")).json();
        if (!stop) useStore.getState().set({ status: s });
      } catch { if (!stop) useStore.getState().set({ status: null }); }
    };
    void poll();
    const i = setInterval(poll, 2500);
    return () => { stop = true; clearInterval(i); };
  }, []);

  const tester = useStore((s) => s.tester);
  const consent = useStore((s) => s.consent);
  const core = !!status && status.voice && status.records && status.db;
  const warm = !!status?.voice_cache;
  const connecting = phase === "connecting";
  const note = !status ? "Connecting…" : !core ? "Getting ready…" : !warm ? "Warming up my voice…" : status.llm_busy ? "The AI is busy right now, so I may be slower and simpler for a moment." : "";
  const pick = (t: Tester) => { useStore.getState().set({ tester: t }); try { localStorage.setItem("hania_tester", t); } catch { /* storage unavailable */ } };

  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }} style={{ textAlign: "center", padding: "0 24px", maxWidth: 520 }}>
      <Text fontWeight="600" fontSize={{ base: "30px", md: "38px" }} lineHeight="1.1" letterSpacing="-0.025em">Hi, I’m Hania.</Text>
      <Text color="var(--muted)" fontSize={{ base: "15px", md: "17px" }} mt="10px">Ask me about your health, appointments, or anything about the hospital. You can speak English, हिन्दी or اردو.</Text>
      <Box mt="22px">
        <Text fontSize="12px" color="var(--muted)" mb="8px">I’m testing as</Text>
        <Box display="flex" justifyContent="center" flexWrap="wrap" gap="8px" role="radiogroup" aria-label="Who is testing">
          {TESTERS.map(([key, label]) => (
            <button key={key} role="radio" aria-checked={tester === key} className={`ctl sm ${tester === key ? "primary" : ""}`} onClick={() => pick(key)}>{label}</button>
          ))}
        </Box>
      </Box>
      <label style={{ display: "flex", gap: 10, alignItems: "flex-start", justifyContent: "center", textAlign: "left", marginTop: 20, fontSize: 12.5, lineHeight: 1.5, cursor: "pointer", color: "var(--muted)" }}>
        <input type="checkbox" checked={consent} onChange={(e) => useStore.getState().set({ consent: e.target.checked })} style={{ marginTop: 3, accentColor: "#0A0A0A" }} />
        <span>
          I understand Hania is an <b style={{ color: "var(--fg)" }}>AI testing agent, not a doctor</b>, and that this is a test: my conversation (with names, phone numbers and ID numbers masked) is stored
          for quality review by hospital staff and doctors. In an emergency I will call 1122.
        </span>
      </label>
      <Box mt="18px" h="48px">
        <button className="ctl pill primary" disabled={!core || !warm || connecting || !consent} onClick={() => void call.begin()} style={{ fontSize: 15 }}>
          {connecting ? "Connecting…" : "Start conversation"}
        </button>
      </Box>
      <Box minH="18px" mt="10px" fontSize="12.5px" color="var(--muted)">{note || (!consent ? "Tick the box to start." : "")}</Box>
      <Text fontSize="12px" color="var(--muted)" mt="8px" lineHeight="1.55">
        Demo with synthetic hospital data. Please do not share real personal or medical details.
      </Text>
    </motion.div>
  );
}

export function HandoverBanner() {
  const h = useStore((s) => s.handover);
  const mode = useStore((s) => s.mode);
  const color = h?.status === "connected" ? "var(--ok)" : mode === "emergency" ? "var(--bad)" : "var(--warn)";
  return (
    <AnimatePresence>
      {h && (
        <motion.div initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.35 }}
          style={{ position: "absolute", top: 4, left: 0, right: 0, display: "flex", justifyContent: "center", zIndex: 4, pointerEvents: "none" }}>
          <Box border="1px solid var(--line)" bg="#fff" borderRadius="22px" px="18px" py="9px" display="flex" alignItems="center" gap="10px" fontSize="13.5px">
            <span style={{ width: 8, height: 8, borderRadius: "50%", background: color }} />
            <span style={{ fontWeight: 500 }}>
              {h.status === "connected" ? `Connected to ${h.staff ?? "a team member"}` : mode === "emergency" ? "Alerting our team now" : "Connecting you to a team member"}
            </span>
            <span style={{ color: "var(--muted)" }}>{h.status === "connected" ? "Demo transfer" : h.id}</span>
          </Box>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

export function EndedOverlay() {
  const error = useStore((s) => s.error);
  return (
    <Box position="absolute" inset="0" zIndex={9} display="flex" alignItems="center" justifyContent="center" bg="#fff">
      <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} style={{ textAlign: "center", padding: 24 }}>
        <Text fontWeight="600" fontSize="30px" letterSpacing="-0.02em">Call ended</Text>
        {error && <Text color="var(--warn)" fontSize="13px" mt="6px">{error}</Text>}
        <Text color="var(--muted)" fontSize="15px" mt="8px" mb="24px">Thanks for calling.</Text>
        <button className="ctl pill primary" onClick={() => useStore.getState().reset()}>Start again</button>
      </motion.div>
    </Box>
  );
}
