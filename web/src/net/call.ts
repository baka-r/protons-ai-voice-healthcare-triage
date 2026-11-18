import { MicVAD } from "@ricky0123/vad-web";
import { levels } from "../audio/levels";
import { Player } from "../audio/player";
import { sfx, setSfxEnabled } from "../audio/sfx";
import { useStore, type Mode, type StepStatus, type UiState } from "../store";

const QUIET = { positiveSpeechThreshold: 0.6, negativeSpeechThreshold: 0.4 };
const WHILE_SPEAKING = { positiveSpeechThreshold: 0.92, negativeSpeechThreshold: 0.75 }; // harder to trigger on echo
const REDEMPTION_MS = 380;

function toPcm16(f32: Float32Array): ArrayBuffer {
  const out = new Int16Array(f32.length);
  for (let i = 0; i < f32.length; i++) {
    const s = Math.max(-1, Math.min(1, f32[i]));
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return out.buffer;
}

export class CallClient {
  private ws?: WebSocket;
  private player?: Player;
  private vad?: MicVAD;
  private raf = 0;
  private speechEndAt = 0;
  private waiting = false;
  private closed = false;

  private vadCtx?: AudioContext;
  private micStream?: Promise<MediaStream>;
  private blockedPoll = 0;
  private diag = { frames: 0, maxLevel: 0, starts: 0, ends: 0, misfires: 0, sent: 0, holdSent: 0, err: "" };
  private diagTimer?: ReturnType<typeof setInterval>;
  private diagSent = 0;
  private hold?: { src: MediaStreamAudioSourceNode; proc: ScriptProcessorNode; chunks: Float32Array[]; on: boolean };

  /** What this phone's microphone path is doing, for the Details panel and (anonymously) for our server log. */
  private snapshot() {
    return {
      ...this.diag, vadCtx: this.vadCtx?.state ?? "none", playerCtx: this.player?.ctx.state ?? "none",
      sampleRate: this.vadCtx?.sampleRate ?? 0, vadRunning: !!this.vad,
    };
  }

  private async report(final = false) {
    const snap = this.snapshot();
    useStore.getState().set({ micDiag: snap });
    if (this.diagSent >= 12 && !final) return;
    this.diagSent++;
    let track: Record<string, unknown> = {};
    try {
      const st = await this.micStream;
      const t = st?.getAudioTracks()[0];
      if (t) track = { ready: t.readyState, muted: t.muted, enabled: t.enabled, settings: t.getSettings?.() };
    } catch { /* no stream */ }
    this.send({ type: "diag", d: { ...snap, track, ua: navigator.userAgent.slice(0, 140), touch: navigator.maxTouchPoints } });
  }

  /** iPhone/Safari only allows audio and the microphone to start INSIDE the tap itself. This must run before any `await` in begin(). */
  private unlockAudio() {
    try {
      const as = (navigator as unknown as { audioSession?: { type: string } }).audioSession;
      if (as) as.type = "play-and-record"; // speaker output while the mic is open; not muted by the silent switch
    } catch { /* not supported */ }
    try {
      this.vadCtx = new AudioContext();
      void this.vadCtx.resume();
    } catch { /* no Web Audio */ }
    if (navigator.mediaDevices?.getUserMedia) {
      this.micStream = navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
      this.micStream.catch(() => undefined); // the error is reported in startMic
    } else {
      this.micStream = Promise.reject(new Error("no-mic-api"));
      this.micStream.catch(() => undefined);
    }
    document.addEventListener("pointerdown", this.onGesture, { passive: true });
  }

  private onGesture = () => { this.unlock(); };

  /** Resume any audio context the browser put to sleep (called on every tap and by the "Tap to turn on sound" button). */
  unlock() {
    for (const c of [this.player?.ctx, this.vadCtx]) {
      if (c && c.state !== "running") void c.resume().catch(() => undefined);
    }
  }

  async begin() {
    this.unlockAudio();
    const st = useStore.getState();
    st.reset();
    this.closed = false;
    this.waiting = false;
    st.set({ phase: "connecting", status: st.status });
    setSfxEnabled(useStore.getState().sfx);
    this.player = new Player();
    await this.player.resume();
    this.player.onChange = (playing) => {
      useStore.getState().set({ playing });
      this.vad?.setOptions(playing ? WHILE_SPEAKING : QUIET);
    };
    this.player.onFirstChunk = () => {
      if (this.waiting) {
        this.waiting = false;
        const e2e = Math.round(performance.now() - this.speechEndAt + REDEMPTION_MS);
        useStore.getState().set({ timing: { ...useStore.getState().timing, e2e_ms: e2e } });
      }
    };
    this.loop();

    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws/call`);
    ws.binaryType = "arraybuffer";
    this.ws = ws;
    ws.onopen = () => {
      const g = useStore.getState();
      ws.send(JSON.stringify({ type: "start", lang: g.lang, consent: g.consent }));
      useStore.getState().set({ phase: "live" });
      void this.startMic();
      this.diagSent = 0;
      this.diagTimer = setInterval(() => { void this.report(); }, 5000);
    };
    ws.onmessage = (ev) => (typeof ev.data === "string" ? this.onJson(JSON.parse(ev.data)) : this.player?.enqueue(ev.data as ArrayBuffer));
    ws.onclose = () => {
      if (!this.closed) {
        useStore.getState().set({ error: "Connection lost", phase: "ended", ui: "ended" });
        this.teardown();
      }
    };
    ws.onerror = () => useStore.getState().set({ error: "Could not reach the assistant" });
  }

  private loop = () => {
    if (++this.blockedPoll % 30 === 0) {
      const blocked = [this.player?.ctx, this.vadCtx].some((c) => !!c && c.state !== "running");
      if (blocked !== useStore.getState().audioBlocked) useStore.getState().set({ audioBlocked: blocked });
      if (this.blockedPoll % 60 === 0 && useStore.getState().drawer) useStore.getState().set({ micDiag: this.snapshot() });
    }
    this.player?.tick();
    levels.mic *= 0.9;
    levels.level = Math.max(levels.tts, levels.mic);
    this.raf = requestAnimationFrame(this.loop);
  };

  private async startMic() {
    try {
      this.vad = await MicVAD.new({
        model: "v5",
        baseAssetPath: "/vad/",
        onnxWASMBasePath: "/vad/",
        ...QUIET,
        redemptionMs: REDEMPTION_MS,
        preSpeechPadMs: 250,
        minSpeechMs: 250,
        audioContext: this.vadCtx,
        getStream: () => this.micStream ?? navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true } }),
        onVADMisfire: () => { this.diag.misfires++; },
        onFrameProcessed: (_p, frame) => {
          this.diag.frames++;
          let sum = 0;
          for (let i = 0; i < frame.length; i++) sum += frame[i] * frame[i];
          const rms = Math.sqrt(sum / frame.length);
          levels.mic = Math.max(levels.mic, Math.min(1, rms * 9));
          if (rms > this.diag.maxLevel) this.diag.maxLevel = Math.round(rms * 1000) / 1000;
        },
        onSpeechStart: () => this.onSpeechStart(),
        onSpeechEnd: (audio: Float32Array) => this.onSpeechEnd(audio),
      });
      await this.vad.start();
      useStore.getState().set({ micError: null });
      void this.report();
    } catch (e) {
      console.warn("microphone unavailable", e);
      this.diag.err = `${(e as { name?: string })?.name ?? "error"}: ${String((e as Error)?.message ?? e).slice(0, 80)}`;
      void this.report();
      const name = (e as { name?: string })?.name ?? "";
      const msg = name === "NotAllowedError" || name === "SecurityError"
        ? "Microphone is blocked. Allow it for this site in your browser settings, then start again. You can type meanwhile."
        : name === "NotFoundError" ? "No microphone found. You can type instead."
        : "Microphone unavailable. You can type instead.";
      useStore.getState().set({ micError: msg });
    }
  }

  private onSpeechStart() {
    this.diag.starts++;
    const st = useStore.getState();
    if (st.mode === "emergency" || st.mode === "connected") return;
    if (this.player?.playing) {
      this.player.stop();
      this.send({ type: "barge_in" });
    }
    st.set({ ui: st.mode === "handover" ? "handover" : "listening" });
    sfx.listen();
  }

  private onSpeechEnd(audio: Float32Array) {
    this.diag.ends++;
    if (useStore.getState().muted) return;
    this.diag.sent++;
    this.speechEndAt = performance.now();
    this.waiting = true;
    this.player?.armFirstChunk();
    this.ws?.send(toPcm16(audio));
  }

  send(obj: object) {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(obj));
  }

  /** Fallback that does not depend on automatic speech detection: press and hold, speak, release. */
  async holdStart() {
    if (useStore.getState().muted || !this.vadCtx || !this.micStream) return;
    this.unlock();
    try {
      if (!this.hold) {
        const stream = await this.micStream;
        const src = this.vadCtx.createMediaStreamSource(stream);
        const proc = this.vadCtx.createScriptProcessor(4096, 1, 1);
        const h = { src, proc, chunks: [] as Float32Array[], on: false };
        proc.onaudioprocess = (e) => { if (h.on) h.chunks.push(new Float32Array(e.inputBuffer.getChannelData(0))); };
        src.connect(proc);
        proc.connect(this.vadCtx.destination);
        this.hold = h;
      }
    } catch (e) {
      useStore.getState().set({ micError: "Microphone is blocked. Allow it for this site in your browser settings." });
      this.diag.err = `hold: ${(e as Error)?.name ?? "error"}`;
      return;
    }
    this.hold.chunks = [];
    this.hold.on = true;
    if (this.player?.playing) { this.player.stop(); this.send({ type: "barge_in" }); }
    useStore.getState().set({ ui: "listening", holding: true });
    sfx.listen();
  }

  holdEnd() {
    const h = this.hold;
    useStore.getState().set({ holding: false });
    if (!h || !h.on || !this.vadCtx) return;
    h.on = false;
    const total = h.chunks.reduce((n, c) => n + c.length, 0);
    const rate = this.vadCtx.sampleRate;
    if (total < rate * 0.35) return; // a tap, not speech
    const all = new Float32Array(total);
    let o = 0;
    for (const c of h.chunks) { all.set(c, o); o += c.length; }
    h.chunks = [];
    const ratio = rate / 16000; // linear resample to the 16 kHz the server expects
    const out = new Float32Array(Math.floor(all.length / ratio));
    for (let i = 0; i < out.length; i++) {
      const x = i * ratio, i0 = Math.floor(x), f = x - i0;
      out[i] = all[i0] * (1 - f) + (all[Math.min(i0 + 1, all.length - 1)] * f);
    }
    this.diag.holdSent++;
    this.onSpeechEnd(out);
  }

  sendText(text: string) {
    const t = text.trim();
    if (!t) return;
    this.speechEndAt = performance.now();
    this.waiting = true;
    this.player?.armFirstChunk();
    this.player?.stop();
    this.send({ type: "text", text: t });
  }

  setLanguage(lang: "en" | "hi" | "ur") {
    useStore.getState().set({ lang });
    try { localStorage.setItem("hania_lang", lang); } catch { /* storage unavailable */ }
    this.send({ type: "set_language", lang });
  }

  sendFeedback(captionId: number, rating: "up" | "down", text: string, comment = "") {
    useStore.getState().set({ rated: { ...useStore.getState().rated, [captionId]: rating } });
    this.send({ type: "feedback", rating, text, comment });
  }

  requestHuman() {
    this.player?.stop();
    this.send({ type: "request_human" });
  }

  async setMuted(m: boolean) {
    useStore.getState().set({ muted: m });
    if (!this.vad) return;
    if (m) await this.vad.pause();
    else await this.vad.start();
  }

  end() {
    this.send({ type: "end" });
    sfx.end();
    this.closed = true;
    this.teardown();
    useStore.getState().set({ phase: "ended", ui: "ended" });
  }

  private teardown() {
    cancelAnimationFrame(this.raf);
    document.removeEventListener("pointerdown", this.onGesture);
    if (this.diagTimer) clearInterval(this.diagTimer);
    try { this.hold?.proc.disconnect(); this.hold?.src.disconnect(); } catch { /* already gone */ }
    this.hold = undefined;
    void this.micStream?.then((s) => s.getTracks().forEach((t) => t.stop())).catch(() => undefined);
    void this.vad?.destroy();
    void this.vadCtx?.close().catch(() => undefined);
    this.vadCtx = undefined;
    this.micStream = undefined;
    this.player?.close();
    this.ws?.close();
  }

  private onJson(m: Record<string, any>) {
    const st = useStore.getState();
    switch (m.type) {
      case "session":
        st.set({ session: { id: m.id, hospital: m.hospital, assistant: m.assistant, emergency: m.emergency } });
        sfx.boot();
        break;
      case "state": {
        const prev = st.ui;
        st.set({ ui: m.state as UiState, mode: m.mode as Mode });
        if (m.state === "thinking" && prev !== "thinking") {
          st.resetTurn();
          sfx.think();
        }
        break;
      }
      case "caption":
        st.addCaption({ role: m.role, text: m.text });
        if (m.role === "assistant") sfx.line();
        break;
      case "trace":
        st.addTrace({ step: m.step, status: m.status as StepStatus, detail: m.detail ?? "", t: m.t });
        break;
      case "safety":
        st.set({ safety: { ...st.safety, ...m.items } });
        break;
      case "sources":
        st.set({ sources: m.items });
        break;
      case "intent":
        st.set({ intent: m.intent });
        break;
      case "timing":
        st.set({ timing: { ...st.timing, ...m } });
        break;
      case "triage":
        st.set({ triage: { tier: m.tier, label: m.label, topic: m.topic, age_group: m.age_group, reasons: m.reasons ?? [] } });
        break;
      case "language":
        st.set({ lang: m.lang });
        try { localStorage.setItem("hania_lang", m.lang); } catch { /* storage unavailable */ }
        break;
      case "handover":
        if (m.status === "cancelled") { st.set({ handover: null }); break; }
        st.set({ handover: { status: m.status, id: m.id, staff: m.staff, urgency: m.urgency, reason: m.reason } });
        if (m.status === "waiting") sfx.alert();
        if (m.status === "connected") sfx.connect();
        break;
      case "audio_end":
        if (m.interrupted) this.player?.stop();
        break;
      case "error":
        st.set({ error: m.message });
        setTimeout(() => useStore.getState().set({ error: null }), 6000);
        break;
      case "ended":
        st.set({ phase: "ended" });
        break;
    }
  }
}

export const call = new CallClient();
