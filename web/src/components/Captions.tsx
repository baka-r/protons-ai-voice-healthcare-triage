import { Box, Flex, Input, Text } from "@chakra-ui/react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useState } from "react";
import { FiThumbsDown, FiThumbsUp } from "react-icons/fi";
import { call } from "../net/call";
import { useStore, type Triage } from "../store";

const TIER_COLOR: Record<Triage["tier"], string> = {
  self_care: "var(--ok)", see_doctor_soon: "var(--warn)", same_day: "var(--bad)", emergency: "var(--bad)",
};
const TIER_HELP: Record<Triage["tier"], string> = {
  self_care: "Usually settles with rest at home", see_doctor_soon: "A doctor visit in a day or two is wise",
  same_day: "Should be seen today", emergency: "Urgent help now",
};

/** The urgency Hania suggests for the current health topic. A suggestion from a testing agent, never a diagnosis. */
function TriageChip() {
  const t = useStore((s) => s.triage);
  if (!t) return null;
  return (
    <Flex justify="center" mt="10px">
      <Box border="1px solid var(--line)" borderRadius="18px" px="14px" py="6px" fontSize="13px" display="inline-flex" alignItems="center" gap="8px"
        title={t.reasons.join(". ")}>
        <span className="dot" style={{ background: TIER_COLOR[t.tier] }} />
        <span style={{ fontWeight: 600 }}>{t.label}</span>
        <span style={{ color: "var(--muted)" }}>{TIER_HELP[t.tier]}</span>
      </Box>
    </Flex>
  );
}

/** Thumbs under Hania's latest answer: how the tester rates it. A thumbs-down offers a one-line "what was wrong". */
function Rate({ id, text }: { id: number; text: string }) {
  const rated = useStore((s) => s.rated[id]);
  const [open, setOpen] = useState(false);
  const [comment, setComment] = useState("");
  useEffect(() => { setOpen(false); setComment(""); }, [id]);
  if (rated && !open) return <Text fontSize="12px" color="var(--muted)" mt="8px">Thanks, noted.</Text>;
  return (
    <Box mt="8px">
      {!rated && (
        <Flex justify="center" gap="6px" align="center" color="var(--muted)" fontSize="12px">
          <span>Was this helpful?</span>
          <button className="ctl round" aria-label="Good answer" style={{ width: 30, height: 30, fontSize: 14 }} onClick={() => call.sendFeedback(id, "up", text)}><FiThumbsUp /></button>
          <button className="ctl round" aria-label="Bad answer" style={{ width: 30, height: 30, fontSize: 14 }} onClick={() => setOpen(true)}><FiThumbsDown /></button>
        </Flex>
      )}
      {open && (
        <Flex gap="6px" maxW="460px" mx="auto" align="center">
          <Input value={comment} onChange={(e) => setComment(e.target.value)} placeholder="What was wrong? (optional, no personal details)" size="sm" autoFocus
            onKeyDown={(e) => { if (e.key === "Enter") { call.sendFeedback(id, "down", text, comment); setOpen(false); } }}
            borderRadius="16px" border="1px solid var(--line)" bg="#fff" fontSize="13px" />
          <button className="ctl sm primary" onClick={() => { call.sendFeedback(id, "down", text, comment); setOpen(false); }}>Send</button>
        </Flex>
      )}
    </Box>
  );
}

export default function Captions() {
  const captions = useStore((s) => s.captions);
  const ui = useStore((s) => s.ui);
  const assistant = [...captions].reverse().find((c) => c.role === "assistant");
  const caller = [...captions].reverse().find((c) => c.role === "caller");
  const callerNewer = caller && assistant ? caller.id > assistant.id : !!caller;
  return (
    <Box textAlign="center" maxW="680px" w="100%" mx="auto" px="24px" minH="0" maxH="38vh" overflowY="auto" aria-live="polite">
      <Box minH="24px" mb="6px">
        <AnimatePresence mode="wait">
          {callerNewer && caller && (
            <motion.div key={`c${caller.id}`} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.2 }}>
              <Text fontSize="15px" color="var(--muted)" lineClamp={2}>{caller.text}</Text>
            </motion.div>
          )}
        </AnimatePresence>
      </Box>
      <AnimatePresence mode="wait">
        {assistant && (
          <motion.div key={assistant.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.35 }}>
            <Text fontWeight="500" fontSize={{ base: "20px", md: "26px" }} lineHeight="1.35" letterSpacing="-0.015em">{assistant.text}</Text>
          </motion.div>
        )}
      </AnimatePresence>
      {assistant && ui === "listening" && !callerNewer && <Rate id={assistant.id} text={assistant.text} />}
      <TriageChip />
    </Box>
  );
}
