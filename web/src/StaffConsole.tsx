import { Box, Flex, Input, Text } from "@chakra-ui/react";
import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";
import { sfx } from "./audio/sfx";

interface Handover {
  id: string; session_id: string; reason: string; urgency: "emergency" | "urgent" | "routine"; category: string; source: string;
  status: "waiting" | "connected" | "resolved" | "abandoned"; created_at: number; accepted_by: string | null;
  summary: null | { summary: string; caller_request: string; urgency: string; notes_for_staff: string };
  transcript?: { role: string; text: string; ts: number }[];
}

const COLORS = { emergency: "var(--bad)", urgent: "var(--warn)", routine: "#0A0A0A" } as const;
const TOKEN_KEY = "staff_token";

export default function StaffConsole() {
  const [token, setToken] = useState<string | null>(() => sessionStorage.getItem(TOKEN_KEY));
  const [pin, setPin] = useState("");
  const [authed, setAuthed] = useState(false);
  const [items, setItems] = useState<Record<string, Handover>>({});
  const [sel, setSel] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const ws = useRef<WebSocket | null>(null);

  const upsert = useCallback((h: Handover) => setItems((m) => ({ ...m, [h.id]: { ...m[h.id], ...h } })), []);

  const connect = useCallback((tk: string) => {
    ws.current?.close();
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const s = new WebSocket(`${proto}://${location.host}/ws/staff`);
    ws.current = s;
    s.onopen = () => s.send(JSON.stringify({ type: "auth", token: tk }));
    s.onclose = (e) => { setAuthed(false); if (e.code === 4401) { sessionStorage.removeItem(TOKEN_KEY); setToken(null); setErr("Session expired. Please sign in again."); } };
    s.onmessage = (ev) => {
      const m = JSON.parse(ev.data);
      if (m.type === "snapshot") { setAuthed(true); setErr(null); setItems(Object.fromEntries((m.handovers as Handover[]).map((h) => [h.id, h]))); }
      if (m.type === "handover_created") { upsert(m.handover); setSel((cur) => cur ?? m.handover.id); if (m.handover.urgency === "emergency") sfx.alert(); }
      if (m.type === "handover_updated") upsert(m.handover);
    };
  }, [upsert]);

  useEffect(() => { if (token) connect(token); return () => ws.current?.close(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [token]);

  const login = async () => {
    setErr(null);
    try {
      const r = await fetch("/api/staff/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ pin }) });
      if (r.status === 429) { setErr("Too many attempts. Try again later."); return; }
      if (!r.ok) { setErr("Wrong PIN"); return; }
      const j = await r.json();
      sessionStorage.setItem(TOKEN_KEY, j.token);
      setPin("");
      setToken(j.token);
    } catch { setErr("Could not reach the server"); }
  };

  const api = async (path: string, method = "GET") => {
    const r = await fetch(path, { method, headers: { Authorization: `Bearer ${token}` } });
    if (!r.ok) throw new Error(`${r.status}`);
    return r.json();
  };
  const select = async (id: string) => { setSel(id); try { upsert(await api(`/api/staff/handovers/${id}`)); } catch { /* ignore */ } };
  const act = async (id: string, what: "accept" | "resolve") => { try { upsert(await api(`/api/staff/handovers/${id}/${what}`, "POST")); if (what === "accept") sfx.connect(); } catch (e) { setErr(`Action failed (${(e as Error).message})`); } };

  const list = Object.values(items).sort((a, b) => b.created_at - a.created_at);
  const cur = sel ? items[sel] : undefined;
  const style = { ["--accent" as string]: "#0A0A0A",  } as CSSProperties;

  if (!token || !authed) {
    return (
      <Flex h="100dvh" align="center" justify="center" position="relative" style={style}>
        <div className="ambient" />
        <Box className="glass" borderRadius="24px" p="34px" zIndex={2} w="min(380px, 92vw)">
          <Text fontWeight="600" fontSize="30px" lineHeight="1" letterSpacing="-0.02em">Staff</Text>
          <Text color="var(--muted)" fontSize="13.5px" mt="6px" mb="20px">Live hand-overs from Hania. Demo access.</Text>
          <Input type="password" value={pin} onChange={(e) => setPin(e.target.value)} onKeyDown={(e) => e.key === "Enter" && void login()} placeholder="Staff PIN" autoFocus
            borderRadius="14px" border="1px solid var(--line)" bg="#FFFFFF" h="46px" mb="12px" _focus={{ borderColor: "var(--accent)", outline: "none" }} />
          {err && <Text color="var(--bad)" fontSize="13px" mb="10px">{err}</Text>}
          <button className="ctl pill primary" style={{ width: "100%" }} onClick={() => void login()}>Sign in</button>
        </Box>
      </Flex>
    );
  }

  return (
    <Flex direction="column" h="100dvh" position="relative" style={style}>
      <div className="ambient" />
      <Flex zIndex={2} px={{ base: "16px", md: "28px" }} pt="20px" pb="10px" align="baseline" justify="space-between">
        <Text fontWeight="600" fontSize="24px" lineHeight="1" letterSpacing="-0.02em">Staff</Text>
        <Text fontSize="12.5px" color="var(--muted)">{list.filter((h) => h.status === "waiting").length} waiting · simulated transfer</Text>
      </Flex>
      <Box flex="1" minH={0} zIndex={2} display="grid" gridTemplateColumns={{ base: "1fr", md: "340px 1fr" }} gap="14px" px={{ base: "12px", md: "28px" }} pb="20px" overflow="hidden">
        <Flex direction="column" gap="10px" overflowY="auto" minH={0}>
          {list.length === 0 && <Box className="glass" borderRadius="18px" p="20px"><Text color="var(--muted)" fontSize="14px">No hand-overs yet.</Text></Box>}
          <AnimatePresence initial={false}>
            {list.map((h) => (
              <motion.div key={h.id} layout initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
                <Box className="glass" borderRadius="18px" p="14px 16px" cursor="pointer" onClick={() => void select(h.id)} boxShadow="none"
                  borderColor={sel === h.id ? COLORS[h.urgency] : undefined}>
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
                  <button className="ctl pill" disabled={cur.status === "resolved"} onClick={() => void act(cur.id, "resolve")} style={{ height: 42 }}>Resolve</button>
                </Flex>
              </Flex>
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
      {err && <Text zIndex={3} position="absolute" bottom="10px" left="50%" transform="translateX(-50%)" color="var(--bad)" fontSize="13px">{err}</Text>}
    </Flex>
  );
}
