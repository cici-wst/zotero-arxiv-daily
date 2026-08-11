# Feishu Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace SMTP email delivery with idempotent Feishu Bitable persistence and Feishu group-bot notifications.

**Architecture:** Keep the existing retrieval/reranking pipeline in `Executor`, but inject a focused `FeishuClient` at the composition root. The client owns URL normalization, schema validation, Bitable pagination/batching, and webhook card delivery; pure helpers are tested separately from HTTP behavior.

**Tech Stack:** Python 3.13, Hydra/OmegaConf, requests, pytest, GitHub Actions, Feishu Open API.

---

## File map

- Create `src/zotero_arxiv_daily/feishu.py`: immutable settings/result types, pure mapping/card helpers, HTTP client.
- Create `tests/test_feishu.py`: pure helper and Feishu API client tests with injected session stubs.
- Modify `src/zotero_arxiv_daily/main.py`: construct and inject `FeishuClient`.
- Modify `src/zotero_arxiv_daily/executor.py`: call the injected delivery client; remove email rendering/sending.
- Modify `tests/test_main.py`, `tests/test_executor.py`, `tests/conftest.py`, `tests/canned_responses.py`: update fixtures and end-to-end expectations.
- Modify `src/zotero_arxiv_daily/utils.py`, `tests/test_utils.py`: remove SMTP code and SMTP tests.
- Delete `src/zotero_arxiv_daily/construct_email.py`, `tests/test_construct_email.py`.
- Modify `config/base.yaml`, `config/custom.yaml`: replace `email` with `feishu`.
- Modify `.github/workflows/main.yml`, `.github/workflows/test.yml`: inject Feishu credentials and remove email credentials.
- Modify `pyproject.toml`, `uv.lock`: declare `requests` directly and remove `aiosmtpd`.
- Modify `README.md`, `.github/copilot-instructions.md`, `CLAUDE.md`: describe the Feishu pipeline and setup.

### Task 1: Add pure URL, record, and notification helpers

**Files:**
- Create: `src/zotero_arxiv_daily/feishu.py`
- Create: `tests/test_feishu.py`

- [ ] **Step 1: Write failing URL normalization tests**

```python
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://ARXIV.org/pdf/2601.00001v2.pdf?x=1#p2", "https://arxiv.org/abs/2601.00001"),
        ("https://www.biorxiv.org/content/10.1101/2026.01.01.123456v3.full.pdf", "https://doi.org/10.1101/2026.01.01.123456"),
        ("https://example.com/Paper/?download=1#top", "https://example.com/Paper"),
    ],
)
def test_normalize_paper_url(raw, expected):
    assert normalize_paper_url(raw) == expected
```

- [ ] **Step 2: Run the URL tests and verify RED**

Run: `uv run pytest tests/test_feishu.py::test_normalize_paper_url -v`
Expected: FAIL because `zotero_arxiv_daily.feishu` does not exist.

- [ ] **Step 3: Implement immutable settings and URL normalization**

```python
@dataclass(frozen=True)
class FeishuSettings:
    app_id: str
    app_secret: str
    app_token: str
    table_id: str
    webhook_url: str

def normalize_paper_url(url: str) -> str:
    parsed = urlsplit(url)
    host = parsed.netloc.lower()
    path = parsed.path.rstrip("/")
    arxiv_id = _extract_arxiv_id(host, path)
    if arxiv_id:
        return f"https://arxiv.org/abs/{arxiv_id}"
    doi = _extract_preprint_doi(host, path)
    if doi:
        return f"https://doi.org/{doi}"
    return urlunsplit((parsed.scheme.lower(), host, path, "", ""))
```

- [ ] **Step 4: Write failing record mapping tests**

Assert exact field names/types, normalized `论文URL`, URL-object shape, joined authors/affiliations, score, and Asia/Shanghai midnight timestamp.

- [ ] **Step 5: Implement `paper_to_record_fields()`**

```python
def paper_to_record_fields(paper: Paper, recommendation_date: datetime) -> dict[str, object]:
    canonical_url = normalize_paper_url(paper.url)
    return {
        "标题": paper.title,
        "论文URL": canonical_url,
        "论文链接": {"text": "打开论文", "link": canonical_url},
        "作者": ", ".join(paper.authors),
        "摘要": paper.abstract,
        "TLDR": paper.tldr or "",
        "作者单位": ", ".join(paper.affiliations or []),
        "来源": paper.source,
        "相关度": paper.score,
        "推荐日期": _shanghai_midnight_ms(recommendation_date),
    }
```

- [ ] **Step 6: Write failing notification-card tests**

Cover normal splitting, exact byte-size enforcement, oversized TLDR truncation marker, and fixed content that cannot fit raising `ValueError`.

- [ ] **Step 7: Implement payload construction helpers**

Use `MAX_WEBHOOK_BODY_BYTES = 20 * 1024`, serialized UTF-8 size checks, and small helpers `_paper_markdown()`, `_payload_size()`, `_truncate_utf8()`. Do not add a paper-count cap.

- [ ] **Step 8: Run helper tests and verify GREEN**

Run: `uv run pytest tests/test_feishu.py -k "normalize or record or payload" -v`
Expected: PASS.

- [ ] **Step 9: Commit helper behavior**

```bash
git add src/zotero_arxiv_daily/feishu.py tests/test_feishu.py
git commit -m "feat: add Feishu delivery helpers"
```

### Task 2: Implement the Feishu API client

**Files:**
- Modify: `src/zotero_arxiv_daily/feishu.py`
- Modify: `tests/test_feishu.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`

- [ ] **Step 1: Add deterministic HTTP session stubs**

Create `StubResponse` and `StubSession` in `tests/test_feishu.py`; record method, URL, headers, params, and JSON body. Responses must support `raise_for_status()` and `json()`.

- [ ] **Step 2: Write failing authentication tests**

Verify the internal token endpoint body, cached token reuse within one run, HTTP errors, `code != 0`, and missing `tenant_access_token` all raise explicit exceptions.

- [ ] **Step 3: Implement request primitives and token acquisition**

```python
class FeishuApiError(RuntimeError):
    pass

class FeishuClient:
    def __init__(self, settings: FeishuSettings, session: requests.Session | None = None):
        self.settings = settings
        self.session = session or requests.Session()
        self._tenant_token: str | None = None

    def _request_json(self, method: str, url: str, options: RequestOptions) -> dict[str, object]:
        ...

    def _get_tenant_token(self) -> str:
        ...
```

Use a frozen `RequestOptions` object instead of more than three positional parameters. Set `HTTP_TIMEOUT_SECONDS = 30`.

- [ ] **Step 4: Write failing schema-validation tests**

Test all 13 configured fields, including fields not currently populated: `标题`、`论文URL`、`论文链接`、`作者`、`摘要`、`TLDR`、`作者单位`、`来源`、`分类`、`相关度`、`发布日期`、`推荐日期`、`代码链接`. Types are Text=1, Number=2, SingleSelect=3, MultiSelect=4, DateTime=5, URL=15. Missing or mismatched fields must name the offending field.

- [ ] **Step 5: Implement `validate_table_schema()`**

GET `/bitable/v1/apps/{app_token}/tables/{table_id}/fields`, follow pagination, compare against immutable `EXPECTED_FIELD_TYPES`, and raise `FeishuApiError` on mismatch.

- [ ] **Step 6: Write failing existing-URL pagination tests**

POST `/records/search?page_size=500`, request only `论文URL`, continue with `page_token`, normalize returned values, and return a frozen set.

- [ ] **Step 7: Implement `list_existing_urls()`**

Keep each page request in a helper under 50 lines. Reject malformed record/field payloads instead of ignoring them.

- [ ] **Step 8: Write failing batch-create tests**

Verify 0 records causes no request, 1,001 records produce two calls of 1,000 and 1, and a second-batch API error is exposed.

- [ ] **Step 9: Implement `batch_create_records()`**

Use `BITABLE_BATCH_LIMIT = 1000` and `client_token=str(uuid4())` for each batch. Return the number created.

- [ ] **Step 10: Write failing webhook tests**

Verify every payload is posted to the configured webhook, response `code == 0` is required, and the full webhook URL never appears in logged messages.

- [ ] **Step 11: Implement `send_notification()` and `deliver()`**

```python
@dataclass(frozen=True)
class DeliveryResult:
    recommended_count: int
    inserted_count: int

def deliver(self, papers: Sequence[Paper], recommendation_date: datetime) -> DeliveryResult:
    self.validate_table_schema()
    existing = self.list_existing_urls()
    unique_papers = deduplicate_papers(papers)
    records = [paper_to_record_fields(p, recommendation_date) for p in unique_papers]
    missing = [record for record in records if record["论文URL"] not in existing]
    inserted = self.batch_create_records(missing)
    self.send_notification(unique_papers, inserted)
    return DeliveryResult(len(unique_papers), inserted)
```

`deduplicate_papers()` preserves the first occurrence order and keys by `normalize_paper_url(paper.url)`. Add tests for exact duplicate URLs and arXiv `/pdf/...vN.pdf` versus `/abs/...` variants in the same input batch.

For an empty paper list, skip schema/table calls and send the empty notification only when requested by the caller.

- [ ] **Step 12: Declare direct dependency and update lock file**

Add `requests>=2.32.0` to `[project].dependencies`; run `uv lock`. Remove `aiosmtpd` later with email cleanup.

- [ ] **Step 13: Run client tests and verify GREEN**

Run: `uv run pytest tests/test_feishu.py -v`
Expected: PASS.

- [ ] **Step 14: Commit API client**

```bash
git add src/zotero_arxiv_daily/feishu.py tests/test_feishu.py pyproject.toml uv.lock
git commit -m "feat: add Feishu API client"
```

### Task 3: Integrate Feishu delivery into the execution pipeline

**Files:**
- Modify: `src/zotero_arxiv_daily/main.py`
- Modify: `src/zotero_arxiv_daily/executor.py`
- Modify: `config/base.yaml`, `config/custom.yaml`
- Modify: `tests/test_main.py`
- Modify: `tests/test_executor.py`
- Modify: `tests/conftest.py`
- Modify: `tests/canned_responses.py`

- [ ] **Step 1: Update the config fixture first**

Before composing test overrides, replace the `email` node in `config/base.yaml` and `config/custom.yaml` with the five-key `feishu` node. This ensures Hydra accepts the fixture overrides and gives the composition root a concrete `config.feishu` object.

Replace email overrides with:

```python
"feishu.app_id=cli_test",
"feishu.app_secret=test-secret",
"feishu.app_token=test-app-token",
"feishu.table_id=test-table-id",
"feishu.webhook_url=https://open.feishu.cn/open-apis/bot/v2/hook/test",
```

- [ ] **Step 2: Write failing Executor integration tests**

Inject a `StubDeliveryClient` that records `(papers, recommendation_date)`. Cover normal papers, no papers with `send_empty=false`, and no papers with `send_empty=true`. Canonical URL deduplication remains a `FeishuClient.deliver()` responsibility and is covered by Task 2 tests; `Executor` must not duplicate that logic.

- [ ] **Step 3: Update `Executor` constructor and `run()`**

```python
class Executor:
    def __init__(self, config: DictConfig, delivery_client: FeishuClient):
        self.config = config
        self.delivery_client = delivery_client
        ...

def run(self) -> None:
    ...
    if not all_papers and not self.config.executor.send_empty:
        logger.info("No new papers found. No Feishu notification will be sent.")
        return
    recommendation_date = datetime.now(ZoneInfo("Asia/Shanghai"))
    result = self.delivery_client.deliver(reranked_papers, recommendation_date)
    logger.info(
        f"Feishu delivery completed: recommended={result.recommended_count}, "
        f"inserted={result.inserted_count}"
    )
```

Remove `render_email` and `send_email` imports. Keep failures visible.

- [ ] **Step 4: Write failing main composition-root test**

Assert `main()` constructs `FeishuSettings`, creates `FeishuClient`, and passes it to `Executor` without logging secrets.

- [ ] **Step 5: Implement composition-root injection**

```python
settings = FeishuSettings.from_config(config.feishu)
delivery_client = FeishuClient(settings)
executor = Executor(config, delivery_client)
executor.run()
```

The test must assert that `recommendation_date` is timezone-aware and has the `Asia/Shanghai` zone; do not use the runner's local/UTC naive clock.

- [ ] **Step 6: Remove SMTP stubs from shared test helpers**

Delete `make_stub_smtp`; replace E2E assertions with `StubDeliveryClient` assertions.

- [ ] **Step 7: Run focused integration tests**

Run: `uv run pytest tests/test_main.py tests/test_executor.py -v`
Expected: PASS.

- [ ] **Step 8: Commit pipeline integration**

```bash
git add src/zotero_arxiv_daily/main.py src/zotero_arxiv_daily/executor.py config/base.yaml config/custom.yaml tests/test_main.py tests/test_executor.py tests/conftest.py tests/canned_responses.py
git commit -m "feat: deliver recommendations through Feishu"
```

### Task 4: Remove the obsolete email implementation

**Files:**
- Modify: `src/zotero_arxiv_daily/utils.py`
- Modify: `tests/test_utils.py`
- Delete: `src/zotero_arxiv_daily/construct_email.py`
- Delete: `tests/test_construct_email.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`

- [ ] **Step 1: Remove email tests and imports**

Delete SMTP tests from `tests/test_utils.py` and all SMTP imports/stubs. Delete `tests/test_construct_email.py` because the production renderer is removed.

- [ ] **Step 2: Remove production email code**

Delete `send_email()` and the `smtplib`/`email.*`/unused `datetime`/`DictConfig` imports from `utils.py`. Delete `construct_email.py`.

- [ ] **Step 3: Remove obsolete dependency**

Delete `aiosmtpd` from `pyproject.toml` and run `uv lock`.

- [ ] **Step 4: Verify no email symbols remain**

Run: `rg -n "send_email|render_email|smtplib|SENDER_PASSWORD|RECEIVER|smtp_server" src tests pyproject.toml`
Expected: no matches.

- [ ] **Step 5: Run affected tests**

Run: `uv run pytest tests/test_utils.py tests/test_executor.py -v`
Expected: PASS.

- [ ] **Step 6: Commit cleanup**

```bash
git add -A src/zotero_arxiv_daily tests pyproject.toml uv.lock
git commit -m "refactor: remove SMTP email delivery"
```

### Task 5: Update GitHub Actions

**Files:**
- Modify: `.github/workflows/main.yml`
- Modify: `.github/workflows/test.yml`
- Create: `tests/test_workflow_config.py`

- [ ] **Step 1: Write failing static workflow tests**

Load both workflow YAML files as text and assert they contain `FEISHU_APP_ID`, `FEISHU_APP_SECRET`, `FEISHU_WEBHOOK_URL`; assert email secret names are absent. The Hydra configuration was migrated in Task 3.

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run pytest tests/test_workflow_config.py -v`
Expected: FAIL while workflows/config still use email.

- [ ] **Step 3: Update both workflows**

Inject only `FEISHU_APP_ID`, `FEISHU_APP_SECRET`, `FEISHU_WEBHOOK_URL` plus existing Zotero/OpenAI variables. Rename workflow/job labels from email wording to Feishu delivery wording.

- [ ] **Step 4: Run static tests and verify GREEN**

Run: `uv run pytest tests/test_workflow_config.py -v`
Expected: PASS.

- [ ] **Step 5: Commit deployment configuration**

```bash
git add .github/workflows tests/test_workflow_config.py
git commit -m "ci: configure Feishu delivery"
```

### Task 6: Update user and contributor documentation

**Files:**
- Modify: `README.md`
- Modify: `.github/copilot-instructions.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Rewrite the Quick Start secret table**

Document `ZOTERO_ID`, `ZOTERO_KEY`, OpenAI-compatible credentials, `FEISHU_APP_ID`, `FEISHU_APP_SECRET`, and `FEISHU_WEBHOOK_URL`. Explicitly state that SMTP secrets are no longer used.

- [ ] **Step 2: Replace the `CUSTOM_CONFIG` example**

Use the created values:

```yaml
feishu:
  app_id: ${oc.env:FEISHU_APP_ID}
  app_secret: ${oc.env:FEISHU_APP_SECRET}
  app_token: VifgbgBseaSpyIsCpH8cIlqVnub
  table_id: tblphxHROAQPFf4k
  webhook_url: ${oc.env:FEISHU_WEBHOOK_URL}
```

- [ ] **Step 3: Document Feishu setup and runtime behavior**

Cover self-built app permissions, publication, adding the app as a Bitable collaborator, group custom bot creation, URL deduplication, table idempotency, at-least-once group notification, and Beijing-time schedule.

- [ ] **Step 4: Update architecture notes**

Replace “Render + send email” with schema validation, Bitable persistence, and group notification in contributor docs.

- [ ] **Step 5: Verify documentation references**

Run: `rg -n "SENDER|SENDER_PASSWORD|RECEIVER|smtp|send email|email delivery" README.md CLAUDE.md .github/copilot-instructions.md`
Expected: no obsolete setup instructions; historical wording only if explicitly marked as removed.

- [ ] **Step 6: Commit documentation**

```bash
git add README.md CLAUDE.md .github/copilot-instructions.md
git commit -m "docs: document Feishu deployment"
```

### Task 7: Full verification and fork handoff

**Files:**
- Review all changed files.

- [ ] **Step 1: Run the complete automated test suite**

Run with a 60-second timeout: `uv run pytest`
Expected: all non-slow tests PASS, zero failures.

- [ ] **Step 2: Run Python compilation**

Run: `uv run python -m compileall src tests`
Expected: exit code 0.

- [ ] **Step 3: Audit metrics and obsolete references**

Run source checks for files over 500 lines, functions over 50 lines, email symbols, hardcoded secrets, and accidental Webhook URLs. Split any production function/file that violates the project limits.

- [ ] **Step 4: Review the final diff**

Run: `git status --short`, `git diff --check`, `git diff origin/main...HEAD --stat`, and `git diff origin/main...HEAD`.
Expected: only Feishu delivery changes plus the approved design/plan documents.

- [ ] **Step 5: Add the user Fork remote without replacing upstream**

```bash
git remote add fork https://github.com/cici-wst/zotero-arxiv-daily.git
git remote -v
```

- [ ] **Step 6: Push the verified feature branch**

```bash
git push -u fork feat/feishu-delivery
```

Expected: branch is available in `cici-wst/zotero-arxiv-daily`; do not force-push or overwrite `main`.
