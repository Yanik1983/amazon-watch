"""Entry point the poll loop runs every minute: `python -m watch.tick`.

Reads the status page's mailbox and polls Amazon only when an hour has passed.
"""
import sys

from watch.main import tick_main

if __name__ == "__main__":
    sys.exit(tick_main())
