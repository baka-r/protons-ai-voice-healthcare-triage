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

  async begin() {
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
        getStream: () =>
          navigator.mediaDevices.getUserMedia({
            audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
          }),
        onFrameProcessed: (_p, frame) => {
          let sum = 0;
          for (let i = 0; i < frame.length; i++) sum += frame[i] * frame[i];
          const rms = Math.sqrt(sum / frame.length);
          levels.mic = Math.max(levels.mic, Math.min(1, rms * 9));
        },
        onSpeechStart: () => this.onSpeechStart(),
        onSpeechEnd: (audio: Float32Array) => this.onSpeechEnd(audio),
      });
      await this.vad.start();
      useStore.getState().set({ micError: null });
    } catch (e) {
      console.warn("microphone unavailable", e);
      useStore.getState().set({ micError: "Microphone unavailable. You can type instead." });
    }
  }

  private onSpeechStart() {
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
    if (useStore.getState().muted) return;
    this.speechEndAt = performance.now();
    this.waiting = true;
    this.player?.armFirstChunk();
    this.ws?.send(toPcm16(audio));
  }

  send(obj: object) {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(obj));
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
    void this.vad?.destroy();
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
