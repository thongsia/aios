#!/usr/bin/env python3
"""Create KAKIS OpenSearch memory indices and aliases. Idempotent.

Usage: kakis_indices.py [--opensearch URL]

Base URL: --opensearch, else AIOS_OPENSEARCH (process env or ~/.hermes/.env).
No built-in default; exits 4 when unset.

Creates (if absent):
  kakis_runs_v1      -> alias kakis_runs       (one doc per run)
  kakis_artifacts_v1 -> alias kakis_artifacts  (one doc per file artifact)
  kakis_calls_v1     -> alias kakis_calls      (one doc per sub-module invocation)
  kakis_meta_v1      -> alias kakis_meta       (schema + query cookbook docs)
"""
import json
import os
import sys
import urllib.error
import urllib.request

def opensearch_base() -> str | None:
    """OpenSearch base URL: AIOS_OPENSEARCH from the process env or ~/.hermes/.env, else None (not configured)."""
    v = os.environ.get("AIOS_OPENSEARCH")
    if v:
        return v
    env_file = os.path.expanduser("~/.hermes/.env")
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    k, _, val = line.partition("=")
                    if val.startswith('"') and val.endswith('"'):
                        val = val[1:-1]
                    if k == "AIOS_OPENSEARCH" and val.strip():
                        return val.strip()
    return None


DEFAULT_OS = opensearch_base()

INDICES = {
    "kakis_runs_v1": {
        "settings": {"number_of_shards": 1, "number_of_replicas": 0},
        "mappings": {
            "properties": {
                "run_id": {"type": "keyword"},
                "slug": {"type": "keyword"},
                "goal": {"type": "text", "fields": {"kw": {"type": "keyword"}}},
                "phase": {"type": "keyword"},
                "status": {"type": "keyword"},
                "feasibility_verdict": {"type": "keyword"},
                "gates": {
                    "properties": {
                        "gate0": {
                            "properties": {
                                "decision": {"type": "keyword"},
                                "decided_at": {"type": "date"},
                                "scope_note": {"type": "text"},
                                "auto_proceeded": {"type": "boolean"},
                            }
                        },
                        "gate1": {
                            "properties": {
                                "decision": {"type": "keyword"},
                                "decided_at": {"type": "date"},
                                "scope_note": {"type": "text"},
                                "auto_proceeded": {"type": "boolean"},
                            }
                        },
                        "gate2": {
                            "properties": {
                                "decision": {"type": "keyword"},
                                "decided_at": {"type": "date"},
                                "scope_note": {"type": "text"},
                                "auto_proceeded": {"type": "boolean"},
                            }
                        },
                    }
                },
                "created_at": {"type": "date"},
                "updated_at": {"type": "date"},
                "dory_iterations": {"type": "integer"},
                "bob_harness_count": {"type": "integer"},
                "bob_best_harness": {"type": "keyword"},
                "bob_best_score": {"type": "float"},
                "completed_steps": {"type": "integer"},
                "total_steps": {"type": "integer"},
                "run_workspace": {"type": "keyword"},
                "dory_workspace": {"type": "keyword"},
                "bob_workspace": {"type": "keyword"},
                "artifact_count": {"type": "integer"},
                "call_count": {"type": "integer"},
                "error_summary": {"type": "text"},
            }
        },
    },
    "kakis_artifacts_v1": {
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
            "index.mapping.total_fields.limit": 100,
        },
        "mappings": {
            "properties": {
                "run_id": {"type": "keyword"},
                "path": {"type": "keyword"},
                "original_path": {"type": "keyword"},
                "kind": {"type": "keyword"},
                "phase": {"type": "keyword"},
                "module": {"type": "keyword"},
                "size_bytes": {"type": "long"},
                "sha256": {"type": "keyword"},
                "mtime": {"type": "date"},
                "content": {"type": "text"},
                "head": {"type": "text"},
            }
        },
    },
    "kakis_calls_v1": {
        "settings": {"number_of_shards": 1, "number_of_replicas": 0},
        "mappings": {
            "properties": {
                "run_id": {"type": "keyword"},
                "seq": {"type": "integer"},
                "module": {"type": "keyword"},
                "variant": {"type": "keyword"},
                "iteration": {"type": "integer"},
                "input_refs": {"type": "keyword"},
                "output_refs": {"type": "keyword"},
                "status": {"type": "keyword"},
                "goal": {"type": "text"},
                "result_summary": {"type": "text"},
                "notes": {"type": "text"},
                "started_at": {"type": "date"},
                "ended_at": {"type": "date"},
            }
        },
    },
    "kakis_meta_v1": {
        "settings": {"number_of_shards": 1, "number_of_replicas": 0},
        "mappings": {
            "properties": {
                "name": {"type": "keyword"},
                "schema_version": {"type": "keyword"},
                "updated_at": {"type": "date"},
                "body": {"type": "text"},
            }
        },
    },
}

ALIASES = {
    "kakis_runs_v1": "kakis_runs",
    "kakis_artifacts_v1": "kakis_artifacts",
    "kakis_calls_v1": "kakis_calls",
    "kakis_meta_v1": "kakis_meta",
}


def req(base, method, path, body=None):
    url = base.rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:
            return e.code, {}
    except Exception as e:
        print(f"ERROR: {method} {path}: {e}", file=sys.stderr)
        return 0, {"error": str(e)}


def ensure_index(base, name):
    status, _ = req(base, "HEAD", "/" + name)
    if status == 200:
        print(f"exists  {name}")
        return True
    if status != 404:
        print(f"ERROR: cannot determine state of {name} (HTTP {status})", file=sys.stderr)
        return False
    status, body = req(base, "PUT", "/" + name, INDICES[name])
    if status in (200, 201):
        print(f"created {name}")
        return True
    print(f"ERROR: create {name}: HTTP {status} {body}", file=sys.stderr)
    return False


def ensure_alias(base, index, alias):
    status, body = req(base, "GET", "/" + index + "/_alias/" + alias)
    if status == 200 and alias in body:
        print(f"alias   {alias} -> {index} (already present)")
        return True
    status, body = req(
        base, "POST", "/_aliases", {"actions": [{"add": {"index": index, "alias": alias}}]}
    )
    if status in (200, 201) and not body.get("errors"):
        print(f"alias   {alias} -> {index}")
        return True
    print(f"ERROR: alias {alias} -> {index}: HTTP {status} {body}", file=sys.stderr)
    return False


def main():
    base = DEFAULT_OS
    if "--opensearch" in sys.argv:
        base = sys.argv[sys.argv.index("--opensearch") + 1]
    if base is None:
        print("ERROR: OpenSearch not configured. Set AIOS_OPENSEARCH (process env or ~/.hermes/.env) or pass --opensearch.", file=sys.stderr)
        return 4
    status, body = req(base, "GET", "/")
    if status != 200:
        print(f"ERROR: OpenSearch unreachable at {base} (HTTP {status})", file=sys.stderr)
        return 2
    version = body.get("version", {}) if isinstance(body, dict) else {}
    number = version.get("number", "?") if isinstance(version, dict) else "?"
    print(f"OpenSearch {number} at {base}")
    ok = True
    for name in INDICES:
        ok = ensure_index(base, name) and ok
    for index, alias in ALIASES.items():
        ok = ensure_alias(base, index, alias) and ok
    # refresh so the (empty) indices are immediately visible to _cat
    req(base, "POST", "/kakis_runs,kakis_artifacts,kakis_calls,kakis_meta/refresh")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
