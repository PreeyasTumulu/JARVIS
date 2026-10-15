// What the model sees of a page: title, address, visible text, and numbered controls.
// Numbers are written into the page as data-jarvis-id and kept for as long as the page is open,
// so "click 12" still means the element the model saw, even after the page re-renders a bit.
// Runs inside the page; nothing here trusts the page's own text, it only reads it.
(limits) => {
  const SELECTOR = [
    "a[href]", "button", "input:not([type=hidden])", "textarea", "select", "summary",
    "[role=button]", "[role=link]", "[role=tab]", "[role=menuitem]", "[role=checkbox]",
    "[role=radio]", "[role=switch]", "[role=option]", "[role=textbox]", "[role=searchbox]",
    "[role=combobox]", "[contenteditable=''], [contenteditable=true]",
  ].join(",");
  const FIELD_TYPES = new Set(["", "text", "search", "email", "url", "tel", "number", "password"]);
  const clean = (text, max) => (text || "").replace(/\s+/g, " ").trim().slice(0, max);
  const visible = (el) => {
    const box = el.getBoundingClientRect();
    if (box.width < 2 || box.height < 2) return false;
    const style = getComputedStyle(el);
    return style.visibility !== "hidden" && style.display !== "none" && style.opacity !== "0";
  };
  const inView = (el) => {
    const box = el.getBoundingClientRect();
    return box.bottom > 0 && box.top < innerHeight && box.right > 0 && box.left < innerWidth;
  };
  const labelOf = (el) => {
    const byId = el.id ? document.querySelector(`label[for="${CSS.escape(el.id)}"]`) : null;
    return clean(
      el.getAttribute("aria-label") || (byId && byId.innerText) ||
      (el.tagName === "INPUT" || el.tagName === "TEXTAREA" ? "" : el.innerText) ||
      el.getAttribute("placeholder") || el.getAttribute("title") || el.getAttribute("alt") ||
      el.getAttribute("name") || (el.type === "submit" ? el.value : ""), 80);
  };
  const kindOf = (el) => {
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute("type") || "").toLowerCase();
    const role = (el.getAttribute("role") || "").toLowerCase();
    if (tag === "select" || role === "combobox" && tag !== "input") return "dropdown";
    if (type === "checkbox" || role === "checkbox" || role === "switch") return "checkbox";
    if (type === "radio" || role === "radio") return "radio";
    if (tag === "textarea" || el.isContentEditable || role === "textbox" || role === "searchbox" ||
        (tag === "input" && FIELD_TYPES.has(type)) || role === "combobox") return "field";
    if (tag === "a" || role === "link") return "link";
    return "button";
  };
  const isSearch = (el, form) => {
    const hints = [el.getAttribute("type"), el.getAttribute("role"), el.getAttribute("name"),
      el.id, el.getAttribute("aria-label"), el.getAttribute("placeholder"),
      form && form.getAttribute("role"), form && form.getAttribute("action")].join(" ").toLowerCase();
    return /\bsearch|\bq\b|\bquery\b|\bfind\b/.test(hints);
  };

  let next = window.__jarvisNextId || 1;
  const all = [];
  for (const el of document.querySelectorAll(SELECTOR)) {
    if (!visible(el)) continue;
    if (!el.hasAttribute("data-jarvis-id")) el.setAttribute("data-jarvis-id", String(next++));
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute("type") || "").toLowerCase();
    const form = el.form || el.closest("form");
    const kind = kindOf(el);
    all.push({
      id: Number(el.getAttribute("data-jarvis-id")),
      kind,
      label: labelOf(el),
      href: tag === "a" ? el.href : "",
      password: type === "password",
      autocomplete: (el.getAttribute("autocomplete") || "").toLowerCase(),
      submit: !!form && ((tag === "button" && (type === "" || type === "submit")) ||
        (tag === "input" && (type === "submit" || type === "image"))),
      search: isSearch(el, form),
      in_form: !!form,
      disabled: !!el.disabled || el.getAttribute("aria-disabled") === "true",
      in_view: inView(el),
    });
  }
  window.__jarvisNextId = next;
  // Fields first, then what is on screen, so a long page still shows the useful controls.
  // With limits.all (to find a control by name or number), every control comes back unsorted.
  const rank = (item) => (item.kind === "field" ? 0 : item.in_view ? 1 : 2);
  const named = all.filter((item) => item.label || item.kind === "field");
  const shown = limits.all ? named
    : named.sort((a, b) => rank(a) - rank(b) || a.id - b.id).slice(0, limits.elements);
  const text = (document.body ? document.body.innerText : "").replace(/\n\s*\n+/g, "\n").trim();
  return {
    title: clean(document.title, 120),
    url: location.href,
    text: text.slice(0, limits.chars),
    truncated: text.length > limits.chars,
    elements: shown,
  };
}
