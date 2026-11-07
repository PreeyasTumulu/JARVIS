// The demo kit: the seven states, a scripted run, the controls, and the microphone level.
// Every demo page carries a copy between its kit markers; edit this file, then run
// `uv run python scripts/build_ui_demos.py` (a test checks the copies match).
//
// A page reads Kit.scene in Kit.onFrame(fn) and styles itself from body[data-state].
// Elements marked data-kit="heard" | "say" | "ask" | "tool" | "label" get their text here,
// and buttons marked data-kit-answer="yes" | "no" answer the confirmation.
// Nothing here makes a network request. The microphone is opened only after its button is
// pressed, and its sound never leaves the page: only a loudness number is read.
const Kit = (() => {
  const STATES = ["idle", "listening", "thinking", "speaking", "confirm", "tool", "error"];
  const NAMES = {
    idle: "Idle",
    listening: "Listening",
    thinking: "Thinking",
    speaking: "Speaking",
    confirm: "Waiting for your yes",
    tool: "Running a tool",
    error: "Error",
  };
  // What each state shows when picked by hand, and in screenshots.
  const EXAMPLE = {
    idle: { say: "Say “Hey Jarvis”" },
    listening: { heard: "send the clipboard to my phone" },
    thinking: { heard: "send the clipboard to my phone" },
    confirm: { ask: "Send what you copied to your phone?" },
    tool: { tool: "send_to_phone", say: "Sending to your phone" },
    speaking: { say: "Sent what you copied to your phone." },
    error: { say: "Your phone isn’t paired yet. Open KDE Connect on the PC and press Pair." },
  };
  const SCRIPT = [
    { state: "idle", ms: 1800, ...EXAMPLE.idle },
    { state: "listening", ms: 2800, heard: "send the clipboard to my phone" },
    { state: "thinking", ms: 1300, heard: "send the clipboard to my phone" },
    { state: "confirm", ms: 2600, ...EXAMPLE.confirm, auto: "yes" },
    { state: "idle", ms: 1600, ...EXAMPLE.idle },
    { state: "listening", ms: 1700, heard: "find my phone" },
    { state: "tool", ms: 1200, tool: "ring_phone", say: "Looking for your phone" },
    { state: "error", ms: 3400, ...EXAMPLE.error },
  ];
  const AFTER_YES = [
    { state: "tool", ms: 1400, ...EXAMPLE.tool },
    { state: "speaking", ms: 2800, ...EXAMPLE.speaking },
  ];
  const AFTER_NO = [{ state: "speaking", ms: 1600, say: "Okay, I won’t." }];

  const params = new URLSearchParams(location.search);
  const still = params.has("still"); // a frozen frame, for screenshots
  const calm = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const scene = {
    state: "idle", heard: "", heardShown: "", say: "", ask: "", tool: "",
    t: 0, since: 0, level: 0, mic: false, calm, still,
    seq: 0, // counts every state change, so a page can tell a new step from the same one
    picked: false, // this state was chosen by hand (a button, a key, ?state=), not by a run
  };
  const frames = [];
  let queue = [];
  let stepEnds = 0;
  let looping = !still && !params.has("state");
  let step = null;
  let analyser = null;
  let samples = null;

  function show(entry, now) {
    step = entry;
    scene.state = entry.state;
    scene.heard = entry.heard || "";
    scene.say = entry.say || "";
    scene.ask = entry.ask || "";
    scene.tool = entry.tool || "";
    scene.since = now;
    scene.seq += 1;
    scene.picked = Boolean(entry.picked);
    stepEnds = entry.ms ? now + entry.ms / 1000 : Infinity;
    document.body.dataset.state = entry.state;
    for (const el of document.querySelectorAll("[data-kit]")) {
      const key = el.dataset.kit;
      if (key === "label") el.textContent = NAMES[entry.state];
      else if (key !== "heard") el.textContent = scene[key] || "";
    }
    for (const button of document.querySelectorAll("[data-kit-state]")) {
      button.setAttribute("aria-pressed", String(button.dataset.kitState === entry.state));
    }
  }

  function run(steps, now) {
    queue = steps.slice();
    show(queue.shift(), now);
  }

  function next(now) {
    if (step && step.auto) return answer(step.auto === "yes");
    if (queue.length) return show(queue.shift(), now);
    if (looping) return run(SCRIPT, now);
    stepEnds = Infinity;
  }

  function answer(yes) {
    if (scene.state !== "confirm") return;
    const now = performance.now() / 1000;
    queue = (yes ? AFTER_YES : AFTER_NO).slice();
    if (looping) queue.push(...SCRIPT);
    show(queue.shift(), now);
  }

  function pick(state) {
    looping = false;
    updatePlay();
    queue = [];
    show({ state, ...EXAMPLE[state], picked: true }, performance.now() / 1000);
  }

  // A page's own turn, such as a typed message: these steps once, then rest.
  function play(steps) {
    looping = false;
    updatePlay();
    run(steps, performance.now() / 1000);
  }

  function stop() {
    looping = false;
    updatePlay();
    queue = [];
    show({ state: "idle", ...EXAMPLE.idle }, performance.now() / 1000);
  }

  function noise(t) {
    return (Math.sin(t * 7.3) + Math.sin(t * 13.1 + 1.7) * 0.6 + Math.sin(t * 29.9 + 0.4) * 0.3) / 1.9;
  }

  function syntheticLevel(t, inState) {
    switch (scene.state) {
      case "listening": return Math.min(1, 0.3 + 0.45 * Math.abs(noise(t * 1.4)));
      case "speaking": {
        const syllable = Math.abs(Math.sin(t * 9.5)) * (0.55 + 0.45 * Math.abs(Math.sin(t * 2.1)));
        return inState < 0.15 ? syllable * inState / 0.15 : syllable;
      }
      case "thinking": return 0.12 + 0.05 * Math.sin(t * 3);
      case "tool": return 0.2;
      default: return 0;
    }
  }

  function micLevel() {
    analyser.getFloatTimeDomainData(samples);
    let sum = 0;
    for (const v of samples) sum += v * v;
    return Math.min(1, Math.sqrt(sum / samples.length) * 6);
  }

  function tick(ms) {
    const now = ms / 1000;
    if (!still && now >= stepEnds) next(now);
    const t = still ? 2.2 : now;
    const inState = still ? 1.4 : now - scene.since;
    scene.t = t;
    const target = scene.mic && scene.state === "listening" ? micLevel() : syntheticLevel(t, inState);
    scene.level = still ? target : scene.level + (target - scene.level) * 0.25;
    // The words appear as they are heard.
    const share = scene.state === "listening" && !still ? Math.min(1, inState / 1.8) : 1;
    scene.heardShown = scene.heard.slice(0, Math.ceil(scene.heard.length * share));
    for (const el of document.querySelectorAll('[data-kit="heard"]')) {
      if (el.textContent !== scene.heardShown) el.textContent = scene.heardShown;
    }
    for (const fn of frames) fn(scene);
    requestAnimationFrame(tick); // a frozen frame keeps drawing the same picture, so resizes redraw
  }

  async function toggleMic(button, status) {
    if (scene.mic) {
      scene.mic = false;
      analyser.context.close();
      analyser = null;
      button.textContent = "Use my microphone";
      status.textContent = "";
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const context = new AudioContext();
      analyser = context.createAnalyser();
      analyser.fftSize = 1024;
      samples = new Float32Array(analyser.fftSize);
      context.createMediaStreamSource(stream).connect(analyser);
      scene.mic = true;
      button.textContent = "Stop using the microphone";
      status.textContent = "Listening follows your voice. Nothing is recorded or sent.";
      pick("listening");
    } catch (error) {
      status.textContent = "The microphone was not allowed. Allow it in the address bar and try again.";
    }
  }

  let playButton = null;
  function updatePlay() {
    if (playButton) playButton.textContent = looping ? "Pause the demo" : "Play the demo";
  }

  function dock() {
    const nav = document.querySelector("#dock");
    if (!nav) return;
    nav.setAttribute("aria-label", "Demo controls");
    const states = document.createElement("div");
    states.className = "kit-states";
    states.setAttribute("role", "group");
    states.setAttribute("aria-label", "Show a state");
    STATES.forEach((state, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.kitState = state;
      button.textContent = NAMES[state];
      button.title = `${NAMES[state]} (key ${index + 1})`;
      button.addEventListener("click", () => pick(state));
      states.append(button);
    });
    const actions = document.createElement("div");
    actions.className = "kit-actions";
    playButton = document.createElement("button");
    playButton.type = "button";
    playButton.addEventListener("click", () => {
      looping = !looping;
      updatePlay();
      if (looping) run(SCRIPT, performance.now() / 1000);
    });
    const mic = document.createElement("button");
    mic.type = "button";
    mic.textContent = "Use my microphone";
    const status = document.createElement("p");
    status.className = "kit-status";
    status.setAttribute("role", "status");
    mic.addEventListener("click", () => toggleMic(mic, status));
    actions.append(playButton, mic);
    nav.append(states, actions, status);
    updatePlay();
  }

  const css = `
  #dock { display: flex; flex-wrap: wrap; align-items: center; justify-content: center;
    gap: 8px 16px; padding: 10px 16px; color: var(--dock-fg); background: var(--dock-bg);
    font: 13px/1.3 var(--dock-font, inherit); }
  #dock button { font: inherit; color: inherit; background: transparent; cursor: pointer;
    border: 1px solid var(--dock-line); border-radius: var(--dock-radius, 999px); padding: 5px 11px; }
  #dock button:hover { border-color: var(--dock-fg); }
  #dock button[aria-pressed="true"] { background: var(--dock-accent); color: var(--dock-on-accent);
    border-color: var(--dock-accent); }
  #dock button:focus-visible, [data-kit-answer]:focus-visible { outline: 2px solid var(--dock-accent);
    outline-offset: 2px; }
  .kit-states, .kit-actions { display: flex; flex-wrap: wrap; gap: 6px; justify-content: center; }
  .kit-status { margin: 0; width: 100%; text-align: center; min-height: 1.3em; opacity: .8; }
  body.kit-still #dock { display: none; }`;

  function start() {
    const style = document.createElement("style");
    style.textContent = css;
    document.head.append(style);
    if (still) document.body.classList.add("kit-still");
    dock();
    for (const button of document.querySelectorAll("[data-kit-answer]")) {
      button.addEventListener("click", () => answer(button.dataset.kitAnswer === "yes"));
    }
    addEventListener("keydown", (event) => {
      if (event.target.closest && event.target.closest("input, textarea")) return;
      const index = Number(event.key) - 1;
      if (index >= 0 && index < STATES.length) pick(STATES[index]);
      else if (event.key === " " && event.target === document.body) {
        event.preventDefault();
        playButton.click();
      }
    });
    const first = params.get("state");
    const now = performance.now() / 1000;
    // <body data-kit-autoplay="off">: the page waits for you; "Play the demo" still runs it.
    if (document.body.dataset.kitAutoplay === "off") looping = false;
    updatePlay();
    if (STATES.includes(first)) show({ state: first, ...EXAMPLE[first], picked: true }, now);
    else if (looping) run(SCRIPT, now);
    else show({ state: "idle", ...EXAMPLE.idle }, now);
    requestAnimationFrame(tick);
  }

  if (document.readyState === "loading") addEventListener("DOMContentLoaded", start);
  else start();
  return { STATES, NAMES, EXAMPLE, scene, onFrame: (fn) => frames.push(fn), pick, answer, play, stop };
})();
