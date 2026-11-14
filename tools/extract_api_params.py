"""Extract, per route, the request parameters the handler reads.

Gives an accurate calling reference for the bridge's generic passthrough
entry and for the LLM-facing catalog.

Usage: python tools/extract_api_params.py <web_panel.py> <out.json>
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path


# app.route(...) extraction (mirrors extract_api_catalog.py)
def _lit(node):
    try:
        return ast.literal_eval(node)
    except Exception:
        return None


def _route(dec):
    if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
        return None
    if not (isinstance(dec.func.value, ast.Name) and dec.func.value.id == "app"):
        return None
    name = dec.func.attr
    if not dec.args:
        return None
    path = _lit(dec.args[0])
    if not isinstance(path, str):
        return None
    if name == "route":
        methods = ["GET"]
        for kw in dec.keywords:
            if kw.arg == "methods":
                methods = _lit(kw.value) or ["GET"]
        return path, [str(m).upper() for m in methods]
    if name in ("get", "post", "put", "delete", "patch"):
        return path, [name.upper()]
    return None


def _dotted(node) -> str:
    """Render attribute chains like request.args.get -> 'request.args.get'."""
    parts = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    return ".".join(reversed(parts))


def _params(fn: ast.AST) -> dict:
    body_keys: set[str] = set()
    query_keys: set[str] = set()
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        callee = _dotted(node.func)
        # body = request.get_json(...) -> body.get("key")
        # jsonify only in responses; ignore
        if callee.endswith(".get") and node.args:
            key = _lit(node.args[0])
            if not isinstance(key, str):
                continue
            root = _dotted(node.func).rsplit(".", 1)[0]
            if root == "request.args":
                query_keys.add(key)
            elif root in {"data", "body", "payload", "req", "params", "cfg_data"}:
                body_keys.add(key)
            elif root == "request":
                query_keys.add(key)
    return {"body": sorted(body_keys), "query": sorted(query_keys)}


def main() -> int:
    src = Path(sys.argv[1]).read_text(encoding="utf-8-sig")
    tree = ast.parse(src)
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            hit = _route(dec)
            if not hit:
                continue
            path, methods = hit
            if not path.startswith("/api/"):
                continue
            p = _params(node)
            out.append({
                "path": path,
                "methods": methods,
                "endpoint": node.name,
                "line": node.lineno,
                "body_params": p["body"],
                "query_params": p["query"],
            })
    out.sort(key=lambda r: (r["path"], r["methods"]))
    Path(sys.argv[2]).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"routes={len(out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
