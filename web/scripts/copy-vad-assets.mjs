// Copies the Silero VAD model, its worklet and the ONNX runtime WASM into public/vad
// so the browser loads everything from our own origin (no CDN, works offline).
import { cpSync, existsSync, mkdirSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

const out = "public/vad";
mkdirSync(out, { recursive: true });

function find(dir, name) {
  if (!existsSync(dir)) return null;
  for (const entry of readdirSync(dir)) {
    const p = join(dir, entry);
    if (statSync(p).isDirectory()) {
      const hit = find(p, name);
      if (hit) return hit;
    } else if (entry === name) return p;
  }
  return null;
}

const vad = "node_modules/@ricky0123/vad-web/dist";
const ort = "node_modules/onnxruntime-web/dist";
const wanted = [
  [vad, "silero_vad_v5.onnx"],
  [vad, "vad.worklet.bundle.min.js"],
  [ort, "ort-wasm-simd-threaded.mjs"],
  [ort, "ort-wasm-simd-threaded.wasm"],
];
for (const [dir, name] of wanted) {
  const src = find(dir, name);
  if (!src) {
    console.error(`copy-vad-assets: missing ${name} under ${dir}`);
    process.exit(1);
  }
  cpSync(src, join(out, name));
}
console.log("copy-vad-assets: ok");
