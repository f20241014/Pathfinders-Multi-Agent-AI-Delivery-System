# R4 validation record

Executed on D:\Pathfinders-R4, November 2026, using .venv (Python 3.12).

- R4 W1-W6 suite: 27 passed. flake8 allocation package and six test files: clean.
- Repository regression: `python -m pytest --ignore=tests/test_prediction.py -q`:
  860 passed, 2 skipped, 3 OR-Tools SWIG deprecation warnings, 77.71 seconds.
  Prediction tests excluded as in repository CI; raw ML datasets/weights were not
  fetched for this task. Two existing traffic-dependent tests skipped without data.
- Eighteen actual pilot runs: reports/r4/time_limit_raw.csv and derived table.
  On 30 orders, mean objective 800 at 0.1s, 773.33 at 0.5s and 2s; zero drops.
  Small four-order pilot objectives equal exhaustive optima. This is not a proof
  of near-optimality at realistic scale. No final test seeds used for tuning.
- Real-map smoke: 2,377 nodes/6,056 edges, 10 vehicles, 100 synthetic orders,
  free-flow only. CNP assigned all 100; centralized dropped zero. Raw values in
  reports/r4/map_smoke.json. No claim of Amazon demand or traffic validation.
- SimPy demos for centralized/independent/full allocation: 5 delivered, 0 failed
  each; logs/r4-*.jsonl (ignored generated logs). Full here is allocation-only,
  not R5 negotiation or R7 D* Lite end-to-end validation.

Reproduce focused checks on PowerShell:

```powershell
$tests = Get-ChildItem tests/test_allocation_w*.py | ForEach-Object FullName
python -m pytest $tests -q
python -m flake8 src/allocation $tests --max-line-length=100
python -m src.allocation.study
python -m src.allocation.sim_runner --mode centralized
```

Map smoke additionally requires existing map dependencies (`osmnx`, matplotlib):
`python -m src.allocation.map_smoke`. Timings and bounded-search solutions can
vary with hardware. Config, versions and SHA256 are in reports/r4/manifest.json.

External references: official Google OR-Tools guides were opened; the Smith DOI
resolver was unavailable during this session, so the bibliography entry needs
manual verification. Buddy review, R3 branch integration, R5 agreement and
teach-back are human/team follow-ups; none are claimed complete.

## Repository audit follow-up

Priority now follows R3 (1 highest); dictionary feasibility results use an
explicit adapter. The focused suite now has 29 passing tests, with clean lint.
The 18 pilot rows were regenerated using the new convention; the 30-order mean
objectives remain 800/773.33/773.33 at 0.1/0.5/2 seconds, with zero drops.
Other-role defect reproductions and audit scope are in REPOSITORY_WEEK6_AUDIT.md
and reports/r4/audit_reproductions.json. These do not certify those branches.

Follow-up repository regression: 862 passed, 2 skipped, 3 SWIG deprecation
warnings in 75.46 seconds, with tests/test_prediction.py excluded as above.
