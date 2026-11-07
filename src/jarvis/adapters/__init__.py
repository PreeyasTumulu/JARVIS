"""Adapters: the only code that talks to the world outside Jarvis's own process.

Tools decide what to do; adapters do it. A tool never opens a socket, starts a process, or
calls a Windows API itself. Keeping that in one layer gives every outside call the same
timeouts, retries, rate limits, key handling, and redaction, and gives tests one place to fake.

- Web APIs: `jarvis.adapters.http.ApiClient`. Keys from .env, one retry, rate limits,
  circuit breakers, a SQLite cache, and logs without query strings.
- Windows (windows, input, volume, display, clipboard, OCR, notifications): `jarvis.platform`,
  one module per Windows API.
- Apps: `jarvis.tools.apps.index`, the Start menu index, launched by AppsFolder id.
- Browser: `jarvis.tools.browser.session`, Playwright on Brave or Edge with its own profile.
- MCP servers: `jarvis.tools.mcp.hub`, stdio processes, listed tools only.
- Shell and SSH (Phase 27) and telephony (Phase 29) come here too, with the same rules: a
  timeout, a retry rule, redacted logs, and keys only from .env.

A new outside service gets an adapter here, not code inside a tool.
"""
