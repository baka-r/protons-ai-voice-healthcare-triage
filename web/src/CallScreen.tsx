import { Flex } from "@chakra-ui/react";
import type { CSSProperties } from "react";
import { BottomBar, TopBar } from "./components/Bars";
import Captions from "./components/Captions";
import OrbStage from "./components/OrbStage";
import { EndedOverlay, HandoverBanner, StartBlock } from "./components/Overlays";
import { DetailsDrawer } from "./components/Panels";
import { call } from "./net/call";
import { useStore } from "./store";
import { MODE_COLORS } from "./theme";

export default function CallScreen() {
  const phase = useStore((s) => s.phase);
  const mode = useStore((s) => s.mode);
  const c = MODE_COLORS[mode];
  const style = { ["--accent" as string]: c.a } as CSSProperties;
  const started = phase === "live" || phase === "ended";
  const audioBlocked = useStore((s) => s.audioBlocked);

  return (
    <Flex direction="column" h="100dvh" position="relative" overflow="hidden" style={style} data-mode={mode}>
      <div className="ambient" aria-hidden />
      <TopBar />
      <Flex flex="1" minH={0} zIndex={2} direction="column" align="center" justify="center" gap={{ base: "10px", md: "14px" }} position="relative" pt="24px" pb="8px" overflowY="auto" overflowX="hidden">
        <HandoverBanner />
        <OrbStage compact={!started} />
        {started ? <Captions /> : <StartBlock />}
      </Flex>
      {phase === "live" && audioBlocked && (
        <button className="ctl pill primary" onClick={() => call.unlock()}
          style={{ position: "absolute", top: 74, left: "50%", transform: "translateX(-50%)", zIndex: 6, height: 40, fontSize: 14 }}>
          Tap to turn on sound and microphone
        </button>
      )}
      {started && <BottomBar />}
      <DetailsDrawer />
      {phase === "ended" && <EndedOverlay />}
    </Flex>
  );
}
