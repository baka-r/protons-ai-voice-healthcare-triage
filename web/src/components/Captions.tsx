import { Box, Text } from "@chakra-ui/react";
import { AnimatePresence, motion } from "motion/react";
import { useStore } from "../store";

export default function Captions() {
  const captions = useStore((s) => s.captions);
  const assistant = [...captions].reverse().find((c) => c.role === "assistant");
  const caller = [...captions].reverse().find((c) => c.role === "caller");
  const callerNewer = caller && assistant ? caller.id > assistant.id : !!caller;
  return (
    <Box textAlign="center" maxW="680px" w="100%" mx="auto" px="24px" minH="0" maxH="30vh" overflowY="auto" aria-live="polite">
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
    </Box>
  );
}
