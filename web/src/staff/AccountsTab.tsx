import { Box, Flex, Input, Text } from "@chakra-ui/react";
import { useCallback, useEffect, useState } from "react";
import type { Api } from "./common";

interface Acct { username: string; name: string; role: string; active: boolean; last_login: string | null }
const ROLE_HELP: Record<string, string> = {
  support: "Hand-over desk only", clinician: "Hand-overs + doctor review", admin: "Everything, including owner dashboard and accounts",
};

export default function AccountsTab({ api }: { api: Api }) {
  const [items, setItems] = useState<Acct[]>([]);
  const [f, setF] = useState({ username: "", name: "", role: "clinician", password: "" });
  const [msg, setMsg] = useState("");
  const load = useCallback(async () => { try { setItems(await api<Acct[]>("/api/admin/accounts")); } catch (e) { setMsg(`Could not load (${(e as Error).message})`); } }, [api]);
  useEffect(() => { void load(); }, [load]);

  const create = async () => {
    try { await api("/api/admin/accounts", "POST", f); setMsg(`Created ${f.username}. Tell them their password in person; they can ask you to reset it.`); setF({ ...f, username: "", name: "", password: "" }); void load(); }
    catch (e) { setMsg((e as Error).message); }
  };
  const toggle = async (a: Acct) => { try { await api(`/api/admin/accounts/${a.username}`, "POST", { active: !a.active }); void load(); } catch (e) { setMsg((e as Error).message); } };
  const reset = async (a: Acct) => {
    const pw = window.prompt(`New password for ${a.username} (at least 10 characters)`);
    if (!pw) return;
    try { await api(`/api/admin/accounts/${a.username}`, "POST", { password: pw }); setMsg(`Password changed for ${a.username}.`); } catch (e) { setMsg((e as Error).message); }
  };
  const field = { borderRadius: "12px", border: "1px solid var(--line)", background: "#fff", height: "40px", fontSize: "14px" } as const;

  return (
    <Box overflowY="auto" minH={0} pb="24px" maxW="760px">
      <Box className="glass" borderRadius="18px" p="16px 18px" mb="14px">
        <div className="label" style={{ marginBottom: 10 }}>Add a person</div>
        <Box display="grid" gridTemplateColumns={{ base: "1fr", md: "1fr 1fr" }} gap="8px">
          <Input {...field} placeholder="Username (e.g. dr.ahmed)" value={f.username} onChange={(e) => setF({ ...f, username: e.target.value })} />
          <Input {...field} placeholder="Full name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
          <select className="ctl" style={{ appearance: "none", padding: "0 14px", height: 40, borderRadius: 12, justifyContent: "flex-start" }} value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}>
            {Object.keys(ROLE_HELP).map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
          <Input {...field} type="password" placeholder="Password (10+ characters)" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} />
        </Box>
        <Text fontSize="12px" color="var(--muted)" mt="8px">{ROLE_HELP[f.role]}</Text>
        <Flex mt="10px" gap="10px" align="center"><button className="ctl sm primary" onClick={() => void create()}>Create account</button>{msg && <Text fontSize="12.5px" color="var(--muted)">{msg}</Text>}</Flex>
      </Box>
      <Flex direction="column" gap="8px">
        {items.map((a) => (
          <Flex key={a.username} className="glass" borderRadius="14px" p="12px 16px" justify="space-between" align="center" wrap="wrap" gap="8px" opacity={a.active ? 1 : 0.55}>
            <Box><Text fontSize="15px">{a.name} <span style={{ color: "var(--muted)", fontSize: 12.5 }}>@{a.username}</span></Text><Text fontSize="12px" color="var(--muted)">{a.role} · {a.last_login ? `last sign-in ${new Date(a.last_login).toLocaleString()}` : "never signed in"}</Text></Box>
            <Flex gap="6px"><button className="ctl sm" onClick={() => void reset(a)}>Reset password</button><button className="ctl sm" onClick={() => void toggle(a)}>{a.active ? "Deactivate" : "Activate"}</button></Flex>
          </Flex>
        ))}
      </Flex>
    </Box>
  );
}
