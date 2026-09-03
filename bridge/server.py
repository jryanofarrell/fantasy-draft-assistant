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
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from config import REPO_ROOT

FEED = REPO_ROOT / "bridge" / "feed.json"
DEFAULT_PORT = 8787


class Handler(BaseHTTPRequestHandler):
    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")

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
        FEED.parent.mkdir(parents=True, exist_ok=True)
        FEED.write_text(json.dumps({"picks": picks}, indent=1))
        print(f"  bridge: {len(picks)} picks", flush=True)

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
    args = ap.parse_args()

    FEED.parent.mkdir(parents=True, exist_ok=True)
    FEED.write_text(json.dumps({"picks": []}))
    print(f"bridge listening on http://127.0.0.1:{args.port}  ->  {FEED}")
    print("in another terminal:  ./run.py draft --provider local")
    try:
        HTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
