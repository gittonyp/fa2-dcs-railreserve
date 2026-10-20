# SDD ledger — plan: docs/superpowers/plans/2026-10-20-railreserve-demo.md

Pre-flight: no shared interface conflicts. Task 2 defines the six base settings; Task 3 adds rate_limit_per_minute. Schema request models are distinct per task. Task 6 raises the test pool size; no production signature changes.

Ruling: No git worktree or commits — the workspace is not a git repository and the user did not ask to initialize one. Evidence for each task is its test command and output in this file.

Task 1: complete (tests: docker compose run --rm --no-deps api1 pytest tests/test_health.py -v → 1 passed; compose config OK)
Task 2: complete (tests: docker compose run --rm api1 pytest tests/test_repository.py -v → 2 passed)
Task 3: complete (tests: docker compose run --rm api1 pytest tests/test_hold.py tests/test_ratelimit.py -v → 4 passed)
Task 4: complete (tests: docker compose run --rm api1 pytest tests/test_payment.py -v → 2 passed)
Task 5: complete (tests: docker compose run --rm api1 pytest tests/test_naive.py tests/test_demo.py -v → 3 passed)
Task 6: complete (tests: docker compose run --rm api1 pytest -v → 14 passed)
Task 7: complete (live checks through Nginx: /health 200 with X-Upstream; dashboard 200; safe race 1×201/19×409; naive race 20×201; payment replay same booking PNR1000000000; api1 stopped → 5/5 health 200 via api2, then restarted)
Ruling: Compose hold TTL raised from 10s to 120s after a live dashboard payment hit 410/410 at ~17s. The sweeper/expiry behavior is still covered by tests; the longer TTL keeps the presentation flow reliable.
Ruling: Nginx uses the spec'd `max_fails=1 fail_timeout=5s`. The demo driver waits for `/health` through Nginx before racing so startup connection refusals do not disable both upstreams mid-sweep. Nginx healthcheck uses `127.0.0.1`, not `localhost`, because `localhost` resolves to `::1` inside the container and Nginx listens on IPv4.
Ruling: Expiry demo uses a DB time-travel update instead of sleeping `HOLD_TTL_SECONDS + 2`; this keeps the six-scenario run fast and deterministic while still exercising the reclaim path.
Ruling: Dashboard is served by Nginx via a read-only bind mount, not copied into the API image.
Bug found and fixed: concurrent payments with the same key initially returned 410 to losers after the seat lock; `repository.pay_hold` now re-reads the committed booking by idempotency key or hold id and returns it as a replay. Added `test_concurrent_payment_with_same_key_creates_one_payment`.
Browser note: the dashboard fires 20 fetch attempts, but HTTP/1.1 limits per-host concurrency, so the naive race may show fewer than 20 winners in-browser. The CLI driver sends all 20 at once and consistently shows 20/20.
Task 8: complete (`scripts/demo.py` + `scripts/demo.sh` wrapper; six scenarios; README; 12-slide `railreserve/docs/presentation-outline.md`)
Task 9: complete (full suite: docker compose run --rm api1 pytest -v → 15 passed; clean `down -v` + `up --build -d`; health 200/dashboard 200; fresh-stack demo 6/6 PASS; failover while api1 stopped: reset 200, hold S1-02 201, stats held=1; api1 restarted healthy; demo left reset to 50 available)


