# Implementation estimate — Fieldprint Platform

What it would cost, in developer hours, to move this pipeline from demonstration
into production. Written September 2026 for the cotton funding conversation.

**Assumptions:** one software developer with roughly ten years of experience;
AWS; containerised workers; an API gateway already in place. No visibility into
the Fieldprint Platform's internals, which is why one line below is marked
*not estimable* rather than guessed at.

> **Revised 28 September 2026.** The CDL bulk-store work has since been built
> and validated, which retires what was the largest single risk here. The
> previous version of this document also quoted a total of 320–400 hours that
> did not reconcile with the sum of its own rows (232–324). The total below is
> now just the rows added up, with the integration allowance stated separately
> instead of buried in a rounding.

## The three numbers that are measured rather than judged

Everything else here is judgment. These are not:

| | |
|---|---|
| Full pipeline runtime, one field, 7 seasons | **0.8–3.1 min** (median ~1.3, 8 workers) |
| Python package | **2,415 lines** across 14 modules |
| Tests in the repository today | **zero** |

The runtime is the fact that shapes the architecture. Over a minute per field
rules out a synchronous API and forces a job queue on day one, which is why
orchestration is the largest single line in the table.

## Breakdown

| Workstream | Hours | Note |
|---|---|---|
| Read and understand the existing pipeline | 16–24 | Dense but heavily commented; the README carries the reasoning |
| Dependency packaging, GDAL in containers | 16–24 | Container image, not a plain Lambda zip |
| Job orchestration: queue, workers, retries, status | 40–60 | SQS + Fargate or Batch; idempotency and dead-lettering |
| Caching layer on S3 | 24–32 | Key discipline, plus the monthly analysis-window roll |
| CDL bulk store on S3 | 8–16 | Pattern already built and validated; this is the port from local disk |
| API service and boundary validation | 32–40 | Submit/status/result, GeoJSON validation, CRS, area limits, authz |
| Hardening external dependencies | 16–24 | Planetary Computer token expiry and throttling |
| Test suite | 40–56 | None exist; golden-file tests against the 11 demo fields and 347 validation fields |
| Observability and cost controls | 16–24 | Per-field metrics, failure alarms, spend monitoring |
| Infrastructure as code, CI/CD | 24–32 | Terraform or CDK |
| **Sum of the above** | **232–332** | ~6–8 focused weeks |
| Integration with Fieldprint internals | **not estimable** | Requires sight of the platform; add an allowance |

**Lean MVP: 150–190 hours.** Batch only, one region, no public API, results
written to a table the platform reads. A defensible Phase 1 if something
demonstrable is wanted before committing to the full build.

## What this is not

This is productionisation, not research. The algorithms are finished and
cross-checked between two independent implementations (see *Which is
authoritative?* in the root README). **Refitting the constants per region is
science work, not developer work, and is costed separately** — it belongs to
the calibration campaign, not to these hours.

## Retired: the CropScape dependency

This was the largest risk in the September version of this document, carrying a
**+40 hour** contingency. It has since been built and measured, and the
contingency is replaced by the 8–16 hour port line above.

CropScape is a public web service that throttles, times out, and returned HTTP
500 during the work itself. A published CDL year never changes, so the national
rasters are now downloaded once and read from disk
(`python/download_cdl.py`, `cdl_local.py`, `cdl_local.R`).

| | CropScape API | Local store |
|---|---|---|
| Score 347 field-years | 52 min | **5.6 s** |
| One 5-year stack, Python | ~45 s | 0.20 s |
| One 5-year stack, R | 56.7 s | 0.97 s |
| Dominant crop | — | agrees on **346 of 347** |

The numbers did not change, which is the point: the one disagreement is a field
CropScape called 33.0% Corn and the local store called 32.7% Peanuts. Against
polygon geometric area the API was already faithful at +0.06% mean, local at
+0.23%, both inside 30 m pixel quantization. **The gain is reliability and
speed, not accuracy** — and the production version is the same pattern pointed
at S3 rather than `~/geodata`.

## Three things that would still blow the estimate

**Cache invalidation.** Cache keys embed the analysis window, which rolls at
the start of each month (`analysis_window()` in `cache.py`). Get this wrong and
you either serve stale results or silently re-download everything. Small amount
of code, large amount of debugging.

**GDAL in serverless.** Container-based Fargate or Batch is the sane path.
Forcing it into a stock Lambda runtime will cost a week.

**Cold-start latency is a product decision, not an engineering one.** The first
run for a never-seen field takes minutes. Whether that is acceptable shapes the
entire UX and needs deciding before the API is designed.

## Cost at scale

Roughly 10 core-minutes per field for a full 7-year history, which at Fargate
rates is well under a cent per field. Inbound transfer to AWS is free, so the
imagery bytes are Microsoft's egress cost rather than ours. The CDL store adds
roughly 25 GB of S3 for 2018–2025, read-mostly — negligible against the compute.

**Verify the imagery position against a real Planetary Computer terms review
before putting it in a budget.** It is favorable enough to be worth confirming
rather than assuming, and a bulk consumer is a different proposition from a demo.
