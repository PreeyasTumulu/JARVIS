// The reactor: one fragment shader, drawn by the desktop overlay (OpenGL 3.3) and the page
// (WebGL 2). Each adds its own #version line. Output is premultiplied alpha, so light adds to
// whatever is behind it and the dim darkens it.

uniform vec2 u_res;
uniform float u_t;          // seconds, always running
uniform float u_burst;      // seconds since the wake word; large once the burst is over
uniform float u_dim;        // 0 to 1, how dark the background goes
uniform float u_edge;       // 0 to 1, the plasma on the screen's edges
uniform float u_core;       // 0 to 1, the reactor in the middle
uniform vec2 u_core_pos;    // from the centre, in screen heights
uniform float u_core_size;  // outer ring radius, in screen heights
uniform float u_level;      // 0 to 1, the voice right now
uniform float u_bars[32];   // the voice over the last moments, 0 to 1
uniform float u_sweep;      // 0 to 1, the comet that runs round the edge while Jarvis works
uniform float u_calm;       // 1 when Windows animations are off: no burst, slow flow
uniform vec3 u_color_a;
uniform vec3 u_color_b;
out vec4 fragColor;

const float TAU = 6.2831853;
const float PI = 3.1415927;

float hash(vec2 p) {
  p = fract(p * vec2(123.34, 456.21));
  p += dot(p, p + 45.32);
  return fract(p.x * p.y);
}

float noise(vec2 p) {
  vec2 i = floor(p), f = fract(p);
  f = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), f.x),
             mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), f.x), f.y);
}

float fbm(vec2 p) {
  float v = 0.0, a = 0.5;
  for (int i = 0; i < 4; i++) {
    v += a * noise(p);
    p = p * 2.03 + vec2(11.7, 3.1);
    a *= 0.5;
  }
  return v;
}

float ring(float r, float radius, float width) {
  return smoothstep(width, 0.0, abs(r - radius));
}

// How far inside the screen this point is. A soft minimum of the four edges: a plain minimum has
// a crease from each corner to the middle, and the plasma would show it as a picture frame.
float insetFromEdge(vec2 p, vec2 half_size) {
  const float k = 30.0;
  vec2 near = half_size - p, far = half_size + p;
  float sum = exp(-k * near.x) + exp(-k * near.y) + exp(-k * far.x) + exp(-k * far.y);
  return -log(sum) / k;
}

float hexLines(vec2 p) {
  vec2 s = vec2(1.0, 1.732);
  vec2 a = mod(p, s) - s * 0.5;
  vec2 b = mod(p - s * 0.5, s) - s * 0.5;
  vec2 g = dot(a, a) < dot(b, b) ? a : b;
  vec2 h = abs(g);
  return smoothstep(0.42, 0.5, max(dot(h, vec2(0.866, 0.5)), h.x));
}

vec3 plasmaEdge(vec2 p, float inset, float t) {
  float angle = atan(p.y, p.x);
  vec2 flow = p * 2.3;
  float warp = fbm(flow * 1.6 + vec2(t * 0.17, -t * 0.11));
  float n = fbm(flow + warp * 1.5 + vec2(-t * 0.13, t * 0.09));
  // Wide while the screen is dark; a thin line over your apps, so it never fogs them.
  float open = smoothstep(0.0, 0.45, u_dim);
  float reach = mix(0.012 + 0.03 * n * n, 0.028 + 0.13 * n * n + 0.07 * u_level, open);
  float glow = exp(-inset / reach) * (0.4 + 1.05 * n);
  float line = exp(-inset / 0.0045) * (0.7 + 0.5 * n);
  // Bright filaments, where the noise crosses its middle.
  float filament = 1.0 - abs(2.0 * fbm(flow * 2.7 + warp * 2.6 + vec2(t * 0.2, 0.0)) - 1.0);
  float wisps = pow(filament, 9.0) * exp(-inset / (reach * 2.2)) * (0.3 + 0.7 * open);
  vec3 tint = mix(u_color_a, u_color_b, 0.5 + 0.5 * sin(angle * 2.0 + t * 0.4 + n * 4.0));
  vec3 col = tint * glow * 1.15 + (tint * 0.5 + 0.5) * line + (tint + 0.3) * wisps * 1.2;
  if (u_sweep > 0.001) {
    float head = mod(angle - t * 1.6, TAU) / TAU;
    float tail = pow(1.0 - head, 6.0) * smoothstep(0.0, 0.015, head);
    col += (u_color_a + 0.35) * tail * exp(-inset / 0.022) * u_sweep * 1.6;
  }
  return col * u_edge;
}

vec3 wakeWave(vec2 p, float inset) {
  float fade = smoothstep(1.5, 0.15, u_burst) * (1.0 - u_calm);
  if (fade <= 0.0) return vec3(0.0);
  float travel = 1.0 - pow(1.0 - clamp(u_burst / 1.1, 0.0, 1.0), 3.0);
  float front = travel * (0.5 * min(u_res.x / u_res.y, 1.8));
  // Each colour runs a little apart, like a lens splitting the wave.
  vec3 wave = vec3(
    exp(-abs(inset - front - 0.012) * 42.0),
    exp(-abs(inset - front) * 42.0),
    exp(-abs(inset - front + 0.012) * 42.0));
  float lattice = hexLines(p * 21.0) * exp(-abs(inset - front + 0.03) * 8.0);
  float behind = smoothstep(0.0, 0.25, front - inset) * 0.06;
  // The fronts meet along the screen's middle line: gone by then, or they pile up into a bar.
  fade *= smoothstep(0.47, 0.3, front);
  return (wave * (u_color_a * 0.8 + 0.5) + u_color_a * (lattice * 0.4 + behind)) * fade;
}

vec3 reactor(vec2 p, float t) {
  vec2 q = (p - u_core_pos) / max(u_core_size, 0.001);
  float r = length(q);
  if (r > 3.2) return vec3(0.0);
  float angle = atan(q.y, q.x);
  float ignite = smoothstep(0.25, 0.85, u_burst + u_calm);
  float breathe = 1.0 + 0.05 * sin(t * 1.7) + 0.16 * u_level;
  r /= breathe;

  // The arc: a white point, a cyan body, and lightning between it and the first ring.
  float arc = 0.05 / (r + 0.045);
  float body = exp(-r * 3.4);
  vec2 bolt = vec2(angle * 2.4, r * 3.2 - t * 2.6);
  float crackle = abs(fbm(bolt) - 0.5) + abs(fbm(bolt * 1.9 + 7.0) - 0.5) * 0.4;
  float lightning = exp(-crackle * 46.0) * smoothstep(0.42, 0.26, r) * smoothstep(0.03, 0.1, r);
  vec3 col = vec3(1.0) * arc * arc * 0.5 + u_color_a * (arc * 0.7 + body * 0.9);
  col += (u_color_a + 0.55) * lightning * (1.1 + u_level * 2.0);

  // Ten coils, turning slowly, brighter with the voice.
  float coil_angle = fract((angle + t * 0.05) * 10.0 / TAU);
  float coil = smoothstep(0.1, 0.16, coil_angle) * smoothstep(0.9, 0.84, coil_angle);
  coil *= smoothstep(0.37, 0.4, r) * smoothstep(0.6, 0.57, r);
  float coil_face = 0.5 + 0.5 * sin((angle + t * 0.05) * 10.0 + r * 30.0);
  col += mix(u_color_b, u_color_a, coil_face) * coil * (0.38 + 1.1 * u_level);

  col += u_color_a * ring(r, 0.35, 0.013) * 1.5;
  col += u_color_b * ring(r, 0.635, 0.012) * 1.1;

  // Dashes that run against each other.
  float dash = step(0.42, fract((angle - t * 0.32) * 36.0 / TAU));
  col += u_color_a * ring(r, 0.68, 0.011) * dash * 0.85;

  // The voice: bars out of the ring, one mirrored half round each side.
  float side = abs(angle) / PI;
  float slot = side * 32.0;
  int index = int(clamp(floor(slot), 0.0, 31.0));
  float height = 0.012 + u_bars[index] * 0.24;
  float bar = smoothstep(0.26, 0.34, fract(slot)) * smoothstep(0.74, 0.66, fract(slot));
  bar *= smoothstep(0.72, 0.73, r) * smoothstep(0.73 + height + 0.005, 0.73 + height, r);
  float along = clamp((r - 0.72) / max(height, 0.01), 0.0, 1.0);
  col += mix(u_color_b, u_color_a + 0.2, along) * bar * (0.75 + u_bars[index] * 0.7);

  // The outer ring has three gaps, and turns the other way.
  float gaps = smoothstep(0.03, 0.05, abs(fract((angle + t * 0.13) * 3.0 / TAU) - 0.5));
  col += (u_color_a * 0.6 + 0.4) * ring(r, 1.06, 0.008) * gaps;
  float ticks = step(0.86, fract((angle - t * 0.05) * 90.0 / TAU));
  col += u_color_b * ticks * smoothstep(1.13, 1.135, r) * smoothstep(1.2, 1.195, r) * 0.65;

  // Thin streaks falling inward. The cells grow with the radius, so each one stays a fine line.
  float lane = (angle + PI) / TAU * 90.0;
  vec2 cell = vec2(lane, log(r + 0.12) * 5.0 + t * (0.8 + u_level * 1.4));
  float lane_seed = hash(vec2(floor(lane), 3.0));
  cell.y += lane_seed * 17.0;
  if (hash(floor(cell)) > 0.93) {
    vec2 f = fract(cell) - 0.5;
    float streak = smoothstep(0.1, 0.0, abs(f.x)) * smoothstep(0.5, 0.0, abs(f.y));
    float range = smoothstep(1.22, 1.45, r) * smoothstep(3.05, 2.1, r);
    // Only while active: at rest on the page they would fall across the conversation.
    col += (u_color_a + 0.3) * streak * range * (0.5 + lane_seed) * smoothstep(0.05, 0.5, u_edge);
  }

  // The halo fades out well before the shader's cut-off.
  col += u_color_a * exp(-max(r - 0.3, 0.0) * 2.1) * 0.08 * smoothstep(3.1, 2.0, r);
  return col * ignite * u_core;
}

void main() {
  vec2 p = (gl_FragCoord.xy - 0.5 * u_res) / u_res.y;
  float t = u_t * (1.0 - 0.8 * u_calm);
  vec2 half_size = vec2(0.5 * u_res.x / u_res.y, 0.5);
  float inset = max(insetFromEdge(p, half_size), 0.0);

  vec3 col = vec3(0.0);
  float dark = 0.0;
  if (u_dim > 0.001) {
    // The whole background changes: a slow field of the state's colour over the dimmed desktop.
    float cloud = fbm(p * 1.5 + vec2(t * 0.05, -t * 0.03));
    float away = length(p - u_core_pos);
    vec3 field = mix(u_color_b, u_color_a, cloud) * (0.05 + 0.3 * cloud * cloud);
    field += u_color_a * 0.11 * exp(-away * 2.4);
    col += field * u_dim * smoothstep(0.0, 0.5, u_burst + u_calm);
    dark = u_dim * smoothstep(0.0, 0.45, u_burst + u_calm);
  }
  if (u_edge > 0.001 && inset < 0.55) col += plasmaEdge(p, inset, t);
  if (u_burst < 1.5) col += wakeWave(p, inset);
  if (u_core > 0.001) {
    col += reactor(p, t);
    // A dark backing, or light added to a white app window is lost.
    float around = length(p - u_core_pos) / max(u_core_size, 0.001);
    float ignite = smoothstep(0.25, 0.85, u_burst + u_calm);
    dark = max(dark, smoothstep(1.32, 1.12, around) * u_core * ignite * 0.86);
  }

  // Dither, or the slow fades band on an 8-bit panel.
  col += (hash(gl_FragCoord.xy + fract(u_t)) - 0.5) / 255.0;
  col = clamp(col, 0.0, 1.0);
  float light = max(col.r, max(col.g, col.b));
  fragColor = vec4(col, clamp(dark + light * 0.8, 0.0, 1.0));
}
