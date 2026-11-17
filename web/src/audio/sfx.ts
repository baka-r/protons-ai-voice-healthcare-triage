// Tiny synthesised UI sounds (no audio files). Subtle by design; can be muted.
let ctx: AudioContext | null = null;
let enabled = true;

export function setSfxEnabled(v: boolean) {
  enabled = v;
}

function ac() {
  if (!ctx) ctx = new AudioContext();
  if (ctx.state === "suspended") void ctx.resume();
  return ctx;
}

function tone(freq: number, dur: number, type: OscillatorType = "sine", vol = 0.035, delay = 0, slideTo?: number) {
  if (!enabled) return;
  try {
    const c = ac();
    const t0 = c.currentTime + delay;
    const o = c.createOscillator();
    const g = c.createGain();
    o.type = type;
    o.frequency.setValueAtTime(freq, t0);
    if (slideTo) o.frequency.exponentialRampToValueAtTime(slideTo, t0 + dur);
    g.gain.setValueAtTime(0.0001, t0);
    g.gain.exponentialRampToValueAtTime(vol, t0 + 0.012);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
    o.connect(g).connect(c.destination);
    o.start(t0);
    o.stop(t0 + dur + 0.02);
  } catch { /* audio not available */ }
}

// Quiet, soft sine tones only.
export const sfx = {
  boot: () => { tone(392, 0.35, "sine", 0.02, 0, 523); },
  line: () => undefined,
  listen: () => tone(587, 0.12, "sine", 0.015, 0, 740),
  think: () => undefined,
  alert: () => { tone(523, 0.25, "sine", 0.025); tone(440, 0.3, "sine", 0.025, 0.22); },
  connect: () => { tone(523, 0.14, "sine", 0.025); tone(659, 0.14, "sine", 0.025, 0.12); tone(784, 0.26, "sine", 0.025, 0.24); },
  end: () => tone(392, 0.4, "sine", 0.02, 0, 260),
};
