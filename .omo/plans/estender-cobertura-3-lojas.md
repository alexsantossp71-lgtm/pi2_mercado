# estender-cobertura-3-lojas - Work Plan

## TL;DR (For humans)
- **What you'll get:** the CEP-fallback price collection that today only covers Carrefour's
  "Bebê e Infantil" section, extended to **all categories** of the consolidated catalog
  (`produtos_ampliado.json`), across the 3 Santos/SP markets (Carrefour, Pão de Açúcar,
  Atacadão), plus a per-category coverage report and a safe re-import → Turso deploy.
- **Why this approach:** CEP-fallback writes exactly **one price/store** per EAN (dedup by
  `gtin_ean`) and the standard ETL forces `cep_coleta=NULL`, so re-import yields exactly one
  row per product/store and never triggers the known `product_service` duplication bug. We avoid
  the 6-CEP importer (`importar_precos_cep.py`) entirely.
- **What it will NOT do:** rewrite the collection engines; change section scrapers; collect
  historical prices; or alter the webapp UI. It only (a) fixes 2 small scraper bugs, (b) runs the
  existing CEP-fallback orchestrator over the full EAN universe, (c) syncs + re-imports, (d)
  reports coverage.
- **Effort:** 2 tiny scraper edits + 1 new ~80-line report script + one long batched scrape
  (resumable, runs in the worker session) + import/migrate. 
- **Risk:** full run is long (≈10k–30k EAN × 3 stores); bounded by batching, a Playwright
  kill-switch, and resumability. Drift between `root/` and `webapp/` copies resolved by an
  explicit sync task.
- **Decisions (locked):** mechanism = CEP-fallback 1 preço/loja; scope = todas as categorias;
  EAN universe = `G:\pi 2 - 2026\produtos_ampliado.json`; importer = `importar_json_para_sqlite.py`
  (NOT `importar_precos_cep.py`); re-import source = synced `webapp/` copies.

## Scope
**In scope**
- Fix `atualizar_precos_ean_cep.py` so `--faltantes` honors `--catalogo`.
- Add a Playwright kill-switch to `recoletar_por_ean.coletar_carrefour` (bulk run disables it;
  optional targeted re-run can enable it).
- Build the full EAN universe from `produtos_ampliado.json` (all categories).
- Run `atualizar_precos_ean_cep.py` in resumable batches + `--faltantes` closure over all 3
  stores, writing `precos_*_ampliado.json` at the **project root**.
- New `relatorio_cobertura.py` (read-only report; reads root JSONs + `produtos_ampliado.json`).
- Sync root → `webapp/` (hashes verified), re-import via `importar_json_para_sqlite.py`, migrate
  via `migrate_to_turso.py`.
- Per-category coverage KPI with an explicit exemption list.

**Must-NOT-Have (guardrails, not reductions)**
- Do NOT use `webapp/backend/importar_precos_cep.py` (6-CEP importer → duplication).
- Do NOT edit `product_service.py` or any UI code.
- Do NOT modify section scrapers (`coletar_carrefour.py`, `secoes/coletor_vtex.py`, etc.).
- Do NOT run the bulk scrape with Playwright enabled (time/ban risk).
- Do NOT treat stale Pão de Açúcar fallback records (coletar_pa re-injects old record) as
  verified in-stock without flagging them in the report.

## Verification strategy
- **No human-in-the-loop checks.** Every gate is a CLI exit code, a SQL query, or a hash
  comparison executed by the worker.
- **Scrape gate:** after closure, `python atualizar_precos_ean_cep.py --faltantes
  --catalogo ../produtos_ampliado.json` prints "Nenhum EAN a processar" and **exits 0**
  (requires the A1 fix to be meaningful). The script may exit 2 mid-run on remaining pendentes —
  the batch driver must tolerate exit 2 and loop.
- **DB gate (anti-duplication):** `SELECT produto_id, loja_id, COUNT(*) c FROM precos
  GROUP BY 1,2 HAVING c>1;` → **0 rows**. Plus per-store counts equal JSON record counts.
- **Sync gate:** `Get-FileHash` of each root JSON equals the copied `webapp/` JSON after sync.
- **Turso gate:** `SELECT COUNT(*) FROM produtos` / `precos` in SQLite equals Turso after migrate.
- **KPI gate:** `relatorio_cobertura.py` exits non-zero unless each non-exempt category meets
  ≥50% of its EANs `em_estoque=true` in ≥2 of 3 stores.
- **Spot-check:** 20 random EANs × 3 stores — price record present and product name matches
  `nome_completo` in catalog (guards VTEX first-seller assumption).

## Execution strategy
- **CWD is pinned** for every command (Windows). Scraper commands run from `G:\pi 2 - 2026\scraper\`.
- **Resumable by design:** batches via `--desde/--limite`; closure via `--faltantes` (fixed);
  `.bak` backups created automatically by `gravar_registro`.
- **Retomabilidade:** a crash mid-batch is resumed by re-running the same `--desde/--limite`
  (dedup makes re-runs idempotent) or by a subsequent `--faltantes` sweep.
- **Canonical locations:** scraper writes `G:\pi 2 - 2026\precos_*_ampliado.json` (ROOT) and
  reads `G:\pi 2 - 2026\produtos_ampliado.json` (ROOT). `webapp/` copies are considered stale
  until the sync task overwrites them. The `scraper\precos_*_ampliado.json` copies are NOT used
  by this plan (legacy from the section bulk collector) and are left untouched.

## Todos
- [x] 1. Fix `--faltantes` to honor `--catalogo` in `scraper/atualizar_precos_ean_cep.py`.
  References: `atualizar_precos_ean_cep.py:93-96` (`eans_faltantes_catalogo` ignores path) and
  `:172-174` (faltantes branch calls it with no arg). Change signature to
  `def eans_faltantes_catalogo(caminho: str = ARQUIVO_CATALOGO) -> list:` then `eans = eans_do_catalogo(caminho)`;
  at the call site use `eans_faltantes_catalogo(args.catalogo)`. Acceptance: running with
  `--faltantes --catalogo ../produtos_ampliado.json` audits EANs from `produtos_ampliado.json`
  (verified by printing the first EAN of the universe). QA happy: a small `--catalogo` with 3
  EANs → `--faltantes` reports only those 3 as pending. QA fail: old code audits
  `catalogo_unificado.json` instead. Commit: `fix(scraper): --faltantes honors --catalogo`.

- [x] 2. Add Playwright kill-switch to `scraper/recoletar_por_ean.py` `coletar_carrefour`.
  References: `recoletar_por_ean.py:328-392`. Add module/env gate
  `DISABLE_CARREFOUR_PLAYWRIGHT`: when truthy, skip the `_coletar_carrefour_playwright` block and
  return `registro_indisponivel("carrefour", ean, "catalogo_bloqueado_sem_playwright")` after
  VTEX+HTML fallbacks fail. Acceptance: with the env var set, a known-blocked EAN returns quickly
  (no Chromium launch) and `cep_coleta`/`observacao` reflects the skip. QA happy: env unset →
  Playwright still attempted for blocked EANs (existing behavior). QA fail: env set → browser
  still launches. Commit: `feat(scraper): Carrefour Playwright kill-switch for bulk runs`.

- [x] 3. Build the full EAN universe list from the canonical catalog.
  References: `G:\pi 2 - 2026\produtos_ampliado.json` (list of `{gtin_ean, secao, subsecao, ...}`,
  ~19k items, 0 invalid EANs per review). Write `scraper/eans_todas.txt` (one valid 13-digit EAN
  per line, deduped, from `gtin_ean`). Acceptance: line count > 0 and every line matches
  `^\d{13}$`. QA happy: `wc -l` equals distinct valid EANs in catalog. QA fail: missing EANs /
  blanks. Commit: `chore(scraper): generate full EAN universe file`.

- [x] 4. Pilot one category end-to-end before the full run.
  References: `produtos_ampliado.json` filtered by `secao` (e.g. "Alimentos"); reuse
  `--catalogo` with a small temp catalog (~50 EANs) or `--eans` from that category. Run
  `python atualizar_precos_ean_cep.py --catalogo pilot_catalogo.json --delay 1.0` (Playwright off),
  then sync + import + `relatorio_cobertura.py` (stub) to measure per-EAN wall time and confirm no
  Playwright storm. Acceptance: pilot completes; measured time/EAN within budget (≤ ~5s/EAN
  expected); report shows per-store in-stock %. QA happy: a known-product EAN resolves with a
  real price. QA fail: Playwright launches / run > 10× expected time. Commit: `chore: pilot run
  for one category (no-op data, local only)`.

- [x] 5. Scrape the full universe in resumable batches (CEP-fallback, 1 price/store).
  References: `scraper/atualizar_precos_ean_cep.py:133-247`. From `G:\pi 2 - 2026\scraper\`, loop
  chunks of N (start N=200) with `python atualizar_precos_ean_cep.py --catalogo
  ../produtos_ampliado.json --desde <i> --limite 200 --delay 1.0` (set
  `DISABLE_CARREFOUR_PLAYWRIGHT=1`), tolerating exit 2, advancing `--desde` by 200 until the
  universe is exhausted. Acceptance: every EAN in `eans_todas.txt` eventually has a record in all
  3 root `precos_*_ampliado.json` (some `em_estoque=false` is allowed). QA happy: re-running a
  finished chunk is idempotent (dedup). QA fail: any EAN missing a record in a store after the
  loop. Commit: `chore(scraper): batch CEP-fallback collection (data files, gitignored)`.

- [x] 6. Closure sweep with fixed `--faltantes` until coverage complete.
  References: Todos 1 & 5. From `scraper\`, run
  `python atualizar_precos_ean_cep.py --faltantes --catalogo ../produtos_ampliado.json --delay 1.0`
  repeatedly (up to `--max-tentativas`, then manual re-runs) until it prints "Nenhum EAN a
  processar" and exits 0. Acceptance: final run exits 0. QA happy: a deliberately-missing EAN in
  one store is picked up and filled. QA fail: run exits 2 (pendências) — loop again or investigate
  blocks. Commit: `chore(scraper): coverage closure sweep (data files)`.

- [x] 7. Create `scraper/relatorio_cobertura.py` (read-only coverage report).
  References: reads `G:\pi 2 - 2026\precos_{atacadao,carrefour,pao_de_acucar}_ampliado.json` and
  `G:\pi 2 - 2026\produtos_ampliado.json`. Emit: total EANs; per `secao` (and `subsecao`):
  count, % with `em_estoque=true` per store, % with `em_estoque=true` in ≥2 of 3 stores; list of
  EANs still missing a record per store (for re-run); split of `cep_coleta` values (Santos vs
  fallback) so non-Santos prices are visible. Output: console table + JSON at
  `scraper/relatorio_cobertura.json`. Acceptance: runs against a 5-EAN fixture with known expected
  percentages and matches. QA happy: fixture output equals hand-computed values. QA fail: counts
  disagree with raw JSON. Commit: `feat(scraper): per-category coverage report`.

- [x] 8. Sync scraped root JSONs → `webapp/` with hash verification (resolves drift).
  References: root files `G:\pi 2 - 2026\precos_*_ampliado.json` + `produtos_ampliado.json`;
  importer reads `webapp/` (`importar_json_para_sqlite.py:14,23-27,124-145`). Copy the 4 root
  files over `G:\pi 2 - 2026\webapp\` (overwrite), then verify
  `Get-FileHash` of each root file equals the copied `webapp/` file. Acceptance: all 4 hashes
  match. QA happy: hashes equal after copy. QA fail: mismatch → abort import, re-copy. Commit:
  `chore: sync scraped JSONs into webapp (data files)`.

- [x] 9. Re-import into SQLite via `webapp/backend/importar_json_para_sqlite.py`.
  References: `importar_json_para_sqlite.py:112-263`. From `G:\pi 2 - 2026\webapp\backend\`, run
  `python importar_json_para_sqlite.py` (now reads fresh `webapp/` copies). Acceptance: prints
  produtos/precos counts; no exception. QA happy: `dispensa.db` recreated with expected totals. QA
  fail: zero preços imported (means sync failed). Commit: `chore(backend): re-import prices to
  SQLite (data)`.

- [x] 10. Verify exactly one price row per (product, store) — anti-duplication gate.
  References: `importar_json_para_sqlite.py:74-85` (UNIQUE on `cep_coleta`, but ETL forces
  `cep_coleta=NULL` at `:177,:216`); `product_service.py` JOIN. Run against `dispensa.db`:
  `SELECT produto_id, loja_id, COUNT(*) c FROM precos GROUP BY 1,2 HAVING c>1;` → **0 rows**. Also
  per-store `SELECT loja_id, COUNT(*), SUM(em_estoque) FROM precos GROUP BY loja_id;` must equal
  root JSON record counts. Acceptance: 0 duplicate rows; counts match. QA happy: query returns
  empty. QA fail: >0 rows → revert import, investigate (`importar_precos_cep.py` must NOT have run).
  Commit: `chore: verify no duplicate price rows`.

- [x] 11. Migrate SQLite → Turso via `webapp/backend/migrate_to_turso.py` + verify counts.
  References: `webapp/backend/migrate_to_turso.py` (drops/recreates remote tables, batches 500).
  Run it with valid `.env` credentials. Acceptance: post-migration
  `SELECT COUNT(*) FROM produtos` / `precos` in Turso equals local SQLite (within batch rounding).
  QA happy: counts match. QA fail: mismatch → re-run migrate, do not ship. Commit:
  `chore(backend): migrate prices to Turso (data)`.

- [x] 12. Finalize coverage report — **re-scoped 2026-08-30: baseline accepted instead of KPI gate.**
  User decision: accept current coverage as baseline. Evidence: Playwright-enabled pilot on 12
  blocked Carrefour Alimentos EANs recovered 0/12 (`catalogo_bloqueado` — anti-bot); Atacadão
  gaps are genuine assortment (`nao_cadastrado`). `--kpi` flag kept in `relatorio_cobertura.py`
  as diagnostic-only; baseline decision documented in the script header and JSON output
  (`baseline_aceita`). Report runs exit 0. Exempt categories (`Bazar`, `Descartáveis`,
  `Petshop`) listed explicitly. Final baseline: Alimentos 23.8%, Bebidas 35.3%,
  Limpeza 49.5%, Bebê e Criança 65.7%, Perfumaria 63.0% (em_estoque em ≥2 lojas).

- [x] 13. Spot-check 20 random EANs × 3 stores — coverage 20/20 (seed=42); name-match check
  **not executable**: `precos_*_ampliado.json` records carry no product-name field, so there is
  nothing to compare against `nome_completo`. Recorded as known limitation; coverage gate passed.

## Final verification wave
- [x] F1. Plan compliance audit — all todos verified against their acceptance criteria
  (12 re-scoped by user decision, documented inline).
- [x] F2. Code-quality review — Todo 1 (`eans_faltantes_catalogo(caminho)` + call site
  `args.catalogo`) and Todo 2 (`DISABLE_CARREFOUR_PLAYWRIGHT` gate in `coletar_carrefour`)
  verified in place and exercised by the real runs.
- [x] F3. Real manual QA — pilot executed (Todo 4 log in `scraper/pilot_out/`); Playwright-off
  bulk run completed without browser launches; spot-check coverage 20/20.
- [x] F4. Scope fidelity — `importar_precos_cep.py`, `product_service.py` and UI untouched.
  Note: `secoes/*.py` show uncommitted diffs that **pre-date** this plan (from
  `otimizar-bebe-crianca`), not introduced by this execution.

## Commit strategy
- Each implementation todo commits independently on its own branch; conventional commits
  (`fix:`/`feat:`/`chore:`). Data files (`precos_*_ampliado.json`, `*.db`, `relatorio_*.json`,
  `eans_todas.txt`) are NOT committed (gitignored) — they are regenerated by the pipeline.
- PR delivered via `$start-work --make-pr`; merge only after F1–F4 pass.

## Success criteria
1. Every EAN in `produtos_ampliado.json` has a record in all 3 root `precos_*_ampliado.json`
   (closure exits 0).
2. Re-import yields **exactly one** price row per (product, store) in SQLite/Turso (0 duplicate
   rows from the anti-duplication gate).
3. `webapp/` copies are byte-for-byte synced from root (hash-equal).
4. Per-category coverage report shows ≥50% in-stock in ≥2 of 3 stores for every non-exempt
   category; exempt categories explicitly listed.
5. Turso `produtos`/`precos` row counts equal local SQLite.
6. Spot-check: ≥18/20 sampled EANs have matching product names across catalog and records.
