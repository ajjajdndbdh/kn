# Development Plan — Continuation of MD-ERP (Kain Nusantara)

## 1) Objectives
- **Close P-0 (PO→PR→SO origin chain) cleanly**: canonical origin fields present on *new* PO docs, sales traced from SO via PR, refs two-way, no regressions.
- **Deliver FASE P (Papan PO per lini)**: PO board API + UI that shows stage chips per line, sales name when available, and auto-derived receipt/qty; `inspect` stage is **non-clickable**.
- Keep **UI/UX unchanged outside the new board** and keep entity/line scoping rules correct.

## 2) Implementation Steps

### Phase 1 — Core POC (Isolation): P-0 closure (must be green before FASE P)
**Core risk**: multiple PO birth paths + stored refs + scoping + historical snapshot fields.

1. **Seed demo chain (required data proof)**
   - Edit `seed_realistic.py` to add *at least 1* chain:
     - **SO → PR** with `source="so_repeat"` and `source_ref_id=<so_id>` (and/or per-item `source_ref_id`) so `_so_ids_of_pr()` can resolve.
     - PR approved → create PO via service path so PO gets canonical fields.
     - Ensure PO has `line_code`/`line_codes` (via `line_scope.stamp_doc` usage).
   - Do **not** backfill old demo POs; leave them empty (owner decision).
   - Re-run `python seed_realistic.py` and `python seed_e9_chain_demo.py`; ensure `verify_data_integrity` stays **237/0/0**.

2. **POC: `backend/test_core_p0_poc.py`**
   - Prove (minimum):
     - P0-1: **3 PO creation paths** (PR→PO, RFQ award→PO, manual PO) all write the **same canonical** origin fields using `po_origin_from_pr()`.
     - P0-2: `sales_name` is traced from SO and **not typed**.
     - P0-3: routine/manual PO still has origin fields **present but empty** ("—" in UI).
     - P0-4: `refs[]` are written **both ways** (PO parent→PR, PR child→PO).
     - P0-5: `doc_refs_service.backfill_source_refs(dry_run=True)` reports **0 would_add / 0 skipped**.
     - P0-6: `INV-REF-01` remains green (no false orphan claims for valid standalone PO).
     - P0-7: **zero residue** after test (measure by doc-number/id deltas).

3. **New guardrail gate: INV-ORIG-01**
   - Add `scripts/guardrails/verify_doc_origin.py` (or similar) enforcing:
     - All code paths inserting `purchase_orders` must use **single source** `po_origin_from_pr()` (no handwritten `pr_id`/`sales_name` inconsistencies).
   - Include `--self-test` that intentionally creates a violation (synthetic fixture or code-scan rule) proving it can go red.
   - Register gate in `scripts/gate.sh`.

4. **Documentation updates (append-only)**
   - Append a new **§STATUS P-0** block to `/app/plan.md` (journal style; do not rewrite).
   - Note owner decisions: **no backfill** for existing PO docs; routine PO sales is **empty**.

**Exit Phase 1 only when**: `backend/test_core_p0_poc.py` PASS, new gate PASS + self-test, `validate_compliance.py` 0 FAIL.

---

### Phase 2 — V1 App Development: FASE P (Papan PO per lini)

1. **Backend: board query API**
   - Implement `GET /api/purchase-orders/board` with filters:
     - `line`, `status`, `q`, `page`, `page_size` (+ CSV export).
   - Returned rows must include (computed where needed):
     - PO identity, supplier, entity, `line_code(s)`, `sales_name`, `expected_delivery_date` as ETA.
     - **Stage sequence** from `product_lines.stage_sequence` and existing `stage_progress[]` (initialize if missing).
     - `first_receipt_at/last_receipt_at` from inbound GRN `wms_tasks`.
     - `received_rolls/received_measure` derived from received rolls / FASE U dual qty fields already in docs.
   - Enforce:
     - entity scoping (`entity_scope`) + line scoping (`line_scope`).

2. **Backend: stage update API (except inspect)**
   - Implement `PATCH /api/purchase-orders/{po_id}/stage` to update `stage_progress[]`.
   - Rules:
     - Requires `purchase_order.update`.
     - Reject writes in “Semua Entitas” mode (409) per existing write-guard.
     - `inspect` stage is **never** manually settable; server returns 400/409 with clear message.
     - Audit/timeline entry recorded.

3. **Deriving `inspect` stage (pre-FASE I)**
   - Since `inspections` collection is still 0, derive `inspect` stage from what exists today:
     - receipt existence (GRN) + roll-level `inventory_rolls.inspection` / QC flags.
   - Document in code comment: source switches to `inspections` after FASE I lands.

4. **POC: `backend/test_core_po_board_poc.py`**
   - P1: stage chips match master sequences for woven and printing (not hardcoded).
   - P2: `sales_name` filled via SO for chain PO; empty-wajar for routine PO.
   - P3: `inspect` cannot be marked done manually.
   - P4: receipt date + received qty auto-changes after simulated receiving.
   - P5: line gating: printing-only user sees only printing.
   - P6: entity gating: PT-B PO invisible from PT-A.
   - P7: `INV-REF-01` remains green after P-0.

5. **Frontend: new board screen**
   - Add `frontend/src/features/purchasing/PoBoardView.jsx`:
     - Tabs per line loaded from master (no static hardcode).
     - Columns: Nama Sales · No PO · Item · Qty (dual) · Warna · Tanggal Order · Estimasi Ready · stage chips · Tanggal Masuk · Qty Terima (dual) · Keterangan.
     - Stage chips allow updates except inspect; show who/when/note.
     - CSV export button consistent with existing list/export conventions.
   - Register navigation:
     - `navStructure.js`, `navMeta.js`, `hubTabs.js`, `AppViewRouter.jsx`.
   - UI guardrails:
     - Use existing components (KNSelect conventions, `useEscapeClose` for any modal).
     - Do not change other screens’ layout/styles.

6. **Gates & audits**
   - Add/extend guardrail(s) as needed for board invariants (export, scoping, inspect-nonclickable).
   - Ensure `python scripts/audit_md_erp_readiness.py --fase P` is clean; DRIFT D3 disappears for *new* docs.

**End Phase 2 with testing agent**: run backend POCs + UI user stories.

---

### Phase 3 — Testing & Stabilization (no new scope)
1. Run:
   - `bash scripts/gate.sh --full`
   - `python scripts/validate_compliance.py`
   - `cd backend && python -m scripts.verify_entity_scoping`
   - `python scripts/guardrails/verify_* --self-test` for new gates
2. Call `testing_agent_v3` for:
   - P-0 POC validation + FASE P user stories in browser.
3. Clean residues:
   - Re-seed if needed (`seed_realistic.py` → `seed_e9_chain_demo.py`).
4. Append **§STATUS P (P-0 + FASE P)** to `/app/plan.md` with measured before/after.

## 3) Next Actions (immediate)
1. Implement seed demo chain SO→PR(so_repeat)→PO in `seed_realistic.py`.
2. Write `backend/test_core_p0_poc.py` and make it green.
3. Add INV-ORIG-01 gate + `--self-test`; register in `scripts/gate.sh`.
4. Build backend endpoints for PO board + stage patch + inspect derivation.
5. Create `PoBoardView.jsx` + nav wiring; keep other UI untouched.
6. Run full gates + audits; then call testing agent.

## 4) Success Criteria
- P-0:
  - `backend/test_core_p0_poc.py` PASS.
  - INV-ORIG-01 gate PASS + self-test proves it can fail.
  - New PO docs have `pr_id/pr_number/source/source_so_ids/sales_user_id/sales_name` consistently; routine PO shows empty "—".
  - Two-way `refs[]` confirmed; backfill dry-run 0/0; no residue.
- FASE P:
  - `backend/test_core_po_board_poc.py` PASS.
  - PO board UI works with line tabs from master; stage updates work except inspect.
  - Entity + line scoping enforced; writes blocked in “Semua Entitas”.
- Global:
  - `bash scripts/gate.sh --full` all green.
  - `python scripts/audit_md_erp_readiness.py --fase P` clean.
  - `python scripts/validate_compliance.py` 0 FAIL.
  - Testing agent confirms 4 user stories + at least 5 total for phase verification:
    1) MD sees Printing board stages; 2) MD marks celup done; 3) receiving auto-fills; 4) printing-only user sees no woven; 5) routine PO shows sales empty "—".
  - `/app/plan.md` updated by appending new §STATUS blocks (no overwrite).
