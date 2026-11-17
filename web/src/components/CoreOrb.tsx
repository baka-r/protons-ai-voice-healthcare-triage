import { Canvas, useFrame } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import * as THREE from "three";
import { levels } from "../audio/levels";
import { useStore } from "../store";
import { MODE_COLORS } from "../theme";

const VERT = /* glsl */ `
varying vec2 vUv;
void main(){ vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }`;

// A perfectly round, solid circle that breathes and swells with the voice, with two soft ripples that expand outward.
// While thinking, a short arc travels around it. One flat colour. No gradients, noise or glow.
const FRAG = /* glsl */ `
uniform float uTime; uniform float uLevel; uniform float uThink; uniform vec3 uA;
varying vec2 vUv;
void main(){
  vec2 p = (vUv - 0.5) * 2.0;
  float r = length(p);
  float ang = atan(p.y, p.x);

  float R = 0.34 + 0.012 * sin(uTime * 1.25) + uLevel * 0.17;
  float body = smoothstep(0.005, -0.005, r - R);

  float t1 = fract(uTime * 0.30);
  float t2 = fract(uTime * 0.30 + 0.5);
  float strength = 0.10 + uLevel * 0.55;
  float ring1 = smoothstep(0.0035, 0.0, abs(r - (R + 0.05 + t1 * 0.30))) * (1.0 - t1) * strength;
  float ring2 = smoothstep(0.0035, 0.0, abs(r - (R + 0.05 + t2 * 0.30))) * (1.0 - t2) * strength;

  float arc = smoothstep(0.55, 1.0, 0.5 + 0.5 * cos(ang - uTime * 2.6)) * smoothstep(0.009, 0.0, abs(r - (R + 0.06))) * uThink;

  float alpha = max(body, max(max(ring1, ring2), arc));
  gl_FragColor = vec4(uA * alpha, alpha);
}`;

function Orb() {
  const mat = useRef<THREE.ShaderMaterial>(null);
  const a = useRef(new THREE.Color(MODE_COLORS.normal.a));
  const level = useRef(0);
  const think = useRef(0);
  const uniforms = useMemo(
    () => ({ uTime: { value: 0 }, uLevel: { value: 0 }, uThink: { value: 0 }, uA: { value: new THREE.Color(MODE_COLORS.normal.a) } }),
    [],
  );
  const tmp = useMemo(() => new THREE.Color(), []);

  useFrame((state, dt) => {
    const st = useStore.getState();
    const eff = st.playing ? "speaking" : st.ui;
    a.current.lerp(tmp.set(MODE_COLORS[st.mode].a), Math.min(1, dt * 3));
    const lvl = eff === "speaking" ? levels.tts : eff === "listening" ? levels.mic * 0.85 : 0;
    level.current += (lvl - level.current) * Math.min(1, dt * 9);
    think.current += ((eff === "thinking" ? 1 : eff === "handover" ? 0.4 : 0) - think.current) * Math.min(1, dt * 3);
    const u = mat.current!.uniforms;
    u.uTime.value = state.clock.elapsedTime;
    u.uLevel.value = level.current;
    u.uThink.value = think.current;
    u.uA.value.copy(a.current);
  });

  return (
    <mesh frustumCulled={false}>
      <planeGeometry args={[2, 2]} />
      <shaderMaterial ref={mat} vertexShader={VERT} fragmentShader={FRAG} uniforms={uniforms} transparent premultipliedAlpha depthTest={false} depthWrite={false} />
    </mesh>
  );
}

export default function CoreOrb() {
  return (
    <Canvas dpr={[1, 2]} gl={{ alpha: true, antialias: true, premultipliedAlpha: true }} style={{ position: "absolute", inset: 0 }}>
      <Orb />
    </Canvas>
  );
}
