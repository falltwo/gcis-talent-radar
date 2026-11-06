# Issue 38 site data refresh implementation plan

> **For agentic workers:** Use executing-plans to implement the following tasks sequentially, with regression tests before production changes.

**Goal:** Complete Issue #38's first three acceptance items: complete GCIS month coverage, reproducible district stats, scheduled regeneration of all site data.

**Architecture:** Build the three frontend JSON artifacts from local source snapshots. Validate inputs and calculate all three artifacts before publishing. Add an offline-only site-data step to the existing daily refresh, preserving the scheduler lock and per-step failure report.

**Tech stack:** Python 3.12, CSV/JSON, pytest, existing daily refresh.

**Spec:** https://github.com/falltwo/gcis-talent-radar/issues/38

## Constraints
- No new API/model calls, paid services or fabricated values.
- Keep suppressed factory values as null. Select one latest job snapshot, deduplicate postings, reject cross-district observations, and disclose missing/raw capped coverage.
- Document the distinct job-family rules used by the map and talent report. Neither rule proves the employer is in manufacturing.
- Preserve the previous three JSON artifacts if a build fails.
- Missing GCIS months must remain explicit; a partial month is not a zero month.
- District office coordinates, vocational schools, business-stock exit rates and district job seekers/pay remain follow-up items, not completion claims.

## Tasks
- [x] Add failing tests for latest-year factory data, suppression, latest snapshot/deduplication/location handling, query caps and missing inputs.
- [x] Implement a district-stats builder with source and filtering metadata; reuse validated job observations in talent builder.
- [x] Test and implement GCIS 12-month coverage with the already-delivered 2025-08/09 files, preserving missing-month disclosure.
- [x] Test and implement offline batch rebuild and fail-before-publish behavior.
- [x] Connect the batch rebuild to daily_refresh's default steps; test order and failure logging with network-free fixtures.
- [x] Rebuild the three real JSON files, document reproducibility, limitations and remaining Issue #38 backlog.
- [x] Run the complete Python/frontend suites in a clean copy; report results without pushing or closing the issue unless requested.

## Verification ledger

- Ruling: implement Issue #38 first-three acceptance criteria; leave the four data-acquisition follow-ups explicitly documented.
- Ruling: preserve existing distinct map/report job-family rules; share latest-snapshot, location and audit handling.
- Red/green: 13 source validation, scheduler ordering and safe publication cases.
- Real offline scheduler entry regenerated all three JSONs with GCIS 2025-10–2026-09, no missing months, job snapshot 2026-10-05 and academic year 113. Repeated build SHA-256 values match.
- Read-only reviewer found two P2 validation gaps; fixed and rechecked with 13 passing tests, no remaining blockers.
