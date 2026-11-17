import { Box } from "@chakra-ui/react";
import { AnimatePresence, motion } from "motion/react";
import { lazy, Suspense } from "react";
import { useStore } from "../store";

const CoreOrb = lazy(() => import("./CoreOrb"));

function stateLabel(eff: string, mode: string): string {
  if (mode === "emergency") return "Getting help for you";
  if (mode === "connected") return "Connected to a team member";
  if (mode === "handover") return "Connecting you to a team member";
  return { listening: "Listening", thinking: "Thinking", speaking: "", idle: "", ended: "" }[eff] ?? "";
}

export default function OrbStage({ compact = false }: { compact?: boolean }) {
  const ui = useStore((s) => s.ui);
  const playing = useStore((s) => s.playing);
  const mode = useStore((s) => s.mode);
  const eff = playing && mode !== "connected" ? "speaking" : ui;
  const label = stateLabel(eff, mode);
  return (
    <Box textAlign="center" flex="none">
      <Box position="relative" w={compact ? "min(64vw, 30vh, 280px)" : "min(66vw, 36vh, 380px)"} aspectRatio="1" mx="auto">
        <Suspense fallback={null}><CoreOrb /></Suspense>
      </Box>
      <Box h="22px" mt="-2px">
        <AnimatePresence mode="wait">
          {label && (
            <motion.div key={label} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.25 }}
              style={{ color: "var(--muted)", fontSize: 14 }}>
              {label}
            </motion.div>
          )}
        </AnimatePresence>
      </Box>
    </Box>
  );
}
