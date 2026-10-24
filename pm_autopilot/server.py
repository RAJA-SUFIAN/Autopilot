"""`python main.py serve` - browse the outbox at http://localhost:<port> (no extra installs needed)."""
from __future__ import annotations

import functools
import http.server
import webbrowser
from pathlib import Path


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002 - keep the terminal clean
        pass


def make_server(directory: Path, port: int, attempts: int = 20) -> http.server.ThreadingHTTPServer:
    """Bind to `port`, or the next free port if it is taken."""
    handler = functools.partial(_QuietHandler, directory=str(directory))
    last_error: OSError | None = None
    for candidate in range(port, port + attempts):
        try:
            return http.server.ThreadingHTTPServer(("127.0.0.1", candidate), handler)
        except OSError as exc:
            last_error = exc
    raise OSError(f"no free port between {port} and {port + attempts - 1}") from last_error


def serve(directory: Path, port: int = 8765, open_browser: bool = True) -> None:
    server = make_server(directory, port)
    url = f"http://localhost:{server.server_address[1]}/"
    print(f"Outbox viewer running at {url}  (press Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
