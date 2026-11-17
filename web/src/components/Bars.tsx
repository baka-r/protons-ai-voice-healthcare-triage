import { Box, Flex, Input, Text } from "@chakra-ui/react";
import { useEffect, useState } from "react";
import { FiMic, FiMicOff, FiPhoneOff, FiSend, FiSliders, FiType } from "react-icons/fi";
import { call } from "../net/call";
import { useStore } from "../store";

export function TopBar() {
  const session = useStore((s) => s.session);
  const drawer = useStore((s) => s.drawer);
  const phase = useStore((s) => s.phase);
  const [name, setName] = useState("Hania");
  useEffect(() => { fetch("/api/config").then((r) => r.json()).then((c) => setName(c.assistant)).catch(() => undefined); }, []);
  return (
    <Flex zIndex={3} px={{ base: "20px", md: "36px" }} pt={{ base: "18px", md: "26px" }} align="center" justify="space-between">
      <Text fontWeight="600" fontSize="17px" letterSpacing="-0.01em">{session?.assistant ?? name}</Text>
      {phase === "live" && (
        <button className="ctl sm" onClick={() => useStore.getState().set({ drawer: !drawer })} aria-label="Show details" aria-pressed={drawer}>
          <FiSliders /> Details
        </button>
      )}
    </Flex>
  );
}

export function BottomBar() {
  const muted = useStore((s) => s.muted);
  const micError = useStore((s) => s.micError);
  const mode = useStore((s) => s.mode);
  const handover = useStore((s) => s.handover);
  const emergency = useStore((s) => s.session?.emergency ?? "1122");
  const [typing, setTyping] = useState(false);
  const [text, setText] = useState("");
  const submit = () => { if (text.trim()) { call.sendText(text); setText(""); } };
  useEffect(() => { if (micError) setTyping(true); }, [micError]);
  return (
    <Box zIndex={3} pb={{ base: "16px", md: "22px" }} px="16px">
      {micError && <Text textAlign="center" fontSize="12.5px" color="var(--warn)" mb="10px">{micError}</Text>}
      {typing && (
        <Flex mb="14px" gap="8px" maxW="520px" mx="auto" borderRadius="26px" border="1px solid var(--line)" p="5px 5px 5px 20px" align="center">
          <Input value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.key === "Enter" && submit()} placeholder="Type a message…" autoFocus
            variant="subtle" border="none" bg="transparent" fontSize="15px" px="0" _focus={{ outline: "none", boxShadow: "none" }} _placeholder={{ color: "var(--muted)" }} />
          <button className="ctl round primary" onClick={submit} aria-label="Send" style={{ width: 40, height: 40, fontSize: 16 }}><FiSend /></button>
        </Flex>
      )}
      <Flex justify="center" align="center" gap="18px">
        <button className="ctl round" onClick={() => setTyping((v) => !v)} aria-label="Type instead" title="Type instead"><FiType /></button>
        <button className={`ctl round big ${muted ? "muted-on" : "primary"}`} onClick={() => call.setMuted(!muted)}
          aria-label={muted ? "Unmute microphone" : "Mute microphone"} title={muted ? "Unmute" : "Mute"}>
          {muted ? <FiMicOff /> : <FiMic />}
        </button>
        <button className="ctl round danger" onClick={() => call.end()} aria-label="End call" title="End call"><FiPhoneOff /></button>
      </Flex>
      <Flex justify="center" align="center" wrap="wrap" gap="6px 14px" mt="16px" fontSize="12.5px" color="var(--muted)">
        <button className="link" disabled={!!handover} onClick={() => call.requestHuman()}>Talk to a person</button>
        <span style={{ color: mode === "emergency" ? "var(--bad)" : undefined, fontWeight: mode === "emergency" ? 600 : 400 }}>
          AI assistant, not a doctor · In an emergency call {emergency}
        </span>
      </Flex>
    </Box>
  );
}
