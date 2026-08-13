"""``python -m siphon`` — launch the Siphon desktop app.

Flags:
  --browser   open in the default browser instead of a desktop window
  --port N    server port (default 8677)
"""

from __future__ import annotations

import argparse
import logging

from .launcher import main as launch


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(prog="siphon", description="Grab any video in 4K.")
    ap.add_argument("--browser", action="store_true", help="Open in browser, not a window.")
    args = ap.parse_args()
    launch(browser=args.browser)


if __name__ == "__main__":
    main()
