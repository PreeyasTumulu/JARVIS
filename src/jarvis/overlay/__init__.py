"""The fullscreen effect when you say "Hey Jarvis" (ADR-070).

`director` turns bus events into small messages, `client` carries them over a pipe to a separate
process, and `window` draws them in a click-through window that never takes focus. The process is
separate so that a graphics driver crash cannot take the assistant down with it, and the pipe
means nothing here listens on a socket.
"""

EXIT_NO_GRAPHICS = 3  # the overlay process cannot draw on this computer; the client does not retry
