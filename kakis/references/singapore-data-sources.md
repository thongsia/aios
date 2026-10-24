# Singapore public data — verified access paths

Distilled from production runs of Singapore COE / vehicle-policy analyses.
Sources are LIVE and update — re-verify row counts and last-month coverage at
run time before citing them (facts below were checked during the COE
categorisation study run).

## data.gov.sg datastore API

- Working public endpoint: `https://data.gov.sg/api/action/datastore_search`
  (no `/v1/` or `/v3/` prefix). The versioned paths answer with an
  authentication error or HTML — that is a wrong path, not a dead source.
- No auth for the public resources below.
- Pagination: `offset` works, `start` is silently ignored, and one giant
  fetch (e.g. limit=100000) returns HTTP 413. Page at limit ≤ 20000;
  limit=500 is fine for probes.

## Known resources (vehicle / COE policy)

| Resource | Resource id | Characteristics |
|---|---|---|
| COE results (per-bidding) | d_69b3380ad7e51aff3a7dcc84eba52b8a | Fields: month, bidding_no, vehicle_class (A–E), quota, bids_success, bids_received, premium. ~1,990 rows, 2010 → 2026-10 at last check. Per-bidding rows are REQUIRED to see A/B price inversions — monthly aggregates hide them. |
| Vehicle registrations | d_d3f4d708e1d0a37b4365414e2fad3a07 | Fields: month, make, importer_type, fuel_type, vehicle_type, number. Make-level only (no model granularity). Was FROZEN at 2025-05 (51,669 rows) at last check — verify whether it has since updated before relying on the freeze; some rows carry null `number` (count and exclude consistently). |
| CPI All Items | d_bdaff844e3ef89d39fceb962ff8f0791 | Monthly; optional context for real-terms exhibits. |

## LTA sources

- Consultation papers / government releases: lta.gov.sg newsroom; linked PDFs
  usually live on file.go.gov.sg or go.gov.sg. Annex pages may be image-only
  (no text layer): extract with pymupdf when a text layer exists, else OCR —
  `pip install easyocr` is a dependency-free path that handles scanned tables
  when the vision backend is unavailable.
- Per-model car data (authoritative for COE class, average OMV, fuel, ARF,
  COE price): LTA monthly "Cost for Cars Registered" PDFs (M032 series) on
  onemotoring.lta.gov.sg. The onemotoring OMV query page may serve no data
  elements at all — use the PDFs instead.
- Registration / OMV annual statistics: lta.gov.sg statistics page (annual
  cost PDFs, "Average OMV of New Cars Registered") — the fallback for
  full-year registration mix when the datastore is frozen.
