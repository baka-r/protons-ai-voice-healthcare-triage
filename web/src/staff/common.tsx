import { Box, Text } from "@chakra-ui/react";
import type { ReactNode } from "react";

export type Api = <T = any>(path: string, method?: string, body?: unknown) => Promise<T>;

export const TIER_LABEL: Record<string, string> = {
  self_care: "Home care", see_doctor_soon: "See a doctor soon", same_day: "Same-day attention", emergency: "Emergency",
};
export const TIER_COLOR: Record<string, string> = {
  self_care: "var(--ok)", see_doctor_soon: "var(--warn)", same_day: "var(--bad)", emergency: "var(--bad)",
};

export function Card({ title, children, wide }: { title: string; children: ReactNode; wide?: boolean }) {
  return (
    <Box className="glass" borderRadius="18px" p="16px 18px" gridColumn={wide ? { base: "auto", md: "span 2" } : undefined}>
      <div className="label" style={{ marginBottom: 10 }}>{title}</div>
      {children}
    </Box>
  );
}

export function Big({ value, unit, sub }: { value: ReactNode; unit?: string; sub?: string }) {
  return (
    <Box>
      <Text fontSize="30px" fontWeight="600" letterSpacing="-0.02em" lineHeight="1.1">{value}<span style={{ fontSize: 13, color: "var(--muted)", marginLeft: 4, fontWeight: 400 }}>{unit}</span></Text>
      {sub && <Text fontSize="12px" color="var(--muted)" mt="2px">{sub}</Text>}
    </Box>
  );
}

export function Rows({ data, empty = "No data yet.", map }: { data: Record<string, number> | undefined; empty?: string; map?: (k: string) => string }) {
  const entries = Object.entries(data ?? {}).sort((a, b) => b[1] - a[1]);
  if (!entries.length) return <Text fontSize="13.5px" color="var(--muted)">{empty}</Text>;
  const max = Math.max(...entries.map(([, n]) => n));
  return (
    <Box display="flex" flexDirection="column" gap="7px">
      {entries.map(([k, n]) => (
        <Box key={k} fontSize="13.5px">
          <Box display="flex" justifyContent="space-between"><span style={{ textTransform: "capitalize" }}>{(map ? map(k) : k).replace(/_/g, " ")}</span><b>{n}</b></Box>
          <Box h="4px" bg="var(--panel)" borderRadius="2px" mt="3px"><Box h="4px" bg="var(--fg)" borderRadius="2px" w={`${Math.max(4, (n / max) * 100)}%`} /></Box>
        </Box>
      ))}
    </Box>
  );
}

export function TierBadge({ tier }: { tier?: string | null }) {
  if (!tier) return null;
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12.5 }}>
      <span className="dot" style={{ background: TIER_COLOR[tier] ?? "#d4d4d4" }} />{TIER_LABEL[tier] ?? tier}
    </span>
  );
}
