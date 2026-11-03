import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

from iridium.firmware import parse_firmware
from iridium.__main__ import arguments
from iridium.server import Server
from iridium.session import Session
from test_session import FakeEngine


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        ui = Path(self.directory.name)
        (ui / "index.html").write_text("<title>Firmware lab</title>")
        self.session = Session(Path("unused"), [parse_firmware(bytes(8678), "avr.bin")], FakeEngine)
        self.addCleanup(self.session.close)
        self.server = Server(("0.0.0.0", 0), self.session, ui)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, method, path, body=None, headers=None, address="127.0.0.1"):
        connection = http.client.HTTPConnection(address, self.server.server_port)
        try:
            connection.request(method, path, body, headers or {})
            response = connection.getresponse()
            return response.status, response.read(), dict(response.getheaders())
        finally:
            connection.close()

    def test_local_controls_and_state(self):
        status, data, _ = self.request("POST", "/api/control", '{"action":"step","steps":42}',
                                       {"Content-Type": "application/json"})
        self.assertEqual(status, 200, data)
        status, data, _ = self.request("GET", "/api/state")
        self.assertEqual(json.loads(data)["processors"][0]["steps"], 42)

    def test_network_binding_and_matching_origin_use_the_connection_destination(self):
        self.assertEqual(arguments([]).host, "0.0.0.0")
        self.assertEqual(arguments(["--host", "127.0.0.1"]).host, "127.0.0.1")
        self.assertEqual(self.server.server_address[0], "0.0.0.0")
        self.assertEqual(self.server.authority, f"127.0.0.1:{self.server.server_port}")
        address = "127.0.0.2"
        origin = f"http://{address}:{self.server.server_port}"
        status, data, _ = self.request("GET", "/api/state", address=address)
        self.assertEqual(status, 200, data)
        status, data, _ = self.request("POST", "/api/control", '{"action":"step","steps":17}',
                                       {"Content-Type": "application/json", "Origin": origin}, address)
        self.assertEqual(status, 200, data)
        self.assertEqual(self.session.state()["processors"][0]["steps"], 17)

    def test_localhost_alias_and_mismatched_origin(self):
        host = f"localhost:{self.server.server_port}"
        headers = {"Content-Type": "application/json", "Host": host, "Origin": f"http://{host}"}
        status, data, _ = self.request("POST", "/api/control", '{"action":"pause"}', headers)
        self.assertEqual(status, 200, data)
        headers["Origin"] = f"http://127.0.0.1:{self.server.server_port}"
        status, _, _ = self.request("POST", "/api/control", '{"action":"run"}', headers)
        self.assertEqual(status, 403)
        self.assertFalse(self.session.running)

    def test_rejects_cross_origin_and_dns_rebinding(self):
        for headers in ({"Origin": "https://external.example"}, {"Host": "external.example"},
                        {"Sec-Fetch-Site": "cross-site"}):
            status, _, _ = self.request("POST", "/api/control", '{"action":"run"}', headers)
            self.assertEqual(status, 403)
        self.assertFalse(self.session.running)

    def test_rejects_traversal_bad_types_and_content_type(self):
        status, _, _ = self.request("GET", "/../run")
        self.assertEqual(status, 404)
        for body, content_type in (("[]", "application/json"), ("{", "application/json"),
                                   ('{"action":"run"}', "text/plain")):
            status, _, _ = self.request("POST", "/api/control", body, {"Content-Type": content_type})
            self.assertEqual(status, 400)

    def test_upload_uses_supplied_bytes_and_static_html_has_csp(self):
        patch = b"\1\2" + bytes(8676)
        status, data, _ = self.request("POST", "/api/firmware", patch, {"X-Filename": "avr.bin"})
        self.assertEqual(status, 200, data)
        self.assertEqual(self.session.engines["avr"].data, patch)
        status, _, headers = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])


if __name__ == "__main__":
    unittest.main()
