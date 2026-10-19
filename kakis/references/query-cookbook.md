# Kakis memory query cookbook (v1)

Endpoint: a private-network OpenSearch cluster (no auth). Read via aliases only.
All queries below are copy-pasteable. Replace `...` with values from earlier results.
Set the base URL once per shell (from `AIOS_OPENSEARCH`, or set it in `~/.hermes/.env`):
OS="${AIOS_OPENSEARCH:-http://<your-opensearch>:9200}"

## Discover the schema

```bash
curl -s '$OS/kakis_meta/_search' -H 'Content-Type: application/json' \
  -d '{"query":{"term":{"name":"schema"}},"_source":["body"]}'
```
The `body` field is the full JSON schema (doc shapes, enums, doc-id conventions,
content policy). The OpenSearch meta doc is the AUTHORITATIVE schema — if the
kakis_memory skill disagrees with it, the meta doc wins.

## Runs

List runs, most recently updated first:
```bash
curl -s '$OS/kakis_runs/_search' -H 'Content-Type: application/json' \
  -d '{"size":20,"sort":[{"updated_at":"desc"}]}'
```

Find runs about a topic (full-text over goal):
```bash
curl -s '$OS/kakis_runs/_search' -H 'Content-Type: application/json' \
  -d '{"query":{"match":{"goal":"mobile keyboard"}}}'
```

Runs by outcome / phase:
```bash
curl -s '$OS/kakis_runs/_search' -H 'Content-Type: application/json' \
  -d '{"query":{"bool":{"must":[{"term":{"status":"completed"}},{"terms":{"feasibility_verdict":["GO","RISKY"]}}]}}'
```

Fetch one run doc:
```bash
curl -s '$OS/kakis_runs/_doc/<run_id>'
```

## Artifacts

All artifacts for one run:
```bash
curl -s '$OS/kakis_artifacts/_search' -H 'Content-Type: application/json' \
  -d '{"query":{"term":{"run_id":"<run_id>"}},"size":200,"sort":[{"path":"asc"}]}'
```

Fetch one artifact's content (e.g. the final plan):
```bash
curl -s '$OS/kakis_artifacts/_search' -H 'Content-Type: application/json' \
  -d '{"query":{"term":{"path":"final_plan.txt"}},"_source":["content","size_bytes","mtime"]}'
```

Search inside artifact text across all runs (e.g. "what did we decide about visualViewport"):
```bash
curl -s '$OS/kakis_artifacts/_search' -H 'Content-Type: application/json' \
  -d '{"query":{"multi_match":{"query":"visualViewport","fields":["content","head"],"type":"best_fields"}},"size":10,"_source":["run_id","path","head"]}'
```

Only metadata, no content (large result sets):
```bash
curl -s '$OS/kakis_artifacts/_search' -H 'Content-Type: application/json' \
  -d '{"query":{"term":{"kind":"execution_report"}},"size":100,"_source":["run_id","path","size_bytes","mtime","head"]}'
```

## Calls (sub-module invocation traces)

Full call trace for a run, in order:
```bash
curl -s '$OS/kakis_calls/_search' -H 'Content-Type: application/json' \
  -d '{"query":{"term":{"run_id":"<run_id>"}},"sort":[{"seq":"asc"}],"size":300}'
```

Dory iteration history for a run:
```bash
curl -s '$OS/kakis_calls/_search' -H 'Content-Type: application/json' \
  -d '{"query":{"bool":{"must":[{"term":{"run_id":"<run_id>"}},{"terms":{"module":["dory_planner","dory_reviewer"]}}]}},"sort":[{"seq":"asc"}],"size":100}'
```

Bob harness outcomes for a run:
```bash
curl -s '$OS/kakis_calls/_search' -H 'Content-Type: application/json' \
  -d '{"query":{"bool":{"must":[{"term":{"run_id":"<run_id>"}},{"term":{"module":"bob_harness"}}]}},"sort":[{"variant":"asc"}]}'
```

Every failed/timed-out call across all runs:
```bash
curl -s '$OS/kakis_calls/_search' -H 'Content-Type: application/json' \
  -d '{"query":{"terms":{"status":["failed","timeout"]}},"size":100}'
```

## Counts / health

```bash
curl -s '$OS/_cat/indices?h=index,docs.count,store.size'
curl -s '$OS/_cat/aliases?h=alias,index'
```
