"""Network web controls; all firmware execution stays in native workers."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .engine import EngineError
from .firmware import MAX_IMAGE_BYTES, parse_firmware


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, session, ui: Path, allow_invalid_crc: bool = False):
        super().__init__(address, Handler)
        self.session = session
        self.ui = ui
        self.allow_invalid_crc = allow_invalid_crc
        browser_host = "127.0.0.1" if address[0] == "0.0.0.0" else address[0]
        self.authority = f"{browser_host}:{self.server_port}"


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, *_):
        pass

    def _allowed(self) -> bool:
        # A wildcard listener's accepted socket identifies the actual LAN IP.
        authorities = {self.server.authority, f"localhost:{self.server.server_port}",
                       f"{self.connection.getsockname()[0]}:{self.server.server_port}"}
        if self.server.server_port == 80:
            authorities.update(authority.removesuffix(":80") for authority in tuple(authorities))
        host = self.headers.get("Host")
        if host not in authorities:
            self._json(403, {"error": "Invalid Host header"})
            return False
        origin = self.headers.get("Origin")
        if origin and origin != f"http://{host}":
            self._json(403, {"error": "Cross-origin requests are not accepted"})
            return False
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            self._json(403, {"error": "Cross-site requests are not accepted"})
            return False
        return True

    def _send(self, status: int, data: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, status: int, data: dict) -> None:
        self._send(status, json.dumps(data, separators=(",", ":")).encode(), "application/json")

    def do_GET(self):
        if not self._allowed():
            return
        path = urlsplit(self.path).path
        if path == "/api/state":
            try:
                self._json(200, self.server.session.state())
            except EngineError as error:
                self._json(409, {"error": str(error)})
            return
        files = {"/": ("index.html", "text/html; charset=utf-8"),
                 "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                 "/style.css": ("style.css", "text/css; charset=utf-8")}
        if path not in files:
            self._json(404, {"error": "Not found"})
            return
        name, kind = files[path]
        self._send(200, (self.server.ui / name).read_bytes(), kind)

    def do_POST(self):
        if not self._allowed():
            return
        try:
            if self.headers.get("Transfer-Encoding"):
                raise ValueError("Transfer encoding is unsupported")
            length = int(self.headers.get("Content-Length", "-1"))
            limit = MAX_IMAGE_BYTES if self.path == "/api/firmware" else 65536
            if not 0 < length <= limit:
                raise ValueError(f"Request body must contain 1 to {limit} bytes")
            body = self.rfile.read(length)
            if len(body) != length:
                raise ValueError("Truncated request body")
            if self.path == "/api/firmware":
                filename = Path(unquote(self.headers.get("X-Filename", "upload.bin"))).name
                firmware = parse_firmware(body, filename, allow_invalid_crc=self.server.allow_invalid_crc)
                if firmware.image in ("trx", "ptt"):
                    # These payloads are shared by both upgrade packages.
                    firmware = parse_firmware(body, filename, model=self.server.session.model,
                                              allow_invalid_crc=self.server.allow_invalid_crc)
                self.server.session.load(firmware)
                response = {"ok": True, "message": f"Loaded {filename}", "firmware": firmware.describe(),
                            "key_epoch": self.server.session.key_epoch,
                            "session_id": self.server.session.session_id}
            else:
                if self.headers.get_content_type() != "application/json":
                    raise ValueError("Use application/json for control requests")
                data = json.loads(body)
                if not isinstance(data, dict):
                    raise ValueError("Control request must be a JSON object")
                response = self._control(data)
            self._json(200, response)
        except (ValueError, TypeError, KeyError, UnicodeDecodeError) as error:
            self._json(400, {"error": str(error)})
        except EngineError as error:
            self._json(409, {"error": str(error)})
        except TimeoutError:
            self._json(408, {"error": "Request body timed out"})

    def _control(self, data: dict) -> dict:
        session = self.server.session
        if self.path == "/api/control":
            return session.control(data.get("action"), data.get("steps", 10000))
        if self.path == "/api/key":
            return session.key(data.get("key"), data.get("pressed"), data.get("generation"),
                               client_id=data.get("client_id"), sequence=data.get("sequence"),
                               epoch=data.get("epoch"), session_id=data.get("session_id"))
        if self.path == "/api/satellite":
            action = data.pop("action", None)
            return session.satellite_action(action, data)
        if self.path == "/api/probe":
            image, operation = data.pop("image", "bc5"), data.pop("operation", None)
            return session.probe(image, operation, data)
        raise ValueError("Unknown API endpoint")
