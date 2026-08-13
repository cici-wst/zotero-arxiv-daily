from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Mapping, Sequence
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4
from zoneinfo import ZoneInfo

import requests
from omegaconf import DictConfig

from .feishu_cards import MAX_WEBHOOK_BODY_BYTES
from .feishu_cards import build_notification_payloads as _build_notification_payloads
from .protocol import Paper


_ARXIV_PATH_RE = re.compile(r"^/(?:abs|pdf|html|e-print)/(.+?)(?:\.pdf)?$")
_ARXIV_VERSION_RE = re.compile(r"v\d+$", re.IGNORECASE)
_PREPRINT_PATH_RE = re.compile(r"^/content/(10\.1101/.+?)(?:v\d+)(?:\.full\.pdf)?$")
_SHANGHAI_TIME_ZONE = ZoneInfo("Asia/Shanghai")
HTTP_TIMEOUT_SECONDS = 30
BITABLE_BATCH_LIMIT = 1000
FIELD_PAGE_SIZE = 100
RECORD_PAGE_SIZE = 500
FIELD_TYPE_TEXT = 1
FIELD_TYPE_NUMBER = 2
FIELD_TYPE_SINGLE_SELECT = 3
FIELD_TYPE_MULTI_SELECT = 4
FIELD_TYPE_DATE = 5
FIELD_TYPE_URL = 15
_OPEN_API_BASE = "https://open.feishu.cn/open-apis"
EXPECTED_FIELD_TYPES: Mapping[str, int] = MappingProxyType({
    "标题": FIELD_TYPE_TEXT,
    "作者": FIELD_TYPE_TEXT,
    "摘要": FIELD_TYPE_TEXT,
    "TLDR": FIELD_TYPE_TEXT,
    "相关度": FIELD_TYPE_NUMBER,
    "发布日期": FIELD_TYPE_DATE,
    "推荐日期": FIELD_TYPE_DATE,
    "论文URL": FIELD_TYPE_TEXT,
    "论文链接": FIELD_TYPE_URL,
})


class FeishuApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class FeishuSettings:
    app_id: str
    app_secret: str
    app_token: str
    table_id: str
    webhook_url: str

    @classmethod
    def from_config(cls, config: DictConfig) -> "FeishuSettings":
        return cls(
            app_id=str(config.app_id),
            app_secret=str(config.app_secret),
            app_token=str(config.app_token),
            table_id=str(config.table_id),
            webhook_url=str(config.webhook_url),
        )


@dataclass(frozen=True)
class DeliveryResult:
    recommended_count: int
    inserted_count: int


@dataclass(frozen=True)
class RequestOptions:
    headers: Mapping[str, str] | None = None
    params: Mapping[str, object] | None = None
    json_body: object | None = None


def _extract_arxiv_id(host: str, path: str) -> str | None:
    if not host.endswith("arxiv.org"):
        return None
    match = _ARXIV_PATH_RE.match(path)
    if match is None:
        return None
    return _ARXIV_VERSION_RE.sub("", match.group(1))


def _extract_preprint_doi(host: str, path: str) -> str | None:
    if not host.endswith(("biorxiv.org", "medrxiv.org")):
        return None
    match = _PREPRINT_PATH_RE.match(path)
    return match.group(1) if match else None


def normalize_paper_url(url: str) -> str:
    parsed = urlsplit(url)
    host = parsed.netloc.lower()
    path = parsed.path.rstrip("/")
    if arxiv_id := _extract_arxiv_id(host, path):
        return f"https://arxiv.org/abs/{arxiv_id}"
    if doi := _extract_preprint_doi(host, path):
        return f"https://doi.org/{doi}"
    return urlunsplit((parsed.scheme.lower(), host, path, "", ""))


def _shanghai_midnight_ms(value: datetime) -> int:
    if value.tzinfo is None:
        raise ValueError("recommendation_date must be timezone-aware")
    local = value.astimezone(_SHANGHAI_TIME_ZONE)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(midnight.timestamp() * 1000)


def paper_to_record_fields(paper: Paper, recommendation_date: datetime) -> dict[str, object]:
    canonical_url = normalize_paper_url(paper.url)
    fields: dict[str, object] = {
        "标题": paper.title,
        "作者": ", ".join(paper.authors),
        "摘要": paper.abstract,
        "TLDR": paper.tldr or "",
        "推荐日期": _shanghai_midnight_ms(recommendation_date),
    }
    if paper.published_at is not None:
        fields["发布日期"] = int(paper.published_at.timestamp() * 1000)
    if paper.score is not None:
        fields["相关度"] = float(paper.score)
    fields["论文URL"] = canonical_url
    fields["论文链接"] = {"text": "打开论文", "link": canonical_url}
    return fields


def deduplicate_papers(papers: Sequence[Paper]) -> list[Paper]:
    seen_urls: set[str] = set()
    unique_papers: list[Paper] = []
    for paper in papers:
        canonical_url = normalize_paper_url(paper.url)
        if canonical_url in seen_urls:
            continue
        seen_urls.add(canonical_url)
        unique_papers.append(paper)
    return unique_papers


def build_notification_payloads(
    papers: Sequence[Paper],
    inserted_count: int,
    table_url: str,
    *,
    max_body_bytes: int = MAX_WEBHOOK_BODY_BYTES,
) -> list[dict[str, object]]:
    return _build_notification_payloads(
        papers,
        inserted_count,
        table_url,
        normalize_url=normalize_paper_url,
        max_body_bytes=max_body_bytes,
    )


class FeishuClient:
    def __init__(self, settings: FeishuSettings, session: requests.Session | None = None):
        self.settings = settings
        self.session = session or requests.Session()
        self._tenant_token: str | None = None

    def _request_json(self, method: str, url: str, options: RequestOptions) -> dict[str, object]:
        try:
            response = self.session.request(
                method,
                url,
                headers=options.headers,
                params=options.params,
                json=options.json_body,
                timeout=HTTP_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise FeishuApiError(f"Feishu request failed for {method} {self._safe_endpoint(url)}") from exc
        if not isinstance(payload, dict):
            raise FeishuApiError(f"Feishu returned a non-object response for {self._safe_endpoint(url)}")
        if payload.get("code") != 0:
            raise FeishuApiError(f"Feishu API error for {self._safe_endpoint(url)}: {payload.get('msg')}")
        return payload

    def _safe_endpoint(self, url: str) -> str:
        if url == self.settings.webhook_url:
            return "group webhook"
        return urlsplit(url).path

    def _get_tenant_token(self) -> str:
        if self._tenant_token is not None:
            return self._tenant_token
        url = f"{_OPEN_API_BASE}/auth/v3/tenant_access_token/internal"
        payload = self._request_json(
            "POST",
            url,
            RequestOptions(json_body={"app_id": self.settings.app_id, "app_secret": self.settings.app_secret}),
        )
        token = payload.get("tenant_access_token")
        if not isinstance(token, str) or not token:
            raise FeishuApiError("Feishu token response is missing tenant_access_token")
        self._tenant_token = token
        return token

    def _api_request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, object] | None = None,
        json_body: object | None = None,
    ) -> dict[str, object]:
        headers = {"Authorization": f"Bearer {self._get_tenant_token()}"}
        return self._request_json(
            method,
            f"{_OPEN_API_BASE}{path}",
            RequestOptions(headers=headers, params=params, json_body=json_body),
        )

    def _table_path(self, suffix: str) -> str:
        base = f"/bitable/v1/apps/{self.settings.app_token}/tables/{self.settings.table_id}"
        return f"{base}/{suffix}"

    def _response_data(self, payload: dict[str, object], endpoint: str) -> dict[str, object]:
        data = payload.get("data")
        if not isinstance(data, dict):
            raise FeishuApiError(f"Feishu {endpoint} response is missing data")
        return data

    def validate_table_schema(self) -> None:
        actual_types: dict[str, int] = {}
        page_token: str | None = None
        while True:
            params: dict[str, object] = {"page_size": FIELD_PAGE_SIZE}
            if page_token:
                params["page_token"] = page_token
            payload = self._api_request("GET", self._table_path("fields"), params=params)
            data = self._response_data(payload, "field list")
            items = data.get("items")
            if not isinstance(items, list):
                raise FeishuApiError("Feishu field list response has invalid items")
            actual_types = {**actual_types, **self._parse_field_types(items)}
            if not data.get("has_more"):
                break
            page_token = self._require_page_token(data, "field list")
        self._check_field_types(actual_types)

    def _parse_field_types(self, items: list[object]) -> dict[str, int]:
        field_types: dict[str, int] = {}
        for item in items:
            if not isinstance(item, dict):
                raise FeishuApiError("Feishu field list contains an invalid item")
            name, field_type = item.get("field_name"), item.get("type")
            if not isinstance(name, str) or not isinstance(field_type, int):
                raise FeishuApiError("Feishu field metadata is malformed")
            field_types[name] = field_type
        return field_types

    def _check_field_types(self, actual_types: Mapping[str, int]) -> None:
        for field_name, expected_type in EXPECTED_FIELD_TYPES.items():
            actual_type = actual_types.get(field_name)
            if actual_type != expected_type:
                raise FeishuApiError(
                    f"Feishu field {field_name} has type {actual_type}; expected {expected_type}"
                )

    def _require_page_token(self, data: Mapping[str, object], endpoint: str) -> str:
        token = data.get("page_token")
        if not isinstance(token, str) or not token:
            raise FeishuApiError(f"Feishu {endpoint} response is missing page_token")
        return token

    def list_existing_urls(self) -> frozenset[str]:
        existing: set[str] = set()
        page_token: str | None = None
        while True:
            params: dict[str, object] = {"page_size": RECORD_PAGE_SIZE}
            if page_token:
                params["page_token"] = page_token
            payload = self._api_request(
                "POST",
                self._table_path("records/search"),
                params=params,
                json_body={"field_names": ["论文URL"]},
            )
            data = self._response_data(payload, "record search")
            existing = existing.union(self._parse_record_urls(data.get("items")))
            if not data.get("has_more"):
                return frozenset(existing)
            page_token = self._require_page_token(data, "record search")

    def _parse_record_urls(self, items: object) -> frozenset[str]:
        if not isinstance(items, list):
            raise FeishuApiError("Feishu record search response has invalid items")
        urls: set[str] = set()
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("fields"), dict):
                raise FeishuApiError("Feishu record search contains an invalid record")
            value = item["fields"].get("论文URL")
            if not isinstance(value, str) or not value:
                raise FeishuApiError("Feishu record is missing a text 论文URL")
            urls.add(normalize_paper_url(value))
        return frozenset(urls)

    def batch_create_records(self, records: Sequence[dict[str, object]]) -> int:
        for start in range(0, len(records), BITABLE_BATCH_LIMIT):
            batch = records[start:start + BITABLE_BATCH_LIMIT]
            payload = self._api_request(
                "POST",
                self._table_path("records/batch_create"),
                params={"client_token": str(uuid4())},
                json_body={"records": [{"fields": fields} for fields in batch]},
            )
            data = self._response_data(payload, "batch create")
            created_records = data.get("records")
            if not isinstance(created_records, list) or len(created_records) != len(batch):
                raise FeishuApiError("Feishu batch create response has invalid records")
            for record in created_records:
                if not isinstance(record, dict):
                    raise FeishuApiError("Feishu batch create response has invalid created record")
                record_id = record.get("record_id")
                fields = record.get("fields")
                if not isinstance(record_id, str) or not record_id or not isinstance(fields, dict):
                    raise FeishuApiError("Feishu batch create response has invalid created record")
        return len(records)

    def send_notification(self, papers: Sequence[Paper], inserted_count: int) -> int:
        table_url = (
            f"https://my.feishu.cn/base/{self.settings.app_token}"
            f"?table={self.settings.table_id}"
        )
        payloads = build_notification_payloads(papers, inserted_count, table_url)
        for payload in payloads:
            self._request_json("POST", self.settings.webhook_url, RequestOptions(json_body=payload))
        return len(payloads)

    def deliver(
        self,
        papers: Sequence[Paper],
        recommendation_date: datetime,
    ) -> DeliveryResult:
        unique_papers = deduplicate_papers(papers)
        if not unique_papers:
            self.send_notification([], 0)
            return DeliveryResult(recommended_count=0, inserted_count=0)

        self.validate_table_schema()
        existing_urls = self.list_existing_urls()
        records = [paper_to_record_fields(paper, recommendation_date) for paper in unique_papers]
        missing_records = [
            record for record in records
            if record["论文URL"] not in existing_urls
        ]
        inserted_count = self.batch_create_records(missing_records)
        self.send_notification(unique_papers, inserted_count)
        return DeliveryResult(
            recommended_count=len(unique_papers),
            inserted_count=inserted_count,
        )
