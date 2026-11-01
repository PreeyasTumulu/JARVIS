"""`python -m jarvis.overlay`: started by client.py, with its messages on stdin."""

import sys

from jarvis.overlay.window import main

if __name__ == "__main__":
    sys.exit(main())
