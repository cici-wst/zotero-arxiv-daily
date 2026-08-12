from __future__ import annotations

import json
import re
from typing import Callable, Sequence

from loguru import logger

from .protocol import Paper


MAX_WEBHOOK_BODY_BYTES = 20 * 1024
_TRUNCATION_MARKER = "\n…（完整内容见多维表格）"
_MARKDOWN_SPECIAL_RE = re.compile(r"([\\`*_{}\[\]()#+\-.!|<>])")


def _escape_lark_markdown(value: str) -> str:
    return _MARKDOWN_SPECIAL_RE.sub(r"\\\1", value)


def _paper_block(
    paper: Paper,
    normalize_url: Callable[[str], str],
    tldr: str | None = None,
) -> dict[str, object]:
    canonical_url = normalize_url(paper.url)
    summary = paper.tldr or "" if tldr is None else tldr
    safe_title = _escape_lark_markdown(paper.title)
    safe_summary = _escape_lark_markdown(summary)
    content = f"**{safe_title}**\n{safe_summary}\n[查看论文]({canonical_url})"
    return {"tag": "div", "text": {"tag": "lark_md", "content": content}}


def _card_payload(
    blocks: list[dict[str, object]],
    *,
    recommended_count: int,
    inserted_count: int,
    table_url: str,
) -> dict[str, object]:
    summary = (
        "今日无新论文。"
        if recommended_count == 0
        else f"今日推荐 {recommended_count} 篇，新增入表 {inserted_count} 篇。"
    )
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
    return len(json.dumps(payload).encode("utf-8"))


def _paper_payload(
    paper: Paper,
    normalize_url: Callable[[str], str],
    tldr: str,
    *,
    recommended_count: int,
    inserted_count: int,
    table_url: str,
) -> dict[str, object]:
    block = _paper_block(paper, normalize_url, tldr)
    return _card_payload(
        [block],
        recommended_count=recommended_count,
        inserted_count=inserted_count,
        table_url=table_url,
    )


def _fit_single_paper_block(
    paper: Paper,
    normalize_url: Callable[[str], str],
    *,
    recommended_count: int,
    inserted_count: int,
    table_url: str,
    max_body_bytes: int,
) -> dict[str, object]:
    fixed_payload = _paper_payload(
        paper,
        normalize_url,
        "",
        recommended_count=recommended_count,
        inserted_count=inserted_count,
        table_url=table_url,
    )
    if _payload_size(fixed_payload) > max_body_bytes:
        raise ValueError("notification fixed content exceeds the webhook body limit")
    marker_payload = _paper_payload(
        paper,
        normalize_url,
        _TRUNCATION_MARKER,
        recommended_count=recommended_count,
        inserted_count=inserted_count,
        table_url=table_url,
    )
    if _payload_size(marker_payload) > max_body_bytes:
        raise ValueError("notification truncation marker exceeds the webhook body limit")
    original = paper.tldr or ""
    low, high = 0, len(original)
    while low < high:
        middle = (low + high + 1) // 2
        candidate = original[:middle] + _TRUNCATION_MARKER
        payload = _paper_payload(
            paper,
            normalize_url,
            candidate,
            recommended_count=recommended_count,
            inserted_count=inserted_count,
            table_url=table_url,
        )
        if _payload_size(payload) <= max_body_bytes:
            low = middle
        else:
            high = middle - 1
    logger.warning(f"Truncated Feishu notification TLDR for paper: {paper.title}")
    return _paper_block(paper, normalize_url, original[:low] + _TRUNCATION_MARKER)


def _limited_paper_block(
    paper: Paper,
    normalize_url: Callable[[str], str],
    *,
    recommended_count: int,
    inserted_count: int,
    table_url: str,
    max_body_bytes: int,
) -> dict[str, object]:
    block = _paper_block(paper, normalize_url)
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
        normalize_url,
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
    normalize_url: Callable[[str], str],
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
        candidate = [*blocks, _paper_block(paper, normalize_url)]
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
        blocks = [_limited_paper_block(
            paper,
            normalize_url,
            recommended_count=len(papers),
            inserted_count=inserted_count,
            table_url=table_url,
            max_body_bytes=max_body_bytes,
        )]
    payloads.append(_card_payload(
        blocks,
        recommended_count=len(papers),
        inserted_count=inserted_count,
        table_url=table_url,
    ))
    return payloads
