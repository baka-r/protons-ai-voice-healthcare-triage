import { Box, Flex, Text } from "@chakra-ui/react";
import { useCallback, useEffect, useState } from "react";
import { Big, Card, Rows, TIER_LABEL, type Api } from "./common";

interface Stats {
  days: number; calls: number; avg_turns: number; outcomes: Record<string, number>; languages: Record<string, number>;
  handovers_by_urgency: Record<string, number>; handover_status: Record<string, number>; handover_reasons: Record<string, number>;
  tiers: Record<string, number>; tier_topics: Record<string, number>; testers: Record<string, number>; feedback: Record<string, number>;
  recent_comments: { rating: string; comment: string; answer: string; role: string; at: string }[]; reviews: Record<string, number>;
  appointments: Record<string, number>; top_intents: Record<string, number>;
  live: { calls_active: number; handovers_waiting: number };
  speed: Record<string, { count: number; avg_ms: number; p50_ms: number; p95_ms: number }>;
  counters: Record<string, number>;
  ai: { llm_routes: { name: string; state: string; ok: number; fail: number }[]; stt_routes: { name: string; state: string }[]; voice_ok: boolean };
}

const SPEED_LABEL: Record<string, string> = { first_audio: "First audio (voice to voice)", stt: "Speech to text", nlu: "Understanding" };

export default function OwnerTab({ api }: { api: Api }) {
  const [days, setDays] = useState(7);
  const [s, setS] = useState<Stats | null>(null);
  const [err, setErr] = useState("");
  const [note, setNote] = useState("");
  const load = useCallback(async () => {
    try { setS(await api<Stats>(`/api/owner/stats?days=${days}`)); setErr(""); } catch (e) { setErr(`Could not load (${(e as Error).message})`); }
  }, [api, days]);
  useEffect(() => { void load(); const i = setInterval(load, 15000); return () => clearInterval(i); }, [load]);

  const up = s?.feedback?.up ?? 0, down = s?.feedback?.down ?? 0;
  const liked = up + down ? Math.round((up / (up + down)) * 100) : null;
  const handed = (s?.outcomes?.handover ?? 0);
  const rate = s?.calls ? Math.round((handed / s.calls) * 100) : 0;
  const reset = async () => { try { const r = await api<{ cleared: number }>("/api/admin/demo/reset", "POST"); setNote(`Cleared ${r.cleared} old hand-overs from the staff queue.`); } catch (e) { setNote(`Reset failed (${(e as Error).message})`); } };

  return (
    <Box overflowY="auto" minH={0} pb="24px">
      <Flex gap="8px" align="center" mb="14px" wrap="wrap">
        {[1, 7, 30].map((d) => <button key={d} className={`ctl sm ${days === d ? "primary" : ""}`} onClick={() => setDays(d)}>{d === 1 ? "Today" : `${d} days`}</button>)}
        <button className="ctl sm" onClick={() => void load()}>Refresh</button>
        <button className="ctl sm" onClick={() => void reset()} title="Clears finished hand-overs from the staff queue. Stored records and the audit log are untouched.">Reset demo queue</button>
        {note && <Text fontSize="12.5px" color="var(--muted)">{note}</Text>}
        {err && <Text fontSize="12.5px" color="var(--bad)">{err}</Text>}
      </Flex>
      {!s ? <Text color="var(--muted)">Loading…</Text> : (
        <Box display="grid" gridTemplateColumns={{ base: "1fr", md: "repeat(2, 1fr)", xl: "repeat(3, 1fr)" }} gap="12px">
          <Card title="Calls"><Flex gap="28px" wrap="wrap"><Big value={s.calls} sub={`last ${s.days} day(s)`} /><Big value={s.avg_turns} sub="turns per call" /><Big value={`${rate}%`} sub="handed to staff" /></Flex></Card>
          <Card title="Right now"><Flex gap="28px"><Big value={s.live.calls_active} sub="calls live" /><Big value={s.live.handovers_waiting} sub="hand-overs waiting" /></Flex></Card>
          <Card title="Tester feedback"><Flex gap="28px"><Big value={liked == null ? "—" : `${liked}%`} sub={`${up} 👍 · ${down} 👎`} /><Big value={Object.values(s.reviews).reduce((a, b) => a + b, 0)} sub="doctor reviews" /></Flex></Card>
          <Card title="Suggested urgency (not a diagnosis)"><Rows data={s.tiers} map={(k) => TIER_LABEL[k] ?? k} /></Card>
          <Card title="Most common health topics"><Rows data={s.tier_topics} /></Card>
          <Card title="What people ask"><Rows data={s.top_intents} /></Card>
          <Card title="Doctor verdicts"><Rows data={s.reviews} empty="No doctor reviews yet." /></Card>
          <Card title="Hand-overs by urgency"><Rows data={s.handovers_by_urgency} /></Card>
          <Card title="Hand-over reasons"><Rows data={s.handover_reasons} /></Card>
          <Card title="Who is testing"><Rows data={s.testers} /></Card>
          <Card title="Languages"><Rows data={s.languages} /></Card>
          <Card title="Appointments"><Rows data={s.appointments} /></Card>
          <Card title="Speed since last restart (ms)" wide>
            <Flex gap="30px" wrap="wrap">
              {Object.entries(s.speed).filter(([k]) => SPEED_LABEL[k]).map(([k, v]) => (
                <Big key={k} value={v.p50_ms} unit="ms" sub={`${SPEED_LABEL[k]} · typical (p50) · slowest 1 in 20: ${v.p95_ms} ms`} />
              ))}
              {!Object.keys(s.speed).length && <Text fontSize="13.5px" color="var(--muted)">No calls yet since the last restart.</Text>}
            </Flex>
          </Card>
          <Card title="AI health">
            <Flex direction="column" gap="6px" fontSize="13.5px">
              {s.ai.llm_routes.map((r) => <Flex key={r.name} justify="space-between"><span>{r.name}</span><span style={{ color: r.state === "ok" ? "var(--ok)" : "var(--warn)" }}>{r.state}</span></Flex>)}
              <Flex justify="space-between"><span>Voice engine</span><span style={{ color: s.ai.voice_ok ? "var(--ok)" : "var(--bad)" }}>{s.ai.voice_ok ? "ok" : "down"}</span></Flex>
            </Flex>
            <Text fontSize="12px" color="var(--muted)" mt="8px">“cooldown” means a free-tier key is resting after a rate limit; Hania falls back to simpler, rule-based answers meanwhile.</Text>
          </Card>
          <Card title="Latest tester comments" wide>
            {s.recent_comments.length === 0 ? <Text fontSize="13.5px" color="var(--muted)">No comments yet.</Text> : (
              <Flex direction="column" gap="10px">
                {s.recent_comments.map((c, i) => (
                  <Box key={i} fontSize="13.5px"><b style={{ color: c.rating === "down" ? "var(--bad)" : "var(--ok)" }}>{c.rating === "down" ? "👎" : "👍"}</b> {c.comment}
                    <Text fontSize="12px" color="var(--muted)">{c.role} · about: “{c.answer}”</Text></Box>
                ))}
              </Flex>
            )}
          </Card>
        </Box>
      )}
    </Box>
  );
}
