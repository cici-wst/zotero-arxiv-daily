"""Tests for zotero_arxiv_daily.protocol.Paper.generate_tldr."""

import pytest

from tests.canned_responses import make_sample_paper, make_stub_openai_client


class StubEncoding:
    def encode(self, text: str) -> list[int]:
        return [ord(character) for character in text]

    def decode(self, tokens: list[int]) -> str:
        return "".join(chr(token) for token in tokens)


@pytest.fixture(autouse=True)
def _offline_tokenizer(monkeypatch):
    monkeypatch.setattr(
        "zotero_arxiv_daily.protocol.tiktoken.encoding_for_model",
        lambda _: StubEncoding(),
    )


@pytest.fixture()
def llm_params():
    return {
        "language": "English",
        "generation_kwargs": {"model": "gpt-4o-mini", "max_tokens": 16384},
    }


# ---------------------------------------------------------------------------
# generate_tldr
# ---------------------------------------------------------------------------


def test_tldr_returns_response(llm_params):
    client = make_stub_openai_client()
    paper = make_sample_paper()
    result = paper.generate_tldr(client, llm_params)
    assert result == "Hello! How can I assist you today?"
    assert paper.tldr == result


def test_tldr_accepts_plain_string_response(llm_params):
    from types import SimpleNamespace

    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **_: "  公益站生成的 TLDR  ")
        )
    )
    paper = make_sample_paper()

    result = paper.generate_tldr(client, llm_params)

    assert result == "公益站生成的 TLDR"
    assert paper.tldr == result


def test_tldr_without_abstract_or_fulltext(llm_params):
    client = make_stub_openai_client()
    paper = make_sample_paper(abstract="", full_text=None)
    result = paper.generate_tldr(client, llm_params)
    assert "Failed to generate TLDR" in result


def test_tldr_raises_when_api_call_fails(llm_params):
    paper = make_sample_paper()

    # Client whose create() raises
    from types import SimpleNamespace

    broken_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **kw: (_ for _ in ()).throw(RuntimeError("API down")))
        )
    )
    with pytest.raises(RuntimeError, match="API down"):
        paper.generate_tldr(broken_client, llm_params)

    assert paper.tldr is None


def test_tldr_rejects_empty_string_response(llm_params):
    from types import SimpleNamespace

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_: "   "))
    )
    paper = make_sample_paper()

    with pytest.raises(ValueError, match="empty TLDR"):
        paper.generate_tldr(client, llm_params)

    assert paper.tldr is None


@pytest.mark.parametrize(
    "response",
    [
        "<!doctype html><meta name='aliyun_waf_aa' content='x'>",
        "<html><title>Access Verification</title></html>",
        "访问验证，请滑动完成验证",
    ],
)
def test_tldr_rejects_waf_or_html_response(llm_params, response):
    from types import SimpleNamespace

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_: response))
    )
    paper = make_sample_paper()

    with pytest.raises(ValueError, match="HTML or access-verification"):
        paper.generate_tldr(client, llm_params)

    assert paper.tldr is None


def test_tldr_truncates_long_prompt(llm_params):
    client = make_stub_openai_client()
    paper = make_sample_paper(full_text="word " * 10000)
    result = paper.generate_tldr(client, llm_params)
    assert result is not None


def test_paper_has_no_affiliation_generation_path():
    paper = make_sample_paper()

    assert not hasattr(paper, "affiliations")
    assert not hasattr(paper, "generate_affiliations")
