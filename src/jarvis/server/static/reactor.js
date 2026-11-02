// The reactor on the page: the same shader as the desktop overlay, drawn with WebGL 2 over the
// whole window. It takes no clicks, and it dims only while you speak, so a confirmation card is
// never under it. Without WebGL 2 the page works the same with a plain ring in its place.
"use strict";

window.JarvisReactor = (() => {
  const canvas = document.getElementById("reactor");
  const dock = document.getElementById("dock");
  const BARS = 32;
  const BAR_STEP = 0.05;
  const IDLE_FRAME = 1 / 24; // resting costs little; an active state runs at the display's rate
  const PIXELS = Math.min(window.devicePixelRatio || 1, 1.5);

  // The same colours as the overlay's scene.py.
  const PALETTE = {
    idle: [[0.2, 0.85, 1.0], [0.08, 0.32, 1.0]],
    listening: [[0.2, 0.85, 1.0], [0.08, 0.32, 1.0]],
    transcribing: [[0.45, 0.95, 1.0], [0.1, 0.45, 1.0]],
    thinking: [[0.66, 0.42, 1.0], [0.18, 0.46, 1.0]],
    speaking: [[1.0, 0.76, 0.28], [0.18, 0.72, 1.0]],
    awaiting_answer: [[1.0, 0.56, 0.16], [1.0, 0.26, 0.12]],
    muted: [[0.5, 0.55, 0.6], [0.3, 0.33, 0.38]],
    off: [[0.5, 0.55, 0.6], [0.3, 0.33, 0.38]],
  };
  const TARGETS = {
    idle: { dim: 0, edge: 0, core: 0.85, sweep: 0 },
    listening: { dim: 0.6, edge: 1, core: 1, sweep: 0 },
    transcribing: { dim: 0.6, edge: 1, core: 1, sweep: 0 },
    thinking: { dim: 0, edge: 0.55, core: 1, sweep: 1 },
    speaking: { dim: 0, edge: 0.55, core: 1, sweep: 0 },
    awaiting_answer: { dim: 0, edge: 0.8, core: 1, sweep: 0 },
  };

  const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 1 : 0;
  const scene = {
    state: "idle", time: 0, burst: 10, dim: 0, edge: 0, core: 0, sweep: 0, level: 0, heard: 0,
    colorA: [...PALETTE.idle[0]], colorB: [...PALETTE.idle[1]], bars: new Float32Array(BARS),
    barClock: 0,
  };

  const ease = (value, target, dt, rate) => target + (value - target) * Math.exp(-rate * dt);

  function voice() {
    const t = scene.time;
    if (scene.state === "listening") return scene.heard;
    if (scene.state === "speaking") {
      return 0.32 + 0.22 * Math.sin(t * 9.1) * Math.sin(t * 3.7) + 0.14 * Math.sin(t * 17.3);
    }
    if (scene.state === "thinking") return 0.1 + 0.06 * Math.sin(t * 3);
    return 0;
  }

  function update(dt) {
    const goal = TARGETS[scene.state] || TARGETS.idle;
    scene.time += dt;
    scene.burst = Math.min(scene.burst + dt, 10);
    scene.dim = ease(scene.dim, goal.dim, dt, 5);
    scene.edge = ease(scene.edge, goal.edge, dt, 5);
    scene.core = ease(scene.core, goal.core, dt, 6);
    scene.sweep = ease(scene.sweep, goal.sweep, dt, 4);
    scene.level = ease(scene.level, voice(), dt, 16);
    const colors = PALETTE[scene.state] || PALETTE.idle;
    for (let i = 0; i < 3; i++) {
      scene.colorA[i] = ease(scene.colorA[i], colors[0][i], dt, 4.5);
      scene.colorB[i] = ease(scene.colorB[i], colors[1][i], dt, 4.5);
    }
    scene.barClock += dt;
    while (scene.barClock >= BAR_STEP) {
      scene.barClock -= BAR_STEP;
      scene.bars.copyWithin(1, 0, BARS - 1);
      scene.bars[0] = Math.min(1, scene.level * 1.15);
    }
  }

  const api = {
    wake() { scene.burst = 0; },
    setState(state) { scene.state = state in PALETTE ? state : "idle"; },
    setLevel(level) { scene.heard = Math.max(0, Math.min(1, level)); },
  };

  const gl = canvas.getContext("webgl2", { alpha: true, premultipliedAlpha: true, antialias: false });
  if (!gl) {
    document.body.classList.add("no-webgl");
    return api;
  }

  function compile(kind, source) {
    const shader = gl.createShader(kind);
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      throw new Error(gl.getShaderInfoLog(shader) || "shader failed");
    }
    return shader;
  }

  const VERTEX = `#version 300 es
void main() {
  vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
  gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}`;

  async function start() {
    const source = await (await fetch("/static/reactor.glsl")).text();
    const program = gl.createProgram();
    gl.attachShader(program, compile(gl.VERTEX_SHADER, VERTEX));
    gl.attachShader(program, compile(gl.FRAGMENT_SHADER, "#version 300 es\nprecision highp float;\n" + source));
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(program));
    gl.useProgram(program);
    gl.bindVertexArray(gl.createVertexArray());
    const at = (name) => gl.getUniformLocation(program, name);
    const u = {
      res: at("u_res"), t: at("u_t"), burst: at("u_burst"), dim: at("u_dim"), edge: at("u_edge"),
      core: at("u_core"), pos: at("u_core_pos"), size: at("u_core_size"), level: at("u_level"),
      bars: at("u_bars"), sweep: at("u_sweep"), calm: at("u_calm"), a: at("u_color_a"), b: at("u_color_b"),
    };
    document.body.classList.add("reactor-on");

    function resize() {
      const width = Math.round(window.innerWidth * PIXELS);
      const height = Math.round(window.innerHeight * PIXELS);
      if (canvas.width !== width || canvas.height !== height) {
        canvas.width = width;
        canvas.height = height;
        gl.viewport(0, 0, width, height);
      }
    }

    let previous = performance.now();
    let waited = 0;
    function frame(now) {
      requestAnimationFrame(frame);
      const dt = Math.min((now - previous) / 1000, 0.1);
      previous = now;
      const resting = scene.state === "idle" && scene.edge < 0.01 && scene.burst > 2;
      waited += dt;
      if (resting && waited < IDLE_FRAME) {
        return;
      }
      update(waited);
      waited = 0;
      resize();
      const box = dock.getBoundingClientRect();
      const tall = window.innerHeight;
      gl.uniform2f(u.res, canvas.width, canvas.height);
      gl.uniform1f(u.t, scene.time);
      gl.uniform1f(u.burst, scene.burst);
      gl.uniform1f(u.dim, scene.dim);
      gl.uniform1f(u.edge, scene.edge);
      gl.uniform1f(u.core, scene.core);
      gl.uniform2f(
        u.pos,
        (box.left + box.width / 2 - window.innerWidth / 2) / tall,
        (tall / 2 - (box.top + box.height / 2)) / tall,
      );
      gl.uniform1f(u.size, (box.width / 2) / 1.2 / tall);
      gl.uniform1f(u.level, scene.level);
      gl.uniform1fv(u.bars, scene.bars);
      gl.uniform1f(u.sweep, scene.sweep);
      gl.uniform1f(u.calm, calm);
      gl.uniform3fv(u.a, scene.colorA);
      gl.uniform3fv(u.b, scene.colorB);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    }
    requestAnimationFrame(frame);
  }

  start().catch((error) => {
    console.warn("The reactor could not start:", error);
    document.body.classList.add("no-webgl");
  });
  return api;
})();
