#!/usr/bin/env python3
"""Publish the KAKIS memory schema + query cookbook into the kakis_meta index.

Docs:
  schema/v1           full JSON schema (schema-v1.json content inline in `body`)
  query-cookbook/v1   copy-pasteable query recipes (markdown in `body`)
  index-map/v1        alias -> purpose -> doc-id conventions

Idempotent (fixed ids). Usage: kakis_publish_meta.py [--opensearch URL]
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_OS = os.environ.get("AIOS_OPENSEARCH", "http://<your-opensearch>:9200")
REFS = Path(__file__).resolve().parent.parent / "references"
SCHEMA_VERSION = "v1"

INDEX_MAP = {
    "aliases": {
        "kakis_runs": "one doc per KAKIS run (index card: goal, phase, gate decisions, workspaces)",
        "kakis_artifacts": "one doc per file artefact (run + dory/ + bob/ sub-workspaces; full text <= 512KiB)",
        "kakis_calls": "one doc per sub-module invocation (igor, dory iterations, bob harnesses, execution batches)",
        "kakis_meta": "this meta index: schema + query cookbook + index map",
    },
    "doc_ids": {
        "kakis_runs": "run_id",
        "kakis_artifacts": "sha256_hex(run_id + '|' + path)",
        "kakis_calls": "run_id + '|call|' + seq + '|' + module",
        "kakis_meta": "<name>/<schema_version> e.g. schema/v1",
    },
    "writer": "only kakis_export.py writes the data indices; all other agents are read-only",
}


def req(base, method, path, body=None):
    url = base.rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {"error": str(e)}


def main():
    base = DEFAULT_OS
    if "--opensearch" in sys.argv:
        base = sys.argv[sys.argv.index("--opensearch") + 1]
    status, body = req(base, "GET", "/")
    if status != 200:
        print(f"ERROR: OpenSearch unreachable at {base} (HTTP {status})", file=sys.stderr)
        return 2
    if status == 0:
        print(f"ERROR: {body}", file=sys.stderr)
        return 2

    now = datetime.now(timezone.utc).isoformat()
    schema_body = (REFS / "schema-v1.json").read_text()
    try:
        json.loads(schema_body)  # must be valid JSON before publishing
    except json.JSONDecodeError as e:
        print(f"ERROR: schema-v1.json is not valid JSON: {e}", file=sys.stderr)
        return 3
    cookbook_body = (REFS / "query-cookbook.md").read_text()

    docs = [
        (f"schema/{SCHEMA_VERSION}", {"name": "schema", "schema_version": SCHEMA_VERSION,
                                      "updated_at": now, "body": schema_body}),
        (f"query-cookbook/{SCHEMA_VERSION}", {"name": "query-cookbook", "schema_version": SCHEMA_VERSION,
                                              "updated_at": now, "body": cookbook_body}),
        (f"index-map/{SCHEMA_VERSION}", {"name": "index-map", "schema_version": SCHEMA_VERSION,
                                         "updated_at": now, "body": json.dumps(INDEX_MAP, indent=2)}),
    ]
    for doc_id, doc in docs:
        status, body = req(base, "PUT",
                           f"/kakis_meta/_doc/{urllib.parse.quote(doc_id, safe='')}?refresh=true", doc)
        if status not in (200, 201):
            print(f"ERROR: publish {doc_id}: HTTP {status} {body}", file=sys.stderr)
            return 3
        print(f"published {doc_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
