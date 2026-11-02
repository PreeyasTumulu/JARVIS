# Security

Jarvis can operate your computer, so its safety model is part of the product. It is described in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), section 6.

## What Jarvis guarantees, in code

- Tools that send, delete, stop, buy, call, or close something wait for your explicit yes; the approval is bound to the exact prepared action, and config cannot lower a tool's floor.
- Text from web pages, files, notifications, windows, and the clipboard is wrapped as untrusted data and can never approve anything.
- After private and outside content are both in a conversation, any tool that sends data to an address the model picks asks first.
- Private content (messages, notifications, files, clipboard, screen text, contacts, memory) never reaches a cloud model; the router raises before sending it.
- Values shaped like secrets are hidden before the model or the audit log sees them.
- The web UI listens on 127.0.0.1 only, checks the Host and Origin headers, needs a per-launch token, and cannot be framed. The Claude Code bridge needs a bearer token from your data folder and refuses any request from a browser.
- Every tool call, including refused ones, is in the local audit log.

## Reporting a vulnerability

Please do not open a public issue for a security problem. Use GitHub's private vulnerability reporting (the repository's Security tab, "Report a vulnerability"), with steps to reproduce. You will get a reply within a week. Prompt-injection paths (content that gets Jarvis to act without your yes, or private data that reaches the network or a cloud model) are in scope and especially welcome.
