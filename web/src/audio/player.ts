import { levels } from "./levels";

/** Plays raw 24 kHz mono PCM16 chunks as they arrive. stop() cuts audio instantly (barge-in). */
export class Player {
  readonly ctx: AudioContext;
  private analyser: AnalyserNode;
  private gain: GainNode;
  private next = 0;
  private sources = new Set<AudioBufferSourceNode>();
  private buf: Uint8Array<ArrayBuffer>;
  onChange?: (playing: boolean) => void;
  onFirstChunk?: () => void;
  private firstPending = false;

  constructor() {
    this.ctx = new AudioContext({ latencyHint: "interactive" });
    this.gain = this.ctx.createGain();
    this.analyser = this.ctx.createAnalyser();
    this.analyser.fftSize = 512;
    this.buf = new Uint8Array(this.analyser.fftSize);
    this.gain.connect(this.analyser);
    this.analyser.connect(this.ctx.destination);
  }

  resume() {
    return this.ctx.state === "suspended" ? this.ctx.resume() : Promise.resolve();
  }

  armFirstChunk() {
    this.firstPending = true;
  }

  get playing() {
    return this.sources.size > 0;
  }

  enqueue(data: ArrayBuffer, sampleRate = 24000) {
    const n = Math.floor(data.byteLength / 2);
    if (n === 0) return;
    if (this.firstPending) {
      this.firstPending = false;
      this.onFirstChunk?.();
    }
    const i16 = new Int16Array(data, 0, n);
    const buffer = this.ctx.createBuffer(1, n, sampleRate);
    const ch = buffer.getChannelData(0);
    for (let i = 0; i < n; i++) ch[i] = i16[i] / 32768;
    const src = this.ctx.createBufferSource();
    src.buffer = buffer;
    src.connect(this.gain);
    const wasPlaying = this.playing;
    const t = Math.max(this.ctx.currentTime + 0.03, this.next);
    src.start(t);
    this.next = t + buffer.duration;
    this.sources.add(src);
    src.onended = () => {
      this.sources.delete(src);
      if (this.sources.size === 0) this.onChange?.(false);
    };
    if (!wasPlaying) this.onChange?.(true);
  }

  /** Immediately silence everything queued. */
  stop() {
    for (const s of this.sources) {
      s.onended = null;
      try { s.stop(); } catch { /* already stopped */ }
    }
    this.sources.clear();
    this.next = 0;
    this.onChange?.(false);
  }

  /** Called once per animation frame. */
  tick() {
    if (!this.playing) {
      levels.tts *= 0.85;
      return;
    }
    this.analyser.getByteTimeDomainData(this.buf);
    let sum = 0;
    for (let i = 0; i < this.buf.length; i++) {
      const v = (this.buf[i] - 128) / 128;
      sum += v * v;
    }
    const rms = Math.sqrt(sum / this.buf.length);
    levels.tts = levels.tts * 0.6 + Math.min(1, rms * 4.2) * 0.4;
  }

  close() {
    this.stop();
    void this.ctx.close();
  }
}
