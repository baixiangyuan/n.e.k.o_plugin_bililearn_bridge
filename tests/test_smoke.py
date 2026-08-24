"""Smoke test for the BiliLearn bridge N.E.K.O plugin.

Validates plugin.toml schema without importing the plugin runtime, so the
test stays green even before the full N.E.K.O SDK environment is available.
"""

import tomllib
from pathlib import Path

PLUGIN_TOML = Path(__file__).resolve().parent.parent / "plugin.toml"
ENTRY_MODULE = Path(__file__).resolve().parent.parent / "bililearn_bridge.py"


def test_plugin_toml_present():
    assert PLUGIN_TOML.is_file(), "plugin.toml must exist at the repo root"


def test_plugin_id_and_entry():
    data = tomllib.load(PLUGIN_TOML.open("rb"))
    plugin = data["plugin"]
    assert plugin["id"] == "bililearn_bridge"
    assert plugin["entry"] == "bililearn_bridge:BiliLearnBridgePlugin"
    assert plugin["type"] == "plugin"


def test_entry_module_exists():
    assert ENTRY_MODULE.is_file(), "bililearn_bridge.py (entry module) must exist at the repo root"
