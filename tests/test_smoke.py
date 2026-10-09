"""Tests for the BiliLearn bridge N.E.K.O plugin.

Runs green under both `unittest` and `pytest`, with or without the N.E.K.O SDK
present: SDK-dependent checks skip instead of failing, and every other check
is offline (the auth handshake runs against a local stub panel).
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

PLUGIN_DIR = Path(__file__).resolve().parent.parent
PLUGIN_TOML = PLUGIN_DIR / "plugin.toml"
ENTRY_MODULE = PLUGIN_DIR / "__init__.py"


def _load(name: str, filename: str):
    """Load a plugin submodule by path, without importing the package root."""
    spec = importlib.util.spec_from_file_location(name, PLUGIN_DIR / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class TestPluginManifest(unittest.TestCase):
    def test_plugin_toml_present(self):
        self.assertTrue(PLUGIN_TOML.is_file(), "plugin.toml must exist at the repo root")

    def test_plugin_identity(self):
        import tomllib

        with PLUGIN_TOML.open("rb") as fh:
            data = tomllib.load(fh)
        plugin = data["plugin"]
        self.assertEqual(plugin["id"], "bililearn_bridge")
        self.assertEqual(plugin["entry"], "plugin.plugins.bililearn_bridge:BiliLearnBridgePlugin")
        self.assertEqual(plugin["type"], "plugin")
        self.assertRegex(plugin["version"], r"^\d+\.\d+\.\d+")
        self.assertIn("sdk", plugin)

    def test_entry_module_defines_class(self):
        self.assertTrue(ENTRY_MODULE.is_file(), "__init__.py must exist at the repo root")
        tree = ast.parse(ENTRY_MODULE.read_text(encoding="utf-8"))
        classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
        self.assertIn("BiliLearnBridgePlugin", classes)
        decorators = {
            node.attr if isinstance(node, ast.Attribute) else getattr(node, "id", "")
            for node in classes["BiliLearnBridgePlugin"].decorator_list
        }
        self.assertIn("neko_plugin", decorators)


class TestEntryBudget(unittest.TestCase):
    """Keep the host-facing entry list small (full coverage lives in api_call)."""

    MAX_ENTRIES = 50

    def _entry_ids(self):
        ids = []
        for filename in ("__init__.py", "director.py"):
            tree = ast.parse((PLUGIN_DIR / filename).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for decorator in node.decorator_list:
                    if not isinstance(decorator, ast.Call):
                        continue
                    func = decorator.func
                    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
                    if name != "plugin_entry":
                        continue
                    entry_id = node.name
                    for keyword in decorator.keywords:
                        if keyword.arg == "id" and isinstance(keyword.value, ast.Constant):
                            entry_id = str(keyword.value.value)
                    ids.append(entry_id)
        return ids

    def test_entry_count_within_budget(self):
        ids = self._entry_ids()
        self.assertGreater(len(ids), 0)
        self.assertLessEqual(
            len(ids),
            self.MAX_ENTRIES,
            f"entry count {len(ids)} exceeds budget {self.MAX_ENTRIES}: {sorted(ids)}",
        )

    def test_entry_ids_unique(self):
        ids = self._entry_ids()
        self.assertEqual(len(ids), len(set(ids)), f"duplicate entry ids: {sorted(ids)}")

    def test_generic_passthrough_still_reaches_everything(self):
        ids = set(self._entry_ids())
        for required in ("api_call", "api_batch", "api_groups", "api_search", "api_describe"):
            self.assertIn(required, ids, "generic passthrough entries must stay available")


class TestCatalog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = _load("bridge_catalog_under_test", "catalog.py")

    def test_route_counts(self):
        # BiliLearn 3.1.6 exposes 308 route handlers across 90 groups. A few
        # paths are registered by several handlers (e.g. PUT + DELETE on
        # /api/diary/entry/<id>), so ROUTES holds the deduplicated path set.
        registered = sum(len(items) for items in self.catalog.GROUPS.values())
        self.assertEqual(registered, 308)
        self.assertEqual(len(self.catalog.GROUPS), 90)
        self.assertLessEqual(len(self.catalog.ROUTES), registered)
        for items in self.catalog.GROUPS.values():
            for item in items:
                self.assertIn(item["p"], self.catalog.ROUTES)

    def test_versions_and_key_routes(self):
        self.assertEqual(self.catalog.BILILEARN_VERSION, "3.1.6")
        for path in ("/api/bot/start", "/api/info", "/api/kb/tutor-chat", "/api/agent/start"):
            self.assertIn(path, self.catalog.ROUTES)

    def test_find_is_case_insensitive(self):
        hits = self.catalog.find("BOT")
        paths = {item["p"] for item in hits}
        self.assertIn("/api/bot/start", paths)

    def test_routes_in_unknown_group_is_empty(self):
        self.assertEqual(self.catalog.routes_in("nope"), [])

    def test_parameter_documentation(self):
        bot = {item["p"]: item for item in self.catalog.routes_in("bot")}
        self.assertIn("mode", bot["/api/bot/start"]["q"])


class _StubPanel(BaseHTTPRequestHandler):
    """Minimal stand-in for the BiliLearn panel's auth-gated surface."""

    users = {"yaya": "yaya"}
    seen_requests: list[tuple[str, str]] = []

    def log_message(self, *args):  # silence test output
        pass

    def _send(self, status: int, payload: dict, *, cookie: str = ""):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authed(self) -> bool:
        return "bililearn_session=ok" in (self.headers.get("Cookie") or "")

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except ValueError:
            return {}

    def do_GET(self):  # noqa: N802 - http.server contract
        path = urlparse(self.path).path
        type(self).seen_requests.append(("GET", path))
        if path == "/api/health":
            self._send(200, {"ok": True, "service": "bilibili-learning-bot-web"})
        elif path == "/api/auth/status":
            self._send(200, {"authenticated": self._authed()})
        elif path == "/api/info":
            if self._authed():
                self._send(200, {"ok": True, "version": "3.1.6", "bot_running": True})
            else:
                self._send(401, {"ok": False, "message": "登录状态已失效，请重新登录", "auth_required": True})
        else:
            self._send(404, {"ok": False, "message": "not found"})

    def do_POST(self):  # noqa: N802 - http.server contract
        path = urlparse(self.path).path
        type(self).seen_requests.append(("POST", path))
        body = self._read_body()
        if path == "/api/disclaimer/confirm":
            self._send(200, {"ok": True})
        elif path == "/api/auth/login":
            user, password = body.get("username"), body.get("password")
            if type(self).users.get(user) == password:
                self._send(200, {"ok": True, "message": "登录成功"}, cookie="bililearn_session=ok; Path=/")
            else:
                self._send(200, {"ok": False, "message": "用户名或密码错误"})
        elif path == "/api/auth/setup":
            type(self).users[body.get("username", "")] = body.get("password", "")
            self._send(200, {"ok": True, "message": "设置成功"}, cookie="bililearn_session=ok; Path=/")
        else:
            self._send(404, {"ok": False, "message": "not found"})


class TestClientHandshake(unittest.TestCase):
    """End-to-end auth: disclaimer -> login -> gated call, against a stub panel."""

    @classmethod
    def setUpClass(cls):
        cls.client_mod = _load("bridge_client_under_test", "client.py")
        _StubPanel.seen_requests = []
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _StubPanel)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _client(self, **kwargs):
        return self.client_mod.BiliLearnClient(port=self.port, timeout=5.0, **kwargs)

    def test_health_identifies_panel(self):
        import asyncio

        client = self._client()
        self.assertTrue(asyncio.run(client.health()))

    def test_seeded_default_login_then_gated_call(self):
        import asyncio

        client = self._client()
        auth = asyncio.run(client.ensure_auth())
        self.assertTrue(auth["authenticated"], auth)
        self.assertEqual(auth["mode"], "seeded-default")

        res = asyncio.run(client.call("GET", "/api/info"))
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["data"]["version"], "3.1.6")

        # The handshake really walked disclaimer + login, in that order.
        seen = _StubPanel.seen_requests
        self.assertIn(("POST", "/api/disclaimer/confirm"), seen)
        self.assertIn(("POST", "/api/auth/login"), seen)

    def test_configured_credentials_win_and_are_used(self):
        import asyncio

        client = self._client(username="yaya", password="yaya")
        auth = asyncio.run(client.ensure_auth())
        self.assertTrue(auth["authenticated"], auth)
        self.assertEqual(auth["mode"], "config")

    def test_bad_credentials_fail_without_setup_overwrite(self):
        import asyncio

        client = self._client(username="yaya", password="wrong", auto_setup=False)
        auth = asyncio.run(client.ensure_auth())
        self.assertFalse(auth["authenticated"])
        self.assertEqual(auth["mode"], "failed")

    def test_expired_session_is_recovered_once(self):
        import asyncio

        client = self._client()
        self.assertTrue(asyncio.run(client.ensure_auth())["authenticated"])
        # Drop the session cookie behind the client's back, then call a gated route.
        client._jar.clear()  # noqa: SLF001 - exercising the 401-retry path
        res = asyncio.run(client.call("GET", "/api/info"))
        self.assertTrue(res["ok"], res)

    def test_rejects_unsafe_paths(self):
        import asyncio

        client = self._client()
        with self.assertRaises(self.client_mod.BiliLearnClientError):
            asyncio.run(client.request("GET", "http://evil.example/api/x"))
        with self.assertRaises(self.client_mod.BiliLearnClientError):
            asyncio.run(client.request("GET", "//evil.example/api/x"))

    def test_rejects_unsupported_methods(self):
        import asyncio

        client = self._client()
        with self.assertRaises(self.client_mod.BiliLearnClientError):
            asyncio.run(client.request("TRACE", "/api/info"))


class TestExeLookup(unittest.TestCase):
    def test_scan_finds_nested_exe(self):
        # Exercised through the plugin class when the SDK is importable.
        try:
            sys.path.insert(0, str(PLUGIN_DIR.parent))
            spec = importlib.util.spec_from_file_location("bridge_pkg_under_test", ENTRY_MODULE)
            assert spec and spec.loader
            module = importlib.util.module_from_spec(spec)
            sys.modules["bridge_pkg_under_test"] = module
            spec.loader.exec_module(module)
        except ImportError as exc:
            self.skipTest(f"N.E.K.O SDK unavailable: {exc}")

        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "BiliLearn Web"
            root.mkdir()
            exe = root / "BiliLearn Web.exe"
            exe.write_bytes(b"stub")
            found = module.BiliLearnBridgePlugin._find_exe_under(Path(tmp), 3)
            self.assertIsNotNone(found)
            self.assertEqual(Path(found).name, "BiliLearn Web.exe")


if __name__ == "__main__":
    unittest.main()