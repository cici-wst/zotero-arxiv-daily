from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Mapping, Sequence
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4
from zoneinfo import ZoneInfo

import requests
from loguru import logger
from omegaconf import DictConfig

from .protocol import Paper


_ARXIV_PATH_RE = re.compile(r"^/(?:abs|pdf|html|e-print)/(.+?)(?:\.pdf)?$")
_ARXIV_VERSION_RE = re.compile(r"v\d+$", re.IGNORECASE)
_PREPRINT_PATH_RE = re.compile(r"^/content/(10\.1101/.+?)(?:v\d+)(?:\.full\.pdf)?$")
_SHANGHAI_TIME_ZONE = ZoneInfo("Asia/Shanghai")
MAX_WEBHOOK_BODY_BYTES = 20 * 1024
HTTP_TIMEOUT_SECONDS = 30
BITABLE_BATCH_LIMIT = 1000
_TRUNCATION_MARKER = "\n…（完整内容见多维表格）"
_OPEN_API_BASE = "https://open.feishu.cn/open-apis"
EXPECTED_FIELD_TYPES: Mapping[str, int] = MappingProxyType({
    "标题": 1,
    "论文URL": 1,
    "论文链接": 15,
    "作者": 1,
    "摘要": 1,
    "TLDR": 1,
    "作者单位": 1,
    "来源": 3,
    "分类": 4,
    "相关度": 2,
    "发布日期": 5,
    "推荐日期": 5,
    "代码链接": 15,
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
        "论文URL": canonical_url,
        "论文链接": {"text": "打开论文", "link": canonical_url},
        "作者": ", ".join(paper.authors),
        "摘要": paper.abstract,
        "TLDR": paper.tldr or "",
        "作者单位": ", ".join(paper.affiliations or []),
        "来源": paper.source,
        "推荐日期": _shanghai_midnight_ms(recommendation_date),
    }
    if paper.score is not None:
        fields["相关度"] = paper.score
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


def _paper_block(paper: Paper, tldr: str | None = None) -> dict[str, object]:
    canonical_url = normalize_paper_url(paper.url)
    summary = paper.tldr or "" if tldr is None else tldr
    content = f"**{paper.title}**\n{summary}\n[查看论文]({canonical_url})"
    return {"tag": "div", "text": {"tag": "lark_md", "content": content}}


def _card_payload(
    blocks: list[dict[str, object]],
    *,
    recommended_count: int,
    inserted_count: int,
    table_url: str,
) -> dict[str, object]:
    summary = f"今日推荐 {recommended_count} 篇，新增入表 {inserted_count} 篇。"
    elements = [{"tag": "div", "text": {"tag": "plain_text", "content": summary}}, *blocks]
    elements.append({
        "tag": "action",
        "actions": [{
            "tag": "button",
            "text": {"tag": "plain_text", "content": "打开多维表格"},
            "url": table_url,
            "type": "primary",
        }],
    })
    return {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {"title": {"tag": "plain_text", "content": "每日论文推荐"}},
            "elements": elements,
        },
    }


def _payload_size(payload: dict[str, object]) -> int:
    return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def _fit_single_paper_block(
    paper: Paper,
    *,
    recommended_count: int,
    inserted_count: int,
    table_url: str,
    max_body_bytes: int,
) -> dict[str, object]:
    empty_payload = _card_payload(
        [_paper_block(paper, "")],
        recommended_count=recommended_count,
        inserted_count=inserted_count,
        table_url=table_url,
    )
    if _payload_size(empty_payload) > max_body_bytes:
        raise ValueError("notification fixed content exceeds the webhook body limit")
    original = paper.tldr or ""
    low, high = 0, len(original)
    while low < high:
        middle = (low + high + 1) // 2
        block = _paper_block(paper, original[:middle] + _TRUNCATION_MARKER)
        payload = _card_payload(
            [block],
            recommended_count=recommended_count,
            inserted_count=inserted_count,
            table_url=table_url,
        )
        if _payload_size(payload) <= max_body_bytes:
            low = middle
        else:
            high = middle - 1
    logger.warning(f"Truncated Feishu notification TLDR for paper: {paper.title}")
    return _paper_block(paper, original[:low] + _TRUNCATION_MARKER)


def _single_paper_block_within_limit(
    paper: Paper,
    *,
    recommended_count: int,
    inserted_count: int,
    table_url: str,
    max_body_bytes: int,
) -> dict[str, object]:
    block = _paper_block(paper)
    payload = _card_payload(
        [block],
        recommended_count=recommended_count,
        inserted_count=inserted_count,
        table_url=table_url,
    )
    if _payload_size(payload) <= max_body_bytes:
        return block
    return _fit_single_paper_block(
        paper,
        recommended_count=recommended_count,
        inserted_count=inserted_count,
        table_url=table_url,
        max_body_bytes=max_body_bytes,
    )


def build_notification_payloads(
    papers: Sequence[Paper],
    inserted_count: int,
    table_url: str,
    *,
    max_body_bytes: int = MAX_WEBHOOK_BODY_BYTES,
) -> list[dict[str, object]]:
    if not papers:
        return [_card_payload(
            [],
            recommended_count=0,
            inserted_count=inserted_count,
            table_url=table_url,
        )]
    payloads: list[dict[str, object]] = []
    blocks: list[dict[str, object]] = []
    for paper in papers:
        candidate = [*blocks, _paper_block(paper)]
        payload = _card_payload(
            candidate,
            recommended_count=len(papers),
            inserted_count=inserted_count,
            table_url=table_url,
        )
        if _payload_size(payload) <= max_body_bytes:
            blocks = candidate
            continue
        if blocks:
            payloads.append(_card_payload(
                blocks,
                recommended_count=len(papers),
                inserted_count=inserted_count,
                table_url=table_url,
            ))
        fitted = _single_paper_block_within_limit(
            paper,
            recommended_count=len(papers),
            inserted_count=inserted_count,
            table_url=table_url,
            max_body_bytes=max_body_bytes,
        )
        blocks = [fitted]
    payloads.append(_card_payload(
        blocks,
        recommended_count=len(papers),
        inserted_count=inserted_count,
        table_url=table_url,
    ))
    return payloads


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
            params: dict[str, object] = {"page_size": 100}
            if page_token:
                params["page_token"] = page_token
            payload = self._api_request("GET", self._table_path("fields"), params=params)
            data = self._response_data(payload, "field list")
            items = data.get("items")
            if not isinstance(items, list):
                raise FeishuApiError("Feishu field list response has invalid items")
            self._collect_field_types(items, actual_types)
            if not data.get("has_more"):
                break
            page_token = self._require_page_token(data, "field list")
        self._check_field_types(actual_types)

    def _collect_field_types(self, items: list[object], output: dict[str, int]) -> None:
        for item in items:
            if not isinstance(item, dict):
                raise FeishuApiError("Feishu field list contains an invalid item")
            name, field_type = item.get("field_name"), item.get("type")
            if not isinstance(name, str) or not isinstance(field_type, int):
                raise FeishuApiError("Feishu field metadata is malformed")
            output[name] = field_type

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
            params: dict[str, object] = {"page_size": 500}
            if page_token:
                params["page_token"] = page_token
            payload = self._api_request(
                "POST",
                self._table_path("records/search"),
                params=params,
                json_body={"field_names": ["论文URL"]},
            )
            data = self._response_data(payload, "record search")
            self._collect_record_urls(data.get("items"), existing)
            if not data.get("has_more"):
                return frozenset(existing)
            page_token = self._require_page_token(data, "record search")

    def _collect_record_urls(self, items: object, output: set[str]) -> None:
        if not isinstance(items, list):
            raise FeishuApiError("Feishu record search response has invalid items")
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("fields"), dict):
                raise FeishuApiError("Feishu record search contains an invalid record")
            value = item["fields"].get("论文URL")
            if not isinstance(value, str) or not value:
                raise FeishuApiError("Feishu record is missing a text 论文URL")
            output.add(normalize_paper_url(value))

    def batch_create_records(self, records: Sequence[dict[str, object]]) -> int:
        for start in range(0, len(records), BITABLE_BATCH_LIMIT):
            batch = records[start:start + BITABLE_BATCH_LIMIT]
            self._api_request(
                "POST",
                self._table_path("records/batch_create"),
                params={"client_token": str(uuid4())},
                json_body={"records": [{"fields": fields} for fields in batch]},
            )
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
