"""Local bridge between the browser and the draft assistant.

ESPN does not publish picks to its API while a draft is running, so the only
place they exist is the draft room in your browser. The userscript in this
directory forwards them here; this writes them to a file the assistant reads
through its `local` provider.

    ./run.py bridge          # start me, then open the draft room

Listens on 127.0.0.1 only. Nothing is exposed off the machine.
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from config import REPO_ROOT

FEED_DIR = REPO_ROOT / "bridge" / "feeds"


def feed_for(league: str | None) -> Path:
    """One file per draft.

    Sharing a single file meant a new draft inherited the previous one's
    picks — players marked drafted who were not, and real picks skipped
    because their numbers were already spoken for. Keyed by league, that
    cannot happen.
    """
    name = "".join(c for c in str(league or "unknown") if c.isalnum()) or "unknown"
    return FEED_DIR / f"draft-{name}.json"
DEFAULT_PORT = 8787


class Server(HTTPServer):
    # Without this a restart within the TIME_WAIT window is refused, which
    # on a draft clock is exactly when you are restarting.
    allow_reuse_address = True


class Handler(BaseHTTPRequestHandler):
    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        # Chrome blocks a public https page from reaching a private address
        # unless the target opts in. Without this the draft room's POSTs are
        # refused before they ever arrive.
        self.send_header("Access-Control-Allow-Private-Network", "true")

    def do_OPTIONS(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8", "replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            self.send_response(400)
            self._cors()
            self.end_headers()
            return

        picks = payload.get("picks", payload if isinstance(payload, list) else [])
        league = payload.get("leagueId")

        feed = feed_for(league)
        feed.parent.mkdir(parents=True, exist_ok=True)
        feed.write_text(json.dumps({
            "leagueId": league,
            "complete": payload.get("complete", False),
            "picks": picks,
        }, indent=1))
        print(f"  bridge: {len(picks)} picks -> {feed.name}", flush=True)

        self.send_response(200)
        self._cors()
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def log_message(self, *args) -> None:
        pass  # the POST handler already reports what matters


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--reset", action="store_true",
                    help="discard previously captured picks and start clean")
    args = ap.parse_args()

    FEED_DIR.mkdir(parents=True, exist_ok=True)
    if args.reset:
        removed = 0
        for path in FEED_DIR.glob("draft-*.json"):
            path.unlink()
            removed += 1
        print(f"cleared {removed} stored draft(s)")
    else:
        existing = sorted(FEED_DIR.glob("draft-*.json"),
                          key=lambda p: p.stat().st_mtime, reverse=True)
        if existing:
            print(f"{len(existing)} stored draft(s); newest is "
                  f"{existing[0].name} (--reset to clear)")

    try:
        server = Server(("127.0.0.1", args.port), Handler)
    except OSError as exc:
        if exc.errno != 48:
            raise
        print(f"error: port {args.port} is already in use — most likely a "
              f"bridge you left running.\n"
              f"  find it:  lsof -ti :{args.port}\n"
              f"  stop it:  kill $(lsof -ti :{args.port})\n"
              f"  or pick another port:  ./run.py bridge --port {args.port + 1}\n"
              f"     (then edit BRIDGE in bridge/espn-capture.user.js to match)",
              file=sys.stderr)
        return 1

    print(f"bridge listening on http://127.0.0.1:{args.port}  ->  {FEED_DIR}/")
    print("in another terminal:  ./run.py draft --live --provider local")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
