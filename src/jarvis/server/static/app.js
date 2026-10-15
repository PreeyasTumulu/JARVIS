// Jarvis web UI. Plain JavaScript, no build step.
// Everything shown comes from the server as data and is inserted with textContent, never as
// HTML, because replies and tool results can contain text from web pages and files.
"use strict";

const token = new URLSearchParams(location.search).get("token") || "";
const $ = (id) => document.getElementById(id);
const ui = {
  chat: $("chat"), welcome: $("welcome"), suggestions: $("suggestions"),
  form: $("composer"), input: $("input"), send: $("send"), stop: $("stop"), mic: $("mic"),
  hint: $("hint"), meta: $("meta"), voice: $("voice"), conn: $("conn"),
  log: $("log"), logEmpty: $("log-empty"), audit: $("audit"), auditRefresh: $("audit-refresh"),
  tabActivity: $("tab-activity"), tabAudit: $("tab-audit"), tabContacts: $("tab-contacts"),
  panelActivity: $("panel-activity"), panelAudit: $("panel-audit"),
  panelContacts: $("panel-contacts"), contacts: $("contacts"), contactForm: $("contact-form"),
  contactName: $("contact-name"), contactPhone: $("contact-phone"),
  contactAliases: $("contact-aliases"), contactFile: $("contact-file"), contactNote: $("contact-note"),
};
const MAX_VCARD_BYTES = 2 * 1024 * 1024;

const VOICE_LABELS = {
  off: "Voice off", idle: "Ready", listening: "Listening", transcribing: "Transcribing",
  thinking: "Thinking", speaking: "Speaking", awaiting_answer: "Waiting for your answer",
};
const MIC_ICON = "M12 15a3 3 0 0 0 3-3V6a3 3 0 1 0-6 0v6a3 3 0 0 0 3 3Zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-2.08A7 7 0 0 0 19 12h-2Z";

let ws = null;
let everOpened = false;
let failures = 0;
let busy = false;
let voiceEnabled = false;
let micOn = false;
let answering = false;
const turns = new Map();     // turn_id -> {box, activity, thinking, steps: Map(call_id -> chip)}
const logEntries = new Map(); // call_id -> log entry element
const cards = new Map();      // request_id or question_id -> card element

// Small DOM helpers

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function icon(path) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  const shape = document.createElementNS("http://www.w3.org/2000/svg", "path");
  shape.setAttribute("d", path);
  svg.append(shape);
  return svg;
}

function nearBottom() {
  return ui.chat.scrollHeight - ui.chat.scrollTop - ui.chat.clientHeight < 120;
}

function append(node) {
  const stick = nearBottom();
  ui.welcome.hidden = true;
  ui.chat.append(node);
  if (stick) ui.chat.scrollTop = ui.chat.scrollHeight;
  return node;
}

function shortJson(value, limit = 120) {
  let text = typeof value === "string" ? value : JSON.stringify(value);
  if (!text || text === "{}") return "";
  return text.length > limit ? text.slice(0, limit - 3) + "..." : text;
}

function seconds(ms) {
  return ms >= 1000 ? (ms / 1000).toFixed(1) + " s" : ms + " ms";
}

function clock(ts) {
  const date = ts ? new Date(ts) : new Date();
  return isNaN(date) ? "" : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

// Connection

function connect() {
  if (!token) {
    setConn("refused", "No token");
    note("Open the link Jarvis printed in the terminal; it carries the access token.", "error");
    return;
  }
  ws = new WebSocket(`ws://${location.host}/ws?token=${encodeURIComponent(token)}`);
  ws.onopen = () => { everOpened = true; failures = 0; setConn("online", "Connected"); };
  ws.onmessage = (event) => {
    let message;
    try { message = JSON.parse(event.data); } catch { return; }
    handle(message);
  };
  ws.onclose = (event) => {
    ws = null;
    if (event.code === 1008) {
      setConn("refused", "Old link");
      note("This link is from an earlier Jarvis run. Open the new link printed in the terminal.", "error");
      return;
    }
    failures += 1;
    setConn("offline", "Offline");
    if (failures === 1 && everOpened) note("Lost the connection to Jarvis. Reconnecting...", "error");
    if (failures === 3) note("Jarvis is not answering. If you restarted it, open the new link from the terminal.", "error");
    setBusy(false);
    setTimeout(connect, Math.min(10000, 1000 * failures));
  };
}

function send(message) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(message));
    return true;
  }
  note("Not connected to Jarvis.", "error");
  return false;
}

function setConn(state, label) {
  ui.conn.dataset.state = state;
  ui.conn.textContent = label;
}

// State

function setBusy(value) {
  busy = value;
  ui.send.hidden = value;
  ui.stop.hidden = !value;
  if (!value) for (const turn of turns.values()) dropThinking(turn);
}

function setVoice(info) {
  voiceEnabled = Boolean(info && info.enabled);
  ui.mic.disabled = !voiceEnabled;
  ui.mic.title = voiceEnabled
    ? `Talk: click, speak, click again (or hold ${info.ptt_hotkey})`
    : "Voice is off in this session";
  setVoiceState(voiceEnabled ? info.state || "idle" : "off");
  if (voiceEnabled) {
    let hint = `Enter sends, Esc stops. Hold ${info.ptt_hotkey} anywhere to talk`;
    if (info.wake_word) hint += ', or say "Hey Jarvis"';
    ui.hint.textContent = hint + ".";
  }
}

function setVoiceState(state, detail) {
  ui.voice.dataset.state = state;
  ui.voice.textContent = VOICE_LABELS[state] || state;
  ui.voice.title = detail || "";
  if (state === "awaiting_answer") answering = true;
  if (state !== "listening" && micOn) setMic(false);
}

function setMic(on) {
  micOn = on;
  ui.mic.setAttribute("aria-pressed", String(on));
}

// Turns

function turnFor(turnId) {
  let turn = turns.get(turnId);
  if (!turn) {
    const box = el("div", "turn");
    turn = { box, activity: null, thinking: null, steps: new Map() };
    turns.set(turnId, turn);
    append(box);
  }
  return turn;
}

function addThinking(turn) {
  if (turn.thinking) return;
  turn.thinking = el("div", "thinking");
  turn.thinking.append(el("span"), el("span"), el("span"));
  turn.box.append(turn.thinking);
}

function dropThinking(turn) {
  if (turn.thinking) { turn.thinking.remove(); turn.thinking = null; }
}

function addToTurn(turn, node) {
  const stick = nearBottom();
  if (turn.thinking) turn.box.insertBefore(node, turn.thinking);
  else turn.box.append(node);
  if (stick) ui.chat.scrollTop = ui.chat.scrollHeight;
  return node;
}

const SOURCE_LABELS = { voice: "spoken", cli: "from the terminal" };

function userBubble(container, text, source) {
  container.append(el("div", "bubble user", text));
  if (SOURCE_LABELS[source]) {
    const label = el("div", "source");
    if (source === "voice") label.append(icon(MIC_ICON));
    label.append(document.createTextNode(SOURCE_LABELS[source]));
    container.append(label);
  }
}

function replyBubble(text, status) {
  const stopped = status && status !== "ok" && status !== "limit";
  return el("div", "bubble jarvis" + (stopped ? " stopped" : ""), text);
}

function note(text, kind) {
  return append(el("div", "note" + (kind ? " " + kind : ""), text));
}

// Cards: confirmations and questions

function confirmCard(message) {
  const request = message.request;
  if (cards.has(request.request_id)) return;
  const card = el("div", "card");
  card.append(el("div", "label", "Confirm"), el("div", "summary", request.summary));
  if (request.reason) card.append(el("div", "reason", request.reason));
  const timer = el("div", "timer");
  const bar = el("div");
  bar.style.animationDuration = `${request.timeout_s}s`;
  timer.append(bar);
  const actions = el("div", "actions");
  const yes = el("button", "btn primary", "Confirm");
  const no = el("button", "btn danger", "Cancel");
  yes.type = no.type = "button";
  yes.addEventListener("click", () => answerConfirm(request.request_id, true));
  no.addEventListener("click", () => answerConfirm(request.request_id, false));
  actions.append(yes, no);
  card.append(actions, timer);
  cards.set(request.request_id, card);
  addToTurn(turnFor(message.turn_id), card);
  yes.focus({ preventScroll: true });
}

function answerConfirm(requestId, approved) {
  const card = cards.get(requestId);
  if (card) card.querySelectorAll("button").forEach((button) => { button.disabled = true; });
  send({ type: "confirm", request_id: requestId, approved });
}

const DECISIONS = {
  confirmed: ["Confirmed", "ok"], denied: ["Cancelled", "bad"],
  timeout: ["No answer in time, so it was not done", "bad"], cancelled: ["Stopped", "bad"],
};

function closeConfirm(message) {
  const card = cards.get(message.request_id);
  if (!card) return;
  cards.delete(message.request_id);
  const [label, kind] = DECISIONS[message.decision] || [message.decision, ""];
  const via = message.via ? ` (${message.via.replace("+", " or ")})` : "";
  card.append(el("div", "outcome " + kind, label + via));
  card.classList.add("closed");
  answering = false;
}

function questionCard(message) {
  if (cards.has(message.question_id)) return;
  const card = el("div", "card question");
  card.append(el("div", "label", "Jarvis asks"), el("div", "summary", message.question));
  const reply = (text) => {
    card.querySelectorAll("button, input").forEach((node) => { node.disabled = true; });
    send({ type: "answer", question_id: message.question_id, text });
  };
  if (message.options && message.options.length) {
    const actions = el("div", "actions");
    for (const option of message.options) {
      const button = el("button", "btn", option);
      button.type = "button";
      button.addEventListener("click", () => reply(option));
      actions.append(button);
    }
    card.append(actions);
  }
  const answer = el("form", "answer");
  const input = el("input");
  input.placeholder = "Type an answer";
  input.setAttribute("aria-label", "Answer");
  const submit = el("button", "btn primary", "Answer");
  answer.append(input, submit);
  answer.addEventListener("submit", (event) => {
    event.preventDefault();
    if (input.value.trim()) reply(input.value.trim());
  });
  card.append(answer);
  cards.set(message.question_id, card);
  append(card);
  input.focus({ preventScroll: true });
}

function closeQuestion(message) {
  const card = cards.get(message.question_id);
  if (!card) return;
  cards.delete(message.question_id);
  card.classList.add("closed");
  answering = false;
}

// Activity log

function logStart(message) {
  ui.logEmpty.hidden = true;
  const entry = el("li", "entry");
  const row = el("div", "row");
  const dot = el("span", "status-dot running");
  row.append(dot, el("span", "tool", message.tool), el("span", "tag " + message.risk, message.risk));
  row.append(el("span", "time", clock()));
  entry.append(row);
  const args = shortJson(message.args, 200);
  if (args) entry.append(el("div", "args", args));
  ui.log.prepend(entry);
  logEntries.set(message.call_id, entry);
  while (ui.log.children.length > 200) ui.log.lastElementChild.remove();
}

function logFinish(message) {
  let entry = logEntries.get(message.call_id);
  if (!entry) {  // invalid or unknown tools never start: they finish straight away
    logStart({ call_id: message.call_id, tool: message.tool, risk: message.decision, args: {} });
    entry = logEntries.get(message.call_id);
  }
  logEntries.delete(message.call_id);
  entry.querySelector(".status-dot").className = "status-dot " + (message.ok ? "ok" : "bad");
  const row = entry.querySelector(".row");
  row.insertBefore(el("span", "tag " + message.decision, message.decision), row.lastElementChild);
  row.lastElementChild.textContent = seconds(message.duration_ms);
  entry.append(el("div", "detail" + (message.ok ? "" : " bad"), shortJson(message.summary, 300)));
}

// Steps inside a turn

function stepStart(message) {
  const turn = turnFor(message.turn_id);
  if (!turn.activity) turn.activity = addToTurn(turn, el("div", "activity"));
  const chip = el("span", "step running", message.tool);
  turn.activity.append(chip);
  turn.steps.set(message.call_id, chip);
}

function stepFinish(message) {
  const turn = turnFor(message.turn_id);
  let chip = turn.steps.get(message.call_id);
  if (!chip) {
    if (!turn.activity) turn.activity = addToTurn(turn, el("div", "activity"));
    chip = turn.activity.appendChild(el("span", "step", message.tool));
  }
  chip.className = "step " + (message.ok ? "ok" : "bad");
  chip.textContent = `${message.tool} ${message.ok ? "ok" : "failed"} ${seconds(message.duration_ms)}`;
  chip.title = message.summary || "";
}

// Audit view

function renderAudit(rows) {
  ui.audit.replaceChildren();
  if (!rows.length) {
    ui.audit.append(el("li", "empty", "No tool calls yet."));
    return;
  }
  for (const row of rows.slice().reverse()) {
    const entry = el("li", "entry");
    const head = el("div", "row");
    head.append(el("span", "status-dot " + (row.ok ? "ok" : "bad")), el("span", "tool", row.tool));
    head.append(el("span", "tag " + row.decision, row.decision));
    if (row.confirmed_via) head.append(el("span", "tag", "via " + row.confirmed_via));
    head.append(el("span", "time", clock(row.ts)));
    entry.append(head);
    const args = shortJson(row.args_json || "", 200);
    if (args) entry.append(el("div", "args", args));
    if (row.error) entry.append(el("div", "detail bad", shortJson(row.error, 300)));
    else if (row.result_json) entry.append(el("div", "detail", shortJson(row.result_json, 300)));
    ui.audit.append(entry);
  }
}

// Contacts

function renderContacts(message) {
  ui.contacts.replaceChildren();
  if (message.note) contactNote(message.note, message.error);
  if (!message.contacts.length) {
    ui.contacts.append(el("li", "empty", "No contacts yet. Add the people you message."));
    return;
  }
  for (const contact of message.contacts) {
    const entry = el("li", "entry contact");
    const head = el("div", "row");
    head.append(el("span", "who", contact.name));
    const remove = el("button", "ghost remove", "Remove");
    remove.type = "button";
    remove.addEventListener("click", () => {
      if (window.confirm(`Remove ${contact.name} from Jarvis's contacts?`)) {
        send({ type: "contact_remove", id: contact.id });
      }
    });
    head.append(remove);
    entry.append(head, el("div", "phone", contact.phone));
    if (contact.aliases.length) entry.append(el("div", "also", "Also: " + contact.aliases.join(", ")));
    ui.contacts.append(entry);
  }
}

function contactNote(text, bad) {
  ui.contactNote.textContent = text;
  ui.contactNote.className = "form-note" + (bad ? " bad" : "");
  ui.contactNote.hidden = !text;
}

function requestContacts() {
  ui.contacts.replaceChildren(el("li", "empty", "Loading..."));
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "contacts" }));
}

ui.contactForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const aliases = ui.contactAliases.value.split(",").map((a) => a.trim()).filter(Boolean);
  const sent = send({
    type: "contact_add", name: ui.contactName.value, phone: ui.contactPhone.value, aliases,
  });
  if (sent) contactNote("Saving...", false);
});

ui.contactFile.addEventListener("change", async () => {
  const file = ui.contactFile.files && ui.contactFile.files[0];
  ui.contactFile.value = "";
  if (!file) return;
  if (file.size > MAX_VCARD_BYTES) {
    contactNote("That file is larger than 2 MB.", true);
    return;
  }
  if (send({ type: "contact_import", text: await file.text() })) contactNote("Importing...", false);
});

// Messages from the server

function hello(message) {
  ui.meta.textContent = `${message.model} · v${message.version}`;
  for (const node of [...ui.chat.children]) if (node !== ui.welcome) node.remove();
  turns.clear();
  cards.clear();
  ui.welcome.hidden = message.history.length > 0;
  if (message.history.length) {
    ui.chat.append(el("div", "divider", "Earlier"));
    for (const row of message.history) {
      const box = el("div", "turn");
      userBubble(box, row.text, row.source);
      if (row.reply) box.append(replyBubble(row.reply, row.status));
      ui.chat.append(box);
    }
    ui.chat.scrollTop = ui.chat.scrollHeight;
  }
  setVoice(message.voice);
  setBusy(message.busy);
  if (!ui.panelAudit.hidden) requestAudit();  // the tab was open while reconnecting
  if (!ui.panelContacts.hidden) requestContacts();
  for (const item of message.open) {
    if (item.type === "confirmation_requested") confirmCard(item);
    else if (item.type === "question") questionCard(item);
  }
}

const handlers = {
  hello,
  turn_started(message) {
    const turn = turnFor(message.turn_id);
    userBubble(turn.box, message.text, message.source);
    addThinking(turn);
    setBusy(true);
  },
  tool_call_started(message) { stepStart(message); logStart(message); },
  tool_call_finished(message) { stepFinish(message); logFinish(message); },
  confirmation_requested: confirmCard,
  confirmation_resolved: closeConfirm,
  question: questionCard,
  question_closed: closeQuestion,
  assistant_message(message) {
    const turn = turnFor(message.turn_id);
    dropThinking(turn);
    addToTurn(turn, replyBubble(message.text, message.text === "Stopped." ? "cancelled" : "ok"));
  },
  turn_finished(message) {
    const turn = turns.get(message.turn_id);
    if (turn) dropThinking(turn);
    setBusy(false);
    answering = false;
  },
  voice_state_changed(message) { setVoiceState(message.state, message.detail); },
  transcript_heard(message) {
    if (answering) note(`You said: ${message.text}`);
  },
  reminder_due(message) { append(el("div", "note reminder", message.text)); },
  audit(message) { renderAudit(message.rows); },
  contacts(message) {
    renderContacts(message);
    if (message.added) ui.contactForm.reset();
  },
  error(message) { note(message.message, "error"); },
};

function handle(message) {
  const handler = handlers[message.type];
  if (handler) handler(message);
}

// Input

function submit(text) {
  const command = text.trim();
  if (!command) return;
  if (busy) {
    note("Still working on the last command. Press Stop (Esc) to cancel it.", "error");
    return;
  }
  if (send({ type: "command", text: command })) {
    ui.input.value = "";
    resizeInput();
  }
}

function stop() {
  if (micOn) setMic(false);
  send({ type: "stop" });
}

function resizeInput() {
  ui.input.style.height = "auto";
  ui.input.style.height = Math.min(ui.input.scrollHeight, 160) + "px";
  ui.input.style.overflowY = ui.input.scrollHeight > 160 ? "auto" : "hidden";
}

ui.form.addEventListener("submit", (event) => {
  event.preventDefault();
  submit(ui.input.value);
});
ui.input.addEventListener("input", resizeInput);
ui.input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    submit(ui.input.value);
  }
});
ui.stop.addEventListener("click", stop);
ui.mic.addEventListener("click", () => {
  if (!voiceEnabled) return;
  const on = !micOn;
  if (send({ type: "mic", on })) setMic(on);
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && (busy || micOn || ui.voice.dataset.state === "speaking")) stop();
});
ui.suggestions.addEventListener("click", (event) => {
  if (event.target instanceof HTMLButtonElement) submit(event.target.textContent);
});

function showTab(name) {
  const tabs = {
    activity: [ui.tabActivity, ui.panelActivity],
    audit: [ui.tabAudit, ui.panelAudit],
    contacts: [ui.tabContacts, ui.panelContacts],
  };
  for (const [key, [tab, panel]] of Object.entries(tabs)) {
    tab.setAttribute("aria-selected", String(key === name));
    panel.hidden = key !== name;
  }
  if (name === "audit") requestAudit();
  if (name === "contacts") requestContacts();
}

function requestAudit() {
  ui.audit.replaceChildren(el("li", "empty", "Loading..."));
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "audit" }));
}
ui.tabActivity.addEventListener("click", () => showTab("activity"));
ui.tabAudit.addEventListener("click", () => showTab("audit"));
ui.tabContacts.addEventListener("click", () => showTab("contacts"));
ui.auditRefresh.addEventListener("click", requestAudit);

connect();
resizeInput();
ui.input.focus();
