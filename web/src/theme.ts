import { createSystem, defaultConfig, defineConfig } from "@chakra-ui/react";
import type { Mode } from "./store";

/** One flat colour per mode. Normal is ink-black; colour only appears when something needs attention. */
export const MODE_COLORS: Record<Mode, { a: string }> = {
  normal: { a: "#0A0A0A" },
  handover: { a: "#F59E0B" },
  emergency: { a: "#EF4444" },
  connected: { a: "#16A34A" },
};

const config = defineConfig({
  globalCss: {
    "html, body, #root": { height: "100%", background: "#FFFFFF", color: "#0A0A0A" },
    body: { fontFamily: "'Inter Variable', system-ui, sans-serif", overflow: "hidden" },
    "*": { scrollbarWidth: "thin", scrollbarColor: "#D4D4D4 transparent" },
  },
  theme: {
    tokens: {
      fonts: {
        heading: { value: "'Inter Variable', system-ui, sans-serif" },
        body: { value: "'Inter Variable', system-ui, sans-serif" },
        mono: { value: "ui-monospace, 'SF Mono', Menlo, Consolas, monospace" },
      },
    },
  },
});

export const system = createSystem(defaultConfig, config);
