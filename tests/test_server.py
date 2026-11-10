from concurrent.futures import ThreadPoolExecutor
import base64
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock

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
        self.assertEqual(json.loads(data)["session_id"], self.session.session_id)
        status, data, _ = self.request("GET", "/api/state")
        self.assertEqual(json.loads(data)["processors"][0]["steps"], 42)
        self.assertEqual(json.loads(data)["session_id"], self.session.session_id)

    def test_restarted_session_rejects_old_keys_even_when_epochs_match(self):
        old_id = self.session.state()["session_id"]
        replacement = Session(Path("unused"), [parse_firmware(bytes(8678), "avr.bin")], FakeEngine)
        self.addCleanup(replacement.close)
        self.server.session = replacement
        self.assertEqual(replacement.key_epoch, self.session.key_epoch)
        self.assertNotEqual(replacement.session_id, old_id)
        body = {"key": "1", "pressed": True, "client_id": "tab", "sequence": 1,
                "epoch": replacement.key_epoch, "session_id": old_id}
        status, data, _ = self.request("POST", "/api/key", json.dumps(body),
                                       {"Content-Type": "application/json"})
        self.assertEqual(status, 200, data)
        self.assertIn("Stale key session", json.loads(data)["message"])
        self.assertEqual(json.loads(data)["session_id"], replacement.session_id)
        self.assertEqual(replacement.keys, set())
        self.assertEqual(replacement._key_clients, {})
        body["session_id"] = replacement.session_id
        status, data, _ = self.request("POST", "/api/key", json.dumps(body),
                                       {"Content-Type": "application/json"})
        self.assertEqual(status, 200, data)
        self.assertEqual(replacement.keys, {"1"})
        body.update(pressed=False, sequence=2, session_id=old_id)
        self.request("POST", "/api/key", json.dumps(body), {"Content-Type": "application/json"})
        self.assertEqual(replacement.keys, {"1"})

    def test_bundle_upload_validates_all_images_before_loading(self):
        old = self.session.engines["avr"]
        good = {"name": "avr.bin", "data": base64.b64encode(bytes(8678)).decode()}
        for images in ([], [good, good], [good, {"name": "bad", "data": "%%%"}],
                       [good, {"name": "bad", "data": "YQ=="}],
                       [good, {"name": [], "data": "YQ=="}]):
            status, data, _ = self.request("POST", "/api/firmware-bundle", json.dumps({"images": images}),
                                           {"Content-Type": "application/json"})
            self.assertEqual(status, 400, data)
            self.assertIs(self.session.engines["avr"], old)
            self.assertFalse(old.closed)
        status, data, _ = self.request("POST", "/api/firmware-bundle", json.dumps({"images": [good]}),
                                       {"Content-Type": "application/json"})
        self.assertEqual(status, 200, data)
        self.assertTrue(old.closed)

    def test_key_release_cancels_an_older_press_over_http(self):
        generation = self.session.state()["key_generations"]["1"]
        for pressed in (False, True):
            status, data, _ = self.request("POST", "/api/key", json.dumps(
                {"key": "1", "pressed": pressed, "generation": generation}),
                {"Content-Type": "application/json"})
            self.assertEqual(status, 200, data)
            self.assertEqual(json.loads(data)["generation"], generation + 1)
        self.assertEqual(self.session.keys, set())
        for generation in (True, -1, "1", 1.5):
            status, _, _ = self.request("POST", "/api/key", json.dumps(
                {"key": "1", "pressed": True, "generation": generation}),
                {"Content-Type": "application/json"})
            self.assertEqual(status, 400)

    def key_request(self, client_id, sequence, pressed, epoch=None):
        status, data, _ = self.request("POST", "/api/key", json.dumps({
            "key": "1", "pressed": pressed, "client_id": client_id, "sequence": sequence,
            "epoch": self.session.key_epoch if epoch is None else epoch,
        }), {"Content-Type": "application/json"})
        self.assertEqual(status, 200, data)
        return json.loads(data)

    def test_two_http_clients_share_ownership_and_pagehide_only_releases_its_owner(self):
        self.session.engines["bc5"] = self.session.engines["avr"]
        self.session.engines["bc5"].request = Mock(return_value={"values": [1, 2]})
        self.session.ui_initialized = True
        self.session._idle = Mock()
        self.session._call = Mock()
        barrier = threading.Barrier(2)

        def press(client):
            barrier.wait(timeout=2)
            return self.key_request(client, 1, True)

        with ThreadPoolExecutor(max_workers=2) as clients:
            results = list(clients.map(press, ("tab-a", "tab-b")))
        self.assertEqual(sum(result["delivered"] for result in results), 1)
        # Pagehide sends a newer release even while the original response may be pending.
        self.assertFalse(self.key_request("tab-a", 3, False)["delivered"])
        self.key_request("tab-a", 2, True)
        self.assertEqual(self.session.keys, {"1"})
        self.assertTrue(self.key_request("tab-b", 2, False)["delivered"])
        self.assertEqual(self.session.keys, set())
        self.assertTrue(self.key_request("fresh-tab", 1, True)["delivered"])
        self.assertTrue(self.key_request("fresh-tab", 2, False)["delivered"])
        self.assertEqual([call.kwargs["ah"] for call in self.session._call.call_args_list], [1, 4, 1, 4])

    def test_http_release_before_delayed_press_and_reset_epoch(self):
        epoch = self.session.key_epoch
        self.key_request("tab-a", 2, False)
        self.key_request("tab-a", 1, True)
        self.assertEqual(self.session.keys, set())
        self.key_request("tab-b", 1, True)
        self.key_request("tab-a", 3, True)
        status, data, _ = self.request("POST", "/api/control", '{"action":"reset"}',
                                       {"Content-Type": "application/json"})
        self.assertEqual(status, 200, data)
        self.assertEqual(json.loads(data)["key_epoch"], epoch + 1)
        self.key_request("tab-a", 4, True, epoch)
        self.assertEqual(self.session.keys, set())
        self.key_request("tab-b", 2, True)
        self.key_request("tab-b", 3, False, epoch)
        self.assertEqual(self.session.keys, {"1"})
        status, data, _ = self.request("GET", "/api/state")
        self.assertEqual(status, 200, data)
        self.assertEqual(json.loads(data)["key_epoch"], epoch + 1)

    def test_browser_key_request_bounds_and_client_capacity(self):
        valid = {"key": "1", "pressed": True, "client_id": "tab", "sequence": 1, "epoch": 0}
        for invalid in ({"client_id": ""}, {"client_id": "a" * 65}, {"client_id": "ü"},
                        {"client_id": "bad id"}, {"client_id": []}, {"sequence": True},
                        {"sequence": 0}, {"sequence": 2**53}, {"sequence": 1.5},
                        {"sequence": None}, {"epoch": -1}, {"epoch": True},
                        {"epoch": 2**53}, {"epoch": None}, {"generation": 0}):
            with self.subTest(invalid=invalid):
                status, data, _ = self.request("POST", "/api/key", json.dumps(valid | invalid),
                                               {"Content-Type": "application/json"})
                self.assertEqual(status, 400, data)
        for session_id in ("", "a" * 31, "A" * 32, [], True, 1):
            with self.subTest(session_id=session_id):
                status, data, _ = self.request("POST", "/api/key", json.dumps(valid | {"session_id": session_id}),
                                               {"Content-Type": "application/json"})
                self.assertEqual(status, 400, data)
        for client in range(128):
            self.key_request(f"tab-{client}", 2, False)
        status, data, _ = self.request("POST", "/api/key", json.dumps(valid),
                                       {"Content-Type": "application/json"})
        self.assertEqual(status, 400, data)
        self.assertIn("128", json.loads(data)["error"])
        self.assertEqual(self.session.keys, set())

    def test_browser_key_session_rejects_old_instance_events_with_the_same_epoch(self):
        status, data, _ = self.request("GET", "/api/state")
        self.assertEqual(status, 200, data)
        state = json.loads(data)
        event = {"key": "1", "pressed": True, "client_id": "tab", "sequence": 1,
                 "epoch": state["key_epoch"], "session_id": state["session_id"]}

        def send(changes):
            status, data, _ = self.request("POST", "/api/key", json.dumps(event | changes),
                                           {"Content-Type": "application/json"})
            self.assertEqual(status, 200, data)
            result = json.loads(data)
            self.assertEqual(result["session_id"], state["session_id"])
            return result

        send({})
        stale = send({"pressed": False, "sequence": 99, "session_id": "0" * 32})
        self.assertIn("Stale key session", stale["message"])
        self.assertEqual(self.session.keys, {"1"})
        send({"pressed": False, "sequence": 2})
        self.assertEqual(self.session.keys, set())
        for session_id in ("", "g" * 32, 1, []):
            status, _, _ = self.request("POST", "/api/key", json.dumps(event | {"session_id": session_id}),
                                       {"Content-Type": "application/json"})
            self.assertEqual(status, 400)
        status, data, _ = self.request("POST", "/api/control", '{"action":"reset"}',
                                       {"Content-Type": "application/json"})
        self.assertEqual(status, 200, data)
        self.assertEqual(json.loads(data)["session_id"], state["session_id"])

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
        self.assertEqual(json.loads(data)["session_id"], self.session.session_id)
        self.assertEqual(self.session.engines["avr"].data, patch)
        status, _, headers = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])

    def test_upload_switches_handset_and_shared_modem_inherits_it(self):
        status, data, _ = self.request("POST", "/api/firmware", bytes(0x36BB22),
                                       {"X-Filename": "bc5_main.bin"})
        self.assertEqual(status, 200, data)
        self.assertEqual(json.loads(data)["firmware"]["model"], "9575")
        status, data, _ = self.request("POST", "/api/firmware", bytes(0x260760),
                                       {"X-Filename": "trx_seg1_0x10000.bin"})
        self.assertEqual(status, 200, data)
        self.assertEqual(json.loads(data)["firmware"]["model"], "9575")
        status, data, _ = self.request("GET", "/api/state")
        state = json.loads(data)
        self.assertEqual(state["handset"]["model"], "9575")
        self.assertIn("sos", state["handset"]["keys"])
        self.assertEqual({image["model"] for image in state["images"]}, {"9575"})
        self.assertEqual(arguments(["--model", "9575"]).firmware,
                         Path(__file__).resolve().parent.parent / "firmware/9575")


if __name__ == "__main__":
    unittest.main()
