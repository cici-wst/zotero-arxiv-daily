import pytest
import json
import numpy as np
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from zotero_arxiv_daily.feishu import (
    FeishuApiError,
    FeishuClient,
    FeishuSettings,
    EXPECTED_FIELD_TYPES,
    build_notification_payloads,
    deduplicate_papers,
    normalize_paper_url,
    paper_to_record_fields,
)
from tests.canned_responses import make_sample_paper


@pytest.mark.parametrize(
    ("raw_url", "expected"),
    [
        (
            "https://ARXIV.org/pdf/2601.00001v2.pdf?download=1#page=2",
            "https://arxiv.org/abs/2601.00001",
        ),
        (
            "https://arxiv.org/html/hep-th/9901001v3",
            "https://arxiv.org/abs/hep-th/9901001",
        ),
        (
            "https://www.biorxiv.org/content/10.1101/2026.01.01.123456v3.full.pdf",
            "https://doi.org/10.1101/2026.01.01.123456",
        ),
        (
            "https://www.medrxiv.org/content/10.1101/2026.02.02.654321v1/",
            "https://doi.org/10.1101/2026.02.02.654321",
        ),
        (
            "HTTPS://Example.COM/Paper/?download=1#top",
            "https://example.com/Paper",
        ),
    ],
)
def test_normalize_paper_url(raw_url: str, expected: str):
    assert normalize_paper_url(raw_url) == expected


def test_paper_to_record_fields_maps_paper_and_shanghai_date():
    paper = make_sample_paper(
        authors=["Author A", "Author B"],
        tldr="A concise summary.",
        score=8.5,
        published_at=datetime(2026, 8, 10, 12, 30, tzinfo=timezone.utc),
    )
    recommendation_date = datetime(2026, 8, 11, 14, 30, tzinfo=ZoneInfo("Asia/Shanghai"))

    fields = paper_to_record_fields(paper, recommendation_date)

    assert fields == {
        "标题": "Sample Paper Title",
        "作者": "Author A, Author B",
        "摘要": "This paper explores a novel approach to widget engineering.",
        "TLDR": "A concise summary.",
        "来源": "arxiv",
        "相关度": 8.5,
        "发布日期": 1786365000000,
        "推荐日期": 1786377600000,
        "论文URL": "https://arxiv.org/abs/2026.00001",
        "论文链接": {"text": "打开论文", "link": "https://arxiv.org/abs/2026.00001"},
    }
    assert list(fields)[-2:] == ["论文URL", "论文链接"]


def test_paper_to_record_fields_converts_numpy_score_to_json_number():
    paper = make_sample_paper(score=np.float32(8.5))
    recommendation_date = datetime(2026, 8, 11, tzinfo=ZoneInfo("Asia/Shanghai"))

    fields = paper_to_record_fields(paper, recommendation_date)

    assert fields["相关度"] == 8.5
    assert isinstance(fields["相关度"], float)
    json.dumps(fields)


def test_deduplicate_papers_uses_canonical_url_and_keeps_first():
    first = make_sample_paper(url="https://arxiv.org/abs/2601.00001v2", title="First")
    duplicate = make_sample_paper(url="https://arxiv.org/pdf/2601.00001.pdf", title="Second")

    result = deduplicate_papers([first, duplicate])

    assert result == [first]


def test_notification_payloads_fit_limit_and_include_table_link():
    papers = [
        make_sample_paper(title=f"Paper {index}", tldr="Summary " * 20)
        for index in range(3)
    ]

    payloads = build_notification_payloads(
        papers,
        inserted_count=2,
        table_url="https://my.feishu.cn/base/example",
        max_body_bytes=900,
    )

    assert len(payloads) > 1
    assert all(_payload_size(payload) <= 900 for payload in payloads)
    combined = json.dumps(payloads, ensure_ascii=False)
    assert "Paper 0" in combined
    assert "https://my.feishu.cn/base/example" in combined
    assert "完整内容见多维表格" not in combined


def test_notification_payload_truncates_only_tldr_when_one_paper_is_too_large():
    paper = make_sample_paper(title="Large Paper", tldr="长摘要" * 2000)

    payloads = build_notification_payloads(
        [paper],
        inserted_count=1,
        table_url="https://my.feishu.cn/base/example",
        max_body_bytes=900,
    )

    serialized = json.dumps(payloads, ensure_ascii=False)
    assert _payload_size(payloads[0]) <= 900
    assert "完整内容见多维表格" in serialized


def test_notification_payload_size_matches_requests_json_encoding():
    paper = make_sample_paper(title="中文标题", tldr="中文摘要" * 2000)

    payloads = build_notification_payloads(
        [paper],
        inserted_count=1,
        table_url="https://my.feishu.cn/base/example",
        max_body_bytes=900,
    )

    assert all(_payload_size(payload) <= 900 for payload in payloads)


def test_notification_payload_rejects_when_truncation_marker_cannot_fit():
    paper = make_sample_paper(title="T" * 120, tldr="摘要" * 100)

    with pytest.raises(ValueError, match="truncation marker"):
        build_notification_payloads(
            [paper],
            inserted_count=1,
            table_url="https://my.feishu.cn/base/example",
            max_body_bytes=800,
        )


def test_notification_payload_escapes_untrusted_lark_markdown():
    paper = make_sample_paper(
        title="<at id=all>全体成员</at> **伪标题**",
        tldr="[伪链接](https://example.com)",
    )

    serialized = json.dumps(
        build_notification_payloads(
            [paper],
            inserted_count=1,
            table_url="https://my.feishu.cn/base/example",
        ),
        ensure_ascii=False,
    )

    assert "<at id=all>" not in serialized
    content = build_notification_payloads(
        [paper],
        inserted_count=1,
        table_url="https://my.feishu.cn/base/example",
    )[0]["card"]["elements"][1]["text"]["content"]
    assert "\\*\\*伪标题\\*\\*" in content
    assert "\\[伪链接\\]\\(https://example\\.com\\)" in content


def test_empty_notification_uses_explicit_no_papers_message():
    payload = build_notification_payloads(
        [],
        inserted_count=0,
        table_url="https://my.feishu.cn/base/example",
    )[0]

    assert "今日无新论文" in json.dumps(payload, ensure_ascii=False)


def test_notification_payload_raises_when_fixed_content_cannot_fit():
    paper = make_sample_paper(title="T" * 2000, tldr="")

    with pytest.raises(ValueError, match="fixed content"):
        build_notification_payloads(
            [paper],
            inserted_count=1,
            table_url="https://my.feishu.cn/base/example",
            max_body_bytes=200,
        )


def _payload_size(payload: dict[str, object]) -> int:
    return len(json.dumps(payload).encode("utf-8"))


def _settings() -> FeishuSettings:
    return FeishuSettings(
        app_id="cli-test",
        app_secret="secret-test",
        app_token="app-test",
        table_id="table-test",
        webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/test",
    )


class StubResponse:
    def __init__(self, payload: dict[str, object], status_code: int = 200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self.payload


class StubSession:
    def __init__(self, handler):
        self.handler = handler
        self.calls: list[dict[str, object]] = []

    def request(self, method, url, **kwargs):
        call = {"method": method, "url": url, **kwargs}
        self.calls.append(call)
        return self.handler(method, url, kwargs)


def _success_response(data: dict[str, object] | None = None):
    return StubResponse({"code": 0, "msg": "success", "data": data or {}})


def _token_response():
    return StubResponse({"code": 0, "msg": "success", "tenant_access_token": "tenant-token", "expire": 7200})


def _field_items():
    return [
        {"field_name": name, "type": field_type}
        for name, field_type in EXPECTED_FIELD_TYPES.items()
    ]


def test_expected_schema_excludes_removed_fields_and_places_urls_last():
    assert "作者单位" not in EXPECTED_FIELD_TYPES
    assert "分类" not in EXPECTED_FIELD_TYPES
    assert "代码链接" not in EXPECTED_FIELD_TYPES
    assert list(EXPECTED_FIELD_TYPES)[-2:] == ["论文URL", "论文链接"]


def test_feishu_client_caches_tenant_token():
    def handler(method, url, kwargs):
        assert method == "POST"
        assert url.endswith("/auth/v3/tenant_access_token/internal")
        assert kwargs["json"] == {"app_id": "cli-test", "app_secret": "secret-test"}
        return _token_response()

    session = StubSession(handler)
    client = FeishuClient(_settings(), session=session)

    assert client._get_tenant_token() == "tenant-token"
    assert client._get_tenant_token() == "tenant-token"
    assert len(session.calls) == 1


def test_feishu_client_rejects_api_error_code():
    session = StubSession(lambda *_: StubResponse({"code": 999, "msg": "denied"}))
    client = FeishuClient(_settings(), session=session)

    with pytest.raises(FeishuApiError, match="denied"):
        client._get_tenant_token()


def test_feishu_client_exposes_http_errors_without_credentials():
    session = StubSession(lambda *_: StubResponse({}, status_code=500))
    client = FeishuClient(_settings(), session=session)

    with pytest.raises(FeishuApiError) as error:
        client._get_tenant_token()

    assert "secret-test" not in str(error.value)


def test_feishu_client_rejects_missing_tenant_token():
    session = StubSession(lambda *_: _success_response())
    client = FeishuClient(_settings(), session=session)

    with pytest.raises(FeishuApiError, match="missing tenant_access_token"):
        client._get_tenant_token()


def test_validate_table_schema_checks_all_expected_fields():
    def handler(method, url, kwargs):
        if url.endswith("/auth/v3/tenant_access_token/internal"):
            return _token_response()
        assert method == "GET"
        return _success_response({"items": _field_items(), "has_more": False})

    client = FeishuClient(_settings(), session=StubSession(handler))

    assert client.validate_table_schema() is None


def test_validate_table_schema_names_the_missing_field():
    fields = [item for item in _field_items() if item["field_name"] != "标题"]

    def handler(method, url, kwargs):
        if url.endswith("/auth/v3/tenant_access_token/internal"):
            return _token_response()
        return _success_response({"items": fields, "has_more": False})

    client = FeishuClient(_settings(), session=StubSession(handler))

    with pytest.raises(FeishuApiError, match="标题"):
        client.validate_table_schema()


def test_list_existing_urls_follows_pagination():
    def handler(method, url, kwargs):
        if url.endswith("/auth/v3/tenant_access_token/internal"):
            return _token_response()
        assert method == "POST"
        if kwargs["params"].get("page_token") == "next":
            return _success_response({"items": [{"fields": {"论文URL": "https://arxiv.org/abs/2"}}], "has_more": False})
        return _success_response({
            "items": [{"fields": {"论文URL": "https://arxiv.org/pdf/1.pdf"}}],
            "has_more": True,
            "page_token": "next",
        })

    client = FeishuClient(_settings(), session=StubSession(handler))

    result = client.list_existing_urls()

    assert result == frozenset({"https://arxiv.org/abs/1", "https://arxiv.org/abs/2"})
    assert isinstance(result, frozenset)


def test_list_existing_urls_rejects_malformed_url_field():
    def handler(method, url, kwargs):
        if url.endswith("/auth/v3/tenant_access_token/internal"):
            return _token_response()
        return _success_response({
            "items": [{"fields": {"论文URL": {"text": "not-a-string"}}}],
            "has_more": False,
        })

    client = FeishuClient(_settings(), session=StubSession(handler))

    with pytest.raises(FeishuApiError, match="论文URL"):
        client.list_existing_urls()


def test_batch_create_records_skips_request_for_empty_input():
    session = StubSession(lambda *_: pytest.fail("empty input must not make an HTTP request"))
    client = FeishuClient(_settings(), session=session)

    assert client.batch_create_records([]) == 0
    assert session.calls == []


def test_batch_create_records_chunks_at_api_limit():
    calls = []

    def handler(method, url, kwargs):
        if url.endswith("/auth/v3/tenant_access_token/internal"):
            return _token_response()
        calls.append(kwargs["json"])
        records = [
            {"record_id": f"rec-{index}", "fields": record["fields"]}
            for index, record in enumerate(kwargs["json"]["records"])
        ]
        return _success_response({"records": records})

    client = FeishuClient(_settings(), session=StubSession(handler))
    records = [{"标题": str(index), "论文URL": f"https://example.com/{index}"} for index in range(1001)]

    assert client.batch_create_records(records) == 1001
    assert [len(call["records"]) for call in calls] == [1000, 1]


def test_batch_create_records_exposes_second_batch_error():
    batch_count = 0

    def handler(method, url, kwargs):
        nonlocal batch_count
        if url.endswith("/auth/v3/tenant_access_token/internal"):
            return _token_response()
        batch_count += 1
        if batch_count == 2:
            return StubResponse({"code": 999, "msg": "second batch denied"})
        records = [
            {"record_id": f"rec-{index}", "fields": record["fields"]}
            for index, record in enumerate(kwargs["json"]["records"])
        ]
        return _success_response({"records": records})

    client = FeishuClient(_settings(), session=StubSession(handler))
    records = [{"标题": str(index)} for index in range(1001)]

    with pytest.raises(FeishuApiError, match="second batch denied"):
        client.batch_create_records(records)


def test_batch_create_records_rejects_missing_created_records():
    def handler(method, url, kwargs):
        if url.endswith("/auth/v3/tenant_access_token/internal"):
            return _token_response()
        return _success_response({})

    client = FeishuClient(_settings(), session=StubSession(handler))

    with pytest.raises(FeishuApiError, match="records"):
        client.batch_create_records([{"标题": "Paper"}])


@pytest.mark.parametrize(
    "created_record",
    [
        {},
        {"record_id": "rec-1"},
        {"fields": {"标题": "Paper"}},
        {"record_id": "", "fields": {"标题": "Paper"}},
    ],
)
def test_batch_create_records_rejects_malformed_created_record(created_record):
    def handler(method, url, kwargs):
        if url.endswith("/auth/v3/tenant_access_token/internal"):
            return _token_response()
        return _success_response({"records": [created_record]})

    client = FeishuClient(_settings(), session=StubSession(handler))

    with pytest.raises(FeishuApiError, match="created record"):
        client.batch_create_records([{"标题": "Paper"}])


def test_send_notification_posts_each_card_and_requires_success():
    def handler(method, url, kwargs):
        assert method == "POST"
        assert url == _settings().webhook_url
        return _success_response()

    client = FeishuClient(_settings(), session=StubSession(handler))
    paper = make_sample_paper(tldr="A summary")

    assert client.send_notification([paper], inserted_count=1) == 1


def test_send_notification_hides_webhook_url_when_api_rejects_request():
    client = FeishuClient(
        _settings(),
        session=StubSession(lambda *_: StubResponse({"code": 999, "msg": "rejected"})),
    )

    with pytest.raises(FeishuApiError) as error:
        client.send_notification([make_sample_paper()], inserted_count=0)

    assert "group webhook" in str(error.value)
    assert _settings().webhook_url not in str(error.value)


class RecordingDeliveryClient(FeishuClient):
    def __init__(self, existing_urls=frozenset()):
        super().__init__(_settings(), session=StubSession(lambda *_: _success_response()))
        self.existing_urls = set(existing_urls)
        self.schema_validation_count = 0
        self.existing_url_query_count = 0
        self.created_records: list[dict[str, object]] = []
        self.notifications: list[tuple[list[object], int]] = []

    def validate_table_schema(self):
        self.schema_validation_count += 1

    def list_existing_urls(self):
        self.existing_url_query_count += 1
        return set(self.existing_urls)

    def batch_create_records(self, records):
        self.created_records.extend(records)
        return len(records)

    def send_notification(self, papers, inserted_count):
        self.notifications.append((list(papers), inserted_count))
        return 1


def _recommendation_date():
    return datetime(2026, 8, 11, 14, 30, tzinfo=ZoneInfo("Asia/Shanghai"))


def test_deliver_empty_list_skips_table_calls_and_sends_empty_notification():
    client = RecordingDeliveryClient()

    result = client.deliver([], _recommendation_date())

    assert result.recommended_count == 0
    assert result.inserted_count == 0
    assert client.schema_validation_count == 0
    assert client.existing_url_query_count == 0
    assert client.created_records == []
    assert client.notifications == [([], 0)]
    with pytest.raises(FrozenInstanceError):
        result.inserted_count = 1


def test_deliver_deduplicates_url_variants_within_the_same_batch():
    first = make_sample_paper(url="https://arxiv.org/abs/2601.00001v2", title="First")
    duplicate = make_sample_paper(url="https://arxiv.org/pdf/2601.00001.pdf", title="Duplicate")
    client = RecordingDeliveryClient()

    result = client.deliver([first, duplicate], _recommendation_date())

    assert result.recommended_count == 1
    assert result.inserted_count == 1
    assert [record["标题"] for record in client.created_records] == ["First"]
    assert client.notifications == [([first], 1)]


def test_deliver_does_not_insert_papers_already_in_the_table():
    paper = make_sample_paper(url="https://arxiv.org/pdf/2601.00001v3.pdf")
    client = RecordingDeliveryClient(existing_urls={"https://arxiv.org/abs/2601.00001"})

    result = client.deliver([paper], _recommendation_date())

    assert result.recommended_count == 1
    assert result.inserted_count == 0
    assert client.created_records == []
    assert client.notifications == [([paper], 0)]


def test_deliver_inserts_only_papers_missing_from_the_table():
    existing = make_sample_paper(url="https://arxiv.org/abs/2601.00001", title="Existing")
    new_one = make_sample_paper(url="https://example.com/new-one", title="New One")
    new_two = make_sample_paper(url="https://example.com/new-two", title="New Two")
    client = RecordingDeliveryClient(existing_urls={"https://arxiv.org/abs/2601.00001"})

    result = client.deliver([existing, new_one, new_two], _recommendation_date())

    assert result.recommended_count == 3
    assert result.inserted_count == 2
    assert [record["标题"] for record in client.created_records] == ["New One", "New Two"]
    assert client.notifications == [([existing, new_one, new_two], 2)]
