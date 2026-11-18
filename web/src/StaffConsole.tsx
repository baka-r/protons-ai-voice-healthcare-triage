import { Box, Flex, Input, Text } from "@chakra-ui/react";
import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";
import { sfx } from "./audio/sfx";
import AccountsTab from "./staff/AccountsTab";
import { TierBadge, type Api } from "./staff/common";
import OwnerTab from "./staff/OwnerTab";
import ReviewTab from "./staff/ReviewTab";

interface Brief { topic: string; age: number | null; age_group: string; answers: { q: string; a: string }[]; tier: string | null; reasons: string[]; language: string; source: string }
interface Handover {
  id: string; session_id: string; reason: string; urgency: "emergency" | "urgent" | "routine"; category: string; source: string;
  status: "waiting" | "connected" | "resolved" | "abandoned" | "cancelled"; created_at: number; accepted_by: string | null;
  summary: null | { summary: string; caller_request: string; urgency: string; notes_for_staff: string };
  brief?: Brief | null;
  transcript?: { role: string; text: string; ts: number }[];
}
type Role = "support" | "clinician" | "admin";
type Tab = "handovers" | "review" | "owner" | "accounts";

const COLORS = { emergency: "var(--bad)", urgent: "var(--warn)", routine: "#0A0A0A" } as const;
const KEY = "staff_session";
interface Saved { token: string; role: Role; name: string }

function loadSaved(): Saved | null {
  try { const v = sessionStorage.getItem(KEY); return v ? (JSON.parse(v) as Saved) : null; } catch { return null; }
}

export default function StaffConsole() {
  const [me, setMe] = useState<Saved | null>(loadSaved);
  const [mode, setMode] = useState<"account" | "pin">("account");
  const [username, setUsername] = useState("");
  const [secret, setSecret] = useState("");
  const [authed, setAuthed] = useState(false);
  const [tab, setTab] = useState<Tab>("handovers");
  const [items, setItems] = useState<Record<string, Handover>>({});
  const [sel, setSel] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const ws = useRef<WebSocket | null>(null);
  const token = me?.token ?? null;

  const upsert = useCallback((h: Handover) => setItems((m) => ({ ...m, [h.id]: { ...m[h.id], ...h } })), []);
  const signOut = useCallback((why?: string) => { sessionStorage.removeItem(KEY); setMe(null); setAuthed(false); setErr(why ?? null); }, []);

  const connect = useCallback((tk: string) => {
    ws.current?.close();
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const s = new WebSocket(`${proto}://${location.host}/ws/staff`);
    ws.current = s;
    s.onopen = () => s.send(JSON.stringify({ type: "auth", token: tk }));
    s.onclose = (e) => { setAuthed(false); if (e.code === 4401) signOut("Session expired. Please sign in again."); };
    s.onmessage = (ev) => {
      const m = JSON.parse(ev.data);
      if (m.type === "snapshot") { setAuthed(true); setErr(null); setItems(Object.fromEntries((m.handovers as Handover[]).map((h) => [h.id, h]))); }
      if (m.type === "handover_created") { upsert(m.handover); setSel((cur) => cur ?? m.handover.id); if (m.handover.urgency === "emergency") sfx.alert(); }
      if (m.type === "handover_updated") upsert(m.handover);
    };
  }, [upsert, signOut]);

  useEffect(() => { if (token) connect(token); return () => ws.current?.close(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [token]);

  const login = async () => {
    setErr(null);
    try {
      const body = mode === "pin" ? { pin: secret } : { username, password: secret };
      const r = await fetch("/api/staff/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      if (r.status === 429) { setErr("Too many attempts. Try again later."); return; }
      if (!r.ok) { setErr(mode === "pin" ? "Wrong PIN" : "Wrong username or password"); return; }
      const j = await r.json();
      const saved: Saved = { token: j.token, role: j.role, name: j.name };
      sessionStorage.setItem(KEY, JSON.stringify(saved));
      setSecret("");
      setMe(saved);
    } catch { setErr("Could not reach the server"); }
  };

  const api: Api = useCallback(async (path, method = "GET", body) => {
    const r = await fetch(path, { method, headers: { Authorization: `Bearer ${token}`, ...(body ? { "Content-Type": "application/json" } : {}) }, body: body ? JSON.stringify(body) : undefined });
    if (r.status === 401) { signOut("Session expired. Please sign in again."); throw new Error("401"); }
    if (!r.ok) { const j = await r.json().catch(() => ({})); throw new Error(typeof j.detail === "string" ? j.detail : String(r.status)); }
    return r.json();
  }, [token, signOut]);

  const select = async (id: string) => { setSel(id); try { upsert(await api(`/api/staff/handovers/${id}`)); } catch { /* ignore */ } };
  const act = async (id: string, what: "accept" | "resolve") => { try { upsert(await api(`/api/staff/handovers/${id}/${what}`, "POST")); if (what === "accept") sfx.connect(); } catch (e) { setErr(`Action failed (${(e as Error).message})`); } };

  const list = Object.values(items).sort((a, b) => b.created_at - a.created_at);
  const cur = sel ? items[sel] : undefined;
  const style = { ["--accent" as string]: "#0A0A0A" } as CSSProperties;
  const role = me?.role ?? "support";
  const tabs: [Tab, string][] = [["handovers", "Hand-overs"], ...(role !== "support" ? [["review", "Doctor review"] as [Tab, string]] : []),
    ...(role === "admin" ? [["owner", "Owner"] as [Tab, string], ["accounts", "Accounts"] as [Tab, string]] : [])];

  if (!token || !authed) {
    return (
      <Flex h="100dvh" align="center" justify="center" position="relative" style={style}>
        <div className="ambient" />
        <Box className="glass" borderRadius="24px" p="34px" zIndex={2} w="min(400px, 92vw)">
          <Text fontWeight="600" fontSize="30px" lineHeight="1" letterSpacing="-0.02em">Staff</Text>
          <Text color="var(--muted)" fontSize="13.5px" mt="6px" mb="16px">Hand-overs, doctor review and owner dashboard.</Text>
          <Flex gap="8px" mb="14px">
            <button className={`ctl sm ${mode === "account" ? "primary" : ""}`} onClick={() => setMode("account")}>My account</button>
            <button className={`ctl sm ${mode === "pin" ? "primary" : ""}`} onClick={() => setMode("pin")}>Desk PIN</button>
          </Flex>
          {mode === "account" && <Input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="Username" autoFocus autoCapitalize="none" borderRadius="14px" border="1px solid var(--line)" bg="#FFFFFF" h="46px" mb="10px" />}
          <Input type="password" value={secret} onChange={(e) => setSecret(e.target.value)} onKeyDown={(e) => e.key === "Enter" && void login()} placeholder={mode === "pin" ? "Staff PIN" : "Password"} autoFocus={mode === "pin"}
            borderRadius="14px" border="1px solid var(--line)" bg="#FFFFFF" h="46px" mb="12px" _focus={{ borderColor: "var(--accent)", outline: "none" }} />
          {err && <Text color="var(--bad)" fontSize="13px" mb="10px">{err}</Text>}
          <button className="ctl pill primary" style={{ width: "100%" }} onClick={() => void login()}>Sign in</button>
          <Text color="var(--muted)" fontSize="12px" mt="12px">The desk PIN only opens the hand-over queue. Doctors and the owner use their own account.</Text>
        </Box>
      </Flex>
    );
  }

  return (
    <Flex direction="column" h="100dvh" position="relative" style={style}>
      <div className="ambient" />
      <Flex zIndex={2} px={{ base: "16px", md: "28px" }} pt="20px" pb="10px" align="center" justify="space-between" wrap="wrap" gap="10px">
        <Flex align="baseline" gap="18px" wrap="wrap">
          <Text fontWeight="600" fontSize="24px" lineHeight="1" letterSpacing="-0.02em">Staff</Text>
          <Flex gap="6px" wrap="wrap">{tabs.map(([k, label]) => <button key={k} className={`ctl sm ${tab === k ? "primary" : ""}`} onClick={() => setTab(k)}>{label}{k === "handovers" && list.some((h) => h.status === "waiting") ? ` (${list.filter((h) => h.status === "waiting").length})` : ""}</button>)}</Flex>
        </Flex>
        <Flex align="center" gap="12px"><Text fontSize="12.5px" color="var(--muted)">{me?.name} · {role}</Text><button className="link" onClick={() => signOut()}>Sign out</button></Flex>
      </Flex>

      <Box flex="1" minH={0} zIndex={2} px={{ base: "12px", md: "28px" }} pb="20px" display="flex" flexDirection="column" overflow="hidden">
        {tab === "review" && <ReviewTab api={api} />}
        {tab === "owner" && <OwnerTab api={api} />}
        {tab === "accounts" && <AccountsTab api={api} />}
        {tab === "handovers" && (
          <Box flex="1" minH={0} display="grid" gridTemplateColumns={{ base: "1fr", md: "340px 1fr" }} gap="14px" overflow="hidden">
            <Flex direction="column" gap="10px" overflowY="auto" minH={0}>
              <Text fontSize="12.5px" color="var(--muted)">{list.filter((h) => h.status === "waiting").length} waiting · simulated transfer</Text>
              {list.length === 0 && <Box className="glass" borderRadius="18px" p="20px"><Text color="var(--muted)" fontSize="14px">No hand-overs yet.</Text></Box>}
              <AnimatePresence initial={false}>
                {list.map((h) => (
                  <motion.div key={h.id} layout initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
                    <Box className="glass" borderRadius="18px" p="14px 16px" cursor="pointer" onClick={() => void select(h.id)} boxShadow="none" borderColor={sel === h.id ? COLORS[h.urgency] : undefined}>
                      <Flex justify="space-between" align="center">
                        <Flex align="center" gap="8px"><span className="dot" style={{ background: COLORS[h.urgency] }} /><Text fontSize="12px" color={COLORS[h.urgency]} textTransform="capitalize" fontWeight="500">{h.urgency}</Text></Flex>
                        <Text fontSize="11.5px" color="var(--muted)">{h.id}</Text>
                      </Flex>
                      <Text fontSize="16px" mt="6px" textTransform="capitalize">{h.reason.replace(/_/g, " ")}</Text>
                      <Flex justify="space-between" mt="2px">
                        <Text fontSize="12px" color="var(--muted)">{new Date(h.created_at * 1000).toLocaleTimeString([], { hour12: false })}</Text>
                        <Text fontSize="12px" color={h.status === "waiting" ? "var(--warn)" : h.status === "connected" ? "var(--ok)" : "var(--muted)"} textTransform="capitalize">{h.status}</Text>
                      </Flex>
                    </Box>
                  </motion.div>
                ))}
              </AnimatePresence>
            </Flex>

            <Box className="glass" borderRadius="22px" p="22px" overflowY="auto" minH={0} boxShadow="none">
              {!cur ? <Text color="var(--muted)">Select a hand-over.</Text> : (
                <>
                  <Flex justify="space-between" align="flex-start" wrap="wrap" gap="12px" mb="18px">
                    <Box>
                      <Text fontWeight="600" fontSize="24px" lineHeight="1.15" letterSpacing="-0.02em" textTransform="capitalize">{cur.reason.replace(/_/g, " ")}</Text>
                      <Text fontSize="12px" color="var(--muted)" mt="6px">{cur.id} · session {cur.session_id} · flagged by {cur.source}{cur.category ? ` · ${cur.category}` : ""}</Text>
                    </Box>
                    <Flex gap="8px">
                      <button className="ctl pill primary" disabled={cur.status !== "waiting"} onClick={() => void act(cur.id, "accept")} style={{ height: 42 }}>Accept call</button>
                      <button className="ctl pill" disabled={cur.status === "resolved" || cur.status === "cancelled"} onClick={() => void act(cur.id, "resolve")} style={{ height: 42 }}>Resolve</button>
                    </Flex>
                  </Flex>
                  {cur.brief && (
                    <>
                      <div className="label" style={{ marginBottom: 8 }}>Clinical brief · suggested urgency, not a diagnosis</div>
                      <Box mb="20px" p="12px 14px" bg="var(--panel)" borderRadius="14px" fontSize="14px" lineHeight="1.55">
                        <Flex gap="12px" align="center" wrap="wrap"><TierBadge tier={cur.brief.tier} /><span style={{ color: "var(--muted)" }}>
                          {[cur.brief.topic, cur.brief.age != null ? `age ${cur.brief.age}` : cur.brief.age_group !== "unknown" ? cur.brief.age_group.replace("_", " ") : "age not given", cur.brief.language, cur.brief.source].filter(Boolean).join(" · ")}</span></Flex>
                        {cur.brief.reasons.map((r, i) => <Text key={i} fontSize="13px" color="var(--muted)">• {r}</Text>)}
                        {cur.brief.answers.map((a, i) => <Text key={`a${i}`} fontSize="13px" color="var(--muted)">Q: {a.q} → {a.a}</Text>)}
                      </Box>
                    </>
                  )}
                  <div className="label" style={{ marginBottom: 8 }}>Summary</div>
                  <Box mb="22px" fontSize="15px" lineHeight="1.55">
                    {cur.summary ? (<>
                      <Text>{cur.summary.summary}</Text>
                      {cur.summary.caller_request && <Text color="var(--muted)" mt="4px">Request: {cur.summary.caller_request}</Text>}
                      {cur.summary.notes_for_staff && <Text color="var(--muted)" mt="4px">Notes: {cur.summary.notes_for_staff}</Text>}
                    </>) : <Text color="var(--muted)">Generating summary…</Text>}
                    <Text fontSize="11.5px" color="var(--muted)" mt="8px">Written by AI from the transcript. It does not diagnose. Please verify with the caller.</Text>
                  </Box>
                  <div className="label" style={{ marginBottom: 8 }}>Transcript · identifiers masked</div>
                  <Flex direction="column" gap="8px" fontSize="14px">
                    {(cur.transcript ?? []).map((t, i) => (
                      <Flex key={i} gap="12px"><Text color={t.role === "caller" ? "var(--warn)" : "var(--accent)"} minW="72px" fontSize="12px" textTransform="capitalize" pt="2px">{t.role}</Text><Text flex="1">{t.text}</Text></Flex>
                    ))}
                  </Flex>
                </>
              )}
            </Box>
          </Box>
        )}
      </Box>
      {err && <Text zIndex={3} position="absolute" bottom="10px" left="50%" transform="translateX(-50%)" color="var(--bad)" fontSize="13px">{err}</Text>}
    </Flex>
  );
}
