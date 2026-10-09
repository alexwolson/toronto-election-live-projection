"""The `mock-feed` HTTP shell: serves `MockFeed.respond` at any path ending in a City file name."""

import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from election_night.mockfeed.feed import MockFeed


def serve(feed: MockFeed, port: int) -> None:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            file = self.path.split("?", 1)[0].rsplit("/", 1)[-1]
            response = feed.respond(file, time.time() * 1000, self.headers.get("If-None-Match"))
            if response.delay:
                time.sleep(response.delay)
            self.send_response(response.status)
            for name, value in response.headers.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(response.body)))
            self.end_headers()
            self.wfile.write(response.body)

        def log_message(self, format, *args) -> None:
            print(f"{self.address_string()} {format % args}", file=sys.stderr, flush=True)

    with ThreadingHTTPServer(("", port), Handler) as server:
        print(f"mock feed on :{port}", file=sys.stderr, flush=True)
        server.serve_forever()
