"""Generate the plugin-embedded API catalog module from the extracted data.

Produces bridge_plugin/catalog.py: a compact, importable reference of every
BiliLearn Web API route plus its accepted request parameters, so the catgirl
can discover and drive any feature through the generic passthrough entry.

Usage: python tools/gen_catalog_module.py <api_catalog.json> <api_params.json> <out.py>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HEADER = '''"""BiliLearn Web API catalog (auto-generated -- do not edit by hand).

Source: bilibili_learning_bot/web_panel.py (BiliLearn __VERSION__).
Regenerate with: python tools/gen_catalog_module.py tools/api_catalog.json tools/api_params.json bridge_plugin/catalog.py

Each group maps to a list of routes:
    {"p": path, "m": [methods], "q": [accepted request params]}

Paths may contain Flask converters (<bvid>, <uid>, <path:keyword>, ...);
substitute real values before calling.
"""

BILILEARN_VERSION = "__VERSION__"

# group -> [{"p": path, "m": [methods], "q": [params]}]
GROUPS: dict[str, list[dict]] = __GROUPS__

# Flat path -> allowed methods, for validation without scanning GROUPS.
ROUTES: dict[str, list[str]] = __ROUTES__


def group_names() -> list[str]:
    """Return every API group name, most-populated first."""
    return sorted(GROUPS, key=lambda name: (-len(GROUPS[name]), name))


def routes_in(group: str) -> list[dict]:
    """Return the routes registered under one group (empty list if unknown)."""
    return list(GROUPS.get(group) or [])


def find(keyword: str) -> list[dict]:
    """Case-insensitive substring search over paths; returns matching routes."""
    needle = (keyword or "").strip().lower()
    if not needle:
        return []
    hits: list[dict] = []
    for group, items in GROUPS.items():
        for item in items:
            if needle in item["p"].lower() or needle in group.lower():
                hits.append({"group": group, **item})
    return hits
'''


def _dump_groups(groups: dict[str, list[dict]]) -> str:
    """One route per line: readable diffs, compact file."""
    lines = ["{"]
    for group in sorted(groups):
        lines.append(f'    "{group}": [')
        for item in groups[group]:
            lines.append(f"        {json.dumps(item, ensure_ascii=False, separators=(', ', ': '))},")
        lines.append("    ],")
    lines.append("}")
    return "\n".join(lines)


def _dump_routes(routes: dict[str, list[str]]) -> str:
    lines = ["{"]
    for path in sorted(routes):
        lines.append(f'    "{path}": {json.dumps(routes[path])},')
    lines.append("}")
    return "\n".join(lines)


def main() -> int:
    catalog = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    params = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    params_by_key = {(r["path"], r["endpoint"]): r for r in params}

    groups: dict[str, list[dict]] = {}
    routes: dict[str, list[str]] = {}
    for r in catalog["routes"]:
        path = r["path"]
        if not path.startswith("/api/"):
            continue
        info = params_by_key.get((path, r["endpoint"]))
        keys = sorted(set((info or {}).get("body_params", [])) | set((info or {}).get("query_params", [])))
        entry = {"p": path, "m": list(r["methods"])}
        if keys:
            entry["q"] = keys
        groups.setdefault(r["group"], []).append(entry)
        # A path can be registered by several handlers (e.g. separate PUT and
        # DELETE functions); merge so no method is lost.
        existing = routes.setdefault(path, [])
        for method in r["methods"]:
            if method not in existing:
                existing.append(method)

    for items in groups.values():
        items.sort(key=lambda e: e["p"])
    ordered_groups = {k: groups[k] for k in sorted(groups)}

    body = (
        HEADER
        .replace("__VERSION__", "3.1.6")
        .replace("__GROUPS__", _dump_groups(ordered_groups))
        .replace("__ROUTES__", _dump_routes(routes))
    )
    Path(sys.argv[3]).write_text(body, encoding="utf-8")
    total = sum(len(v) for v in groups.values())
    print(f"groups={len(groups)} routes={total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
