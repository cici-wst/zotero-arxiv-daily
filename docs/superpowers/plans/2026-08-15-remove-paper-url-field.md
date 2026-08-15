# Remove the Paper URL Text Field Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the redundant `论文URL` Feishu field while preserving duplicate detection through `论文链接.link`.

**Architecture:** Keep canonical URL normalization in `feishu.py`. Record creation emits only the hyperlink field; record search requests only that field and extracts its `link` member into a normalized string set. Schema validation and all setup documentation describe the remaining field set. Existing malformed hyperlink data remains an explicit error.

**Tech Stack:** Python, pytest, requests, OmegaConf, Feishu Bitable REST API.

---

### Task 1: Add failing field-migration tests

**Files:**
- Modify: `tests/test_feishu.py`

- [ ] **Step 1: Replace record-field expectations**

Update `test_paper_to_record_fields_maps_paper_and_shanghai_date` and `test_expected_schema_excludes_removed_fields_and_places_urls_last` so `paper_to_record_fields` emits no `论文URL`, emits the canonical URL under `论文链接.link`, and expects `论文链接` as the final URL field.

- [ ] **Step 2: Add hyperlink record-search tests**

Update `test_list_existing_urls_follows_pagination` so paginated responses return `fields: {"论文链接": {"text": ..., "link": ...}}`; assert the request body uses `field_names: ["论文链接"]` and the returned set contains normalized links.

- [ ] **Step 3: Add malformed hyperlink cases**

Update `test_list_existing_urls_rejects_malformed_url_field` and parameterize it over missing field, `None`, empty mapping, missing `link`, non-string `link`, and empty `link`; each must raise `FeishuApiError` naming `论文链接`.

- [ ] **Step 4: Add duplicate batch-payload integration coverage**

Add `test_deliver_uses_hyperlink_records_for_dedup` using a real `FeishuClient` with `StubSession`. The handler must return token, schema, record-search, batch-create, and webhook responses. Return an existing matching `论文链接: {text, link}` plus a new paper, then assert the record-search request asks for `论文链接` and the real batch-create JSON contains only the new paper.

- [ ] **Step 5: Run the focused tests and confirm RED**

Run `uv run pytest tests/test_feishu.py -q`. Expected: failures caused by the old `论文URL` implementation, not collection or syntax errors.

### Task 2: Switch production Feishu behavior

**Files:**
- Modify: `src/zotero_arxiv_daily/feishu.py`

- [ ] **Step 1: Remove `论文URL` from `EXPECTED_FIELD_TYPES`**

Keep `论文链接` as a required URL field.

- [ ] **Step 2: Stop emitting `论文URL`**

Retain one canonical URL in the `论文链接` object with `text` and `link` members.

- [ ] **Step 3: Read and validate `论文链接.link`**

Request only `论文链接`, require a mapping and non-empty string `link`, normalize it, and raise explicit `FeishuApiError` messages for malformed values.

- [ ] **Step 4: Compare string URLs during delivery**

Derive each pending record's URL from `record["论文链接"]["link"]` before comparing to the existing normalized URL set.

- [ ] **Step 5: Run the focused tests and confirm GREEN**

Run `uv run pytest tests/test_feishu.py -q`. Expected: all Feishu tests pass.

### Task 3: Synchronize setup documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/feishu-official-api-research.md`
- Modify: `docs/superpowers/specs/2026-08-11-feishu-delivery-design.md`
- Modify: `docs/superpowers/plans/2026-08-11-feishu-delivery.md`

- [ ] **Step 1: Remove `论文URL` from required field tables and examples**

Document `论文链接` as the canonical clickable URL and deduplication source. Update the README's schema count from 12 fields to 11.

- [ ] **Step 2: Document migration order**

State: audit and backfill `论文链接` from valid old `论文URL`, repair/delete rows missing both, deploy and verify, then delete the physical `论文URL` column in Feishu.

- [ ] **Step 3: Search for stale references**

Run `rg -n "论文URL" README.md docs src tests`; expected matches are only the migration instructions and historical incident/design notes, not required schema, runtime code, or current setup instructions.

### Task 4: Full verification

**Files:**
- No new files.

- [ ] **Step 1: Run all tests**

Run `uv run pytest -q` with the tool invocation timeout set to 60,000 ms. Do not add a nonexistent pytest-timeout or ruff dependency.

- [ ] **Step 2: Run static checks**

Run `git diff --check`; this repository does not configure ruff or another linter.

- [ ] **Step 3: Inspect the diff**

Run `git diff --check` and verify no secrets, temporary logs, or unrelated files are included.

- [ ] **Step 4: Report the external migration action**

Treat the Feishu migration as a deployment precondition: before starting the new scheduled run, audit every row, backfill valid old `论文URL` values into `论文链接` hyperlink objects, repair or delete rows where both are invalid, and verify every row has a non-empty `论文链接.link`. Then run the new code once, and only after it succeeds delete the physical `论文URL` column.
