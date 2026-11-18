import { Box, Flex, Text } from "@chakra-ui/react";
import { useCallback, useEffect, useState } from "react";
import { TIER_LABEL, TierBadge, type Api } from "./common";

interface Row { session_id: string; started_at: string; language: string; outcome: string | null; turns: number; tier: string | null; topic: string; thumbs_up: number; thumbs_down: number; reviewed: number; role: string }
interface Detail {
  session_id: string; language: string; outcome: string | null;
  utterances: { id: number; speaker: string; text: string; intent: string | null }[];
  reviews: { utterance_id: number; verdict: string; correction: string; expected_tier: string | null; reviewer: string }[];
  feedback: { rating: string; comment: string; assistant_text: string; role: string }[];
  triage: { tier: string; topic: string; age_group: string; source: string; brief: { reasons?: string[]; answers?: { q: string; a: string }[] } }[];
}

const VERDICT_COLOR: Record<string, string> = { safe: "var(--ok)", unsafe: "var(--bad)", wrong: "var(--warn)" };

function Verdict({ sid, uid, existing, api, done }: { sid: string; uid: number; existing?: Detail["reviews"][number]; api: Api; done: () => void }) {
  const [mode, setMode] = useState<"" | "unsafe" | "wrong">("");
  const [text, setText] = useState("");
  const [tier, setTier] = useState("");
  const [err, setErr] = useState("");
  const send = async (verdict: string) => {
    try { await api(`/api/review/sessions/${sid}/verdict`, "POST", { utterance_id: uid, verdict, correction: text, expected_tier: tier || null }); setMode(""); setText(""); setTier(""); setErr(""); done(); }
    catch (e) { setErr((e as Error).message); }
  };
  return (
    <Box mt="6px">
      <Flex gap="6px" align="center" wrap="wrap">
        <button className="ctl sm" onClick={() => void send("safe")}>✓ Safe &amp; correct</button>
        <button className="ctl sm" onClick={() => setMode("wrong")}>Wrong</button>
        <button className="ctl sm danger" onClick={() => setMode("unsafe")}>Unsafe</button>
        {existing && <Text fontSize="12px" color={VERDICT_COLOR[existing.verdict]}>Your verdict: {existing.verdict}{existing.expected_tier ? ` · should be: ${TIER_LABEL[existing.expected_tier]}` : ""}</Text>}
      </Flex>
      {mode && (
        <Box mt="8px" p="10px" border="1px solid var(--line)" borderRadius="12px">
          <Text fontSize="12.5px" color="var(--muted)" mb="6px">{mode === "unsafe" ? "What could this answer cause, and what should she have said?" : "What should she have said instead?"}</Text>
          <textarea value={text} onChange={(e) => setText(e.target.value)} rows={3} style={{ width: "100%", border: "1px solid var(--line)", borderRadius: 10, padding: 8, fontFamily: "inherit", fontSize: 13.5 }} />
          <Flex gap="8px" mt="6px" align="center" wrap="wrap">
            <select value={tier} onChange={(e) => setTier(e.target.value)} className="ctl sm" style={{ appearance: "none", padding: "0 12px" }}>
              <option value="">Correct urgency (optional)</option>
              {Object.entries(TIER_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
            <button className="ctl sm primary" onClick={() => void send(mode)}>Save verdict</button>
            <button className="ctl sm" onClick={() => setMode("")}>Cancel</button>
            {err && <Text fontSize="12.5px" color="var(--bad)">{err}</Text>}
          </Flex>
        </Box>
      )}
    </Box>
  );
}

export default function ReviewTab({ api }: { api: Api }) {
  const [rows, setRows] = useState<Row[]>([]);
  const [flagged, setFlagged] = useState(true);
  const [sel, setSel] = useState<string | null>(null);
  const [d, setD] = useState<Detail | null>(null);
  const [err, setErr] = useState("");
  const list = useCallback(async () => { try { setRows(await api<Row[]>(`/api/review/sessions?flagged=${flagged ? 1 : 0}`)); setErr(""); } catch (e) { setErr(`Could not load (${(e as Error).message})`); } }, [api, flagged]);
  const open = useCallback(async (id: string) => { setSel(id); try { setD(await api<Detail>(`/api/review/sessions/${id}`)); } catch { /* ignore */ } }, [api]);
  useEffect(() => { void list(); }, [list]);

  const exportJson = async () => {
    const data = await api("/api/review/export");
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
    const a = document.createElement("a"); a.href = url; a.download = "doctor-corrections.json"; a.click(); URL.revokeObjectURL(url);
  };
  const byUt = Object.fromEntries((d?.reviews ?? []).map((r) => [r.utterance_id, r]));

  return (
    <Box display="grid" gridTemplateColumns={{ base: "1fr", md: "340px 1fr" }} gap="14px" minH={0} flex="1" overflow="hidden">
      <Flex direction="column" gap="8px" overflowY="auto" minH={0}>
        <Flex gap="8px" wrap="wrap">
          <button className={`ctl sm ${flagged ? "primary" : ""}`} onClick={() => setFlagged(true)}>Needs attention</button>
          <button className={`ctl sm ${!flagged ? "primary" : ""}`} onClick={() => setFlagged(false)}>All calls</button>
          <button className="ctl sm" onClick={() => void exportJson()} title="Download every unsafe/wrong verdict as test cases">Export corrections</button>
        </Flex>
        {err && <Text fontSize="12.5px" color="var(--bad)">{err}</Text>}
        {rows.length === 0 && <Box className="glass" borderRadius="14px" p="16px"><Text fontSize="14px" color="var(--muted)">{flagged ? "Nothing flagged. Thumbs-down answers, same-day or emergency tiers and hand-overs appear here." : "No calls with a transcript yet."}</Text></Box>}
        {rows.map((r) => (
          <Box key={r.session_id} className="glass" borderRadius="14px" p="12px 14px" cursor="pointer" borderColor={sel === r.session_id ? "var(--fg)" : undefined} onClick={() => void open(r.session_id)}>
            <Flex justify="space-between" fontSize="12px" color="var(--muted)"><span>{new Date(r.started_at).toLocaleString([], { hour12: false, month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}</span><span>{r.role} · {r.language}</span></Flex>
            <Text fontSize="15px" mt="3px" textTransform="capitalize">{r.topic || r.outcome || "conversation"}</Text>
            <Flex justify="space-between" mt="3px" align="center"><TierBadge tier={r.tier} /><Text fontSize="12px" color="var(--muted)">{r.thumbs_down ? `👎 ${r.thumbs_down} ` : ""}{r.thumbs_up ? `👍 ${r.thumbs_up} ` : ""}{r.reviewed ? `· reviewed ${r.reviewed}` : ""}</Text></Flex>
          </Box>
        ))}
      </Flex>
      <Box className="glass" borderRadius="18px" p="18px 20px" overflowY="auto" minH={0}>
        {!d ? <Text color="var(--muted)">Pick a call to review. Mark each thing Hania said as safe, wrong or unsafe. Wrong and unsafe verdicts become new test cases.</Text> : (
          <>
            <Flex justify="space-between" wrap="wrap" gap="8px" mb="12px"><Text fontWeight="600" fontSize="20px" letterSpacing="-0.015em">Call {d.session_id}</Text><Text fontSize="12.5px" color="var(--muted)">{d.language} · {d.outcome ?? "in progress"}</Text></Flex>
            {d.triage.length > 0 && (
              <Box mb="14px" p="10px 12px" bg="var(--panel)" borderRadius="12px" fontSize="13px">
                {d.triage.slice(-2).map((t, i) => (
                  <Box key={i} mb="4px"><TierBadge tier={t.tier} /> <span style={{ color: "var(--muted)" }}>· {t.topic || "—"} · {t.age_group.replace("_", " ")} · {t.source}</span>
                    {(t.brief.reasons ?? []).map((x, j) => <Text key={j} fontSize="12px" color="var(--muted)">{x}</Text>)}
                    {(t.brief.answers ?? []).map((a, j) => <Text key={`a${j}`} fontSize="12px" color="var(--muted)">• {a.q} → {a.a}</Text>)}</Box>
                ))}
              </Box>
            )}
            {d.feedback.map((f, i) => <Text key={i} fontSize="13px" mb="6px" color={f.rating === "down" ? "var(--bad)" : "var(--ok)"}>{f.rating === "down" ? "👎" : "👍"} {f.role}: {f.comment || "(no comment)"}</Text>)}
            <Flex direction="column" gap="12px" fontSize="14.5px" mt="8px">
              {d.utterances.map((u) => (
                <Box key={u.id}>
                  <Flex gap="12px"><Text minW="64px" fontSize="12px" color={u.speaker === "caller" ? "var(--warn)" : "var(--fg)"} textTransform="capitalize" pt="2px">{u.speaker === "caller" ? "Patient" : "Hania"}</Text><Text flex="1" lineHeight="1.5">{u.text}</Text></Flex>
                  {u.speaker === "assistant" && <Box pl="76px"><Verdict sid={d.session_id} uid={u.id} existing={byUt[u.id]} api={api} done={() => { void open(d.session_id); void list(); }} /></Box>}
                </Box>
              ))}
            </Flex>
          </>
        )}
      </Box>
    </Box>
  );
}
