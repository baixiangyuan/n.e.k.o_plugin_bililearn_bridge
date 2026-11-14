"""Extract every @app.route from BiliLearn's web_panel.py into a JSON catalog.

Usage: python tools/extract_api_catalog.py <web_panel.py> <out.json>
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path


def _literal(node):
    try:
        return ast.literal_eval(node)
    except Exception:
        return None


def _route_from_decorator(dec: ast.AST):
    """Return (path, methods) for an @app.route(...) decorator, else None."""
    if not isinstance(dec, ast.Call):
        return None
    func = dec.func
    # app.route / app.get / app.post ...
    if not isinstance(func, ast.Attribute):
        return None
    if not (isinstance(func.value, ast.Name) and func.value.id == "app"):
        return None
    name = func.attr
    if name == "route":
        if not dec.args:
            return None
        path = _literal(dec.args[0])
        methods = ["GET"]
        for kw in dec.keywords:
            if kw.arg == "methods":
                methods = _literal(kw.value) or ["GET"]
        if not isinstance(path, str):
            return None
        return path, [str(m).upper() for m in methods]
    if name in ("get", "post", "put", "delete", "patch"):
        if not dec.args:
            return None
        path = _literal(dec.args[0])
        if not isinstance(path, str):
            return None
        return path, [name.upper()]
    return None


def main() -> int:
    src = Path(sys.argv[1]).read_text(encoding="utf-8-sig")
    tree = ast.parse(src)
    rows = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            hit = _route_from_decorator(dec)
            if not hit:
                continue
            path, methods = hit
            rows.append({
                "path": path,
                "methods": methods,
                "endpoint": node.name,
                "line": node.lineno,
            })
    # de-dup by (path, methods, endpoint)
    seen = set()
    uniq = []
    for r in rows:
        key = (r["path"], tuple(r["methods"]), r["endpoint"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    uniq.sort(key=lambda r: (r["path"], r["methods"]))

    # classify
    def classify(p: str) -> str:
        if not p.startswith("/api/"):
            return "page"
        parts = p[len("/api/"):].split("/")
        return parts[0] or "root"

    for r in uniq:
        r["group"] = classify(r["path"])

    groups = {}
    for r in uniq:
        groups.setdefault(r["group"], []).append(r)

    out = {
        "total": len(uniq),
        "api_total": sum(1 for r in uniq if r["path"].startswith("/api/")),
        "groups": {k: len(v) for k, v in sorted(groups.items(), key=lambda kv: -len(kv[1]))},
        "routes": uniq,
    }
    Path(sys.argv[2]).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"total={out['total']} api={out['api_total']} groups={len(groups)}")
    for k, v in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        print(f"  {k}: {len(v)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
