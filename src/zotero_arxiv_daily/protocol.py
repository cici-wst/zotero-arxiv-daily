from dataclasses import dataclass
from typing import Optional, TypeVar
from datetime import datetime
import tiktoken
from openai import OpenAI
from loguru import logger
RawPaperItem = TypeVar('RawPaperItem')
INVALID_LLM_RESPONSE_MARKERS = (
    "<!doctype html",
    "<html",
    "aliyun_waf",
    "access verification",
    "访问验证",
)


def _extract_tldr(response: object) -> str:
    if isinstance(response, str):
        content = response
    else:
        content = response.choices[0].message.content

    if not isinstance(content, str):
        raise TypeError("LLM returned a non-text TLDR")

    tldr = content.strip()
    if not tldr:
        raise ValueError("LLM returned an empty TLDR")
    if any(marker in tldr.lower() for marker in INVALID_LLM_RESPONSE_MARKERS):
        raise ValueError("LLM returned HTML or access-verification content")
    return tldr

@dataclass
class Paper:
    source: str
    title: str
    authors: list[str]
    abstract: str
    url: str
    pdf_url: Optional[str] = None
    full_text: Optional[str] = None
    published_at: Optional[datetime] = None
    tldr: Optional[str] = None
    score: Optional[float] = None

    def _generate_tldr_with_llm(self, openai_client:OpenAI,llm_params:dict) -> str:
        lang = llm_params.get('language', 'English')
        prompt = f"Given the following information of a paper, generate a one-sentence TLDR summary in {lang}:\n\n"
        if self.title:
            prompt += f"Title:\n {self.title}\n\n"

        if self.abstract:
            prompt += f"Abstract: {self.abstract}\n\n"

        if self.full_text:
            prompt += f"Preview of main content:\n {self.full_text}\n\n"

        if not self.full_text and not self.abstract:
            logger.warning(f"Neither full text nor abstract is provided for {self.url}")
            return "Failed to generate TLDR. Neither full text nor abstract is provided"
        
        # use gpt-4o tokenizer for estimation
        enc = tiktoken.encoding_for_model("gpt-4o")
        prompt_tokens = enc.encode(prompt)
        prompt_tokens = prompt_tokens[:4000]  # truncate to 4000 tokens
        prompt = enc.decode(prompt_tokens)
        
        response = openai_client.chat.completions.create(
            messages=[
                {
                    "role": "system",
                    "content": f"You are an assistant who perfectly summarizes scientific paper, and gives the core idea of the paper to the user. Your answer should be in {lang}.",
                },
                {"role": "user", "content": prompt},
            ],
            **llm_params.get('generation_kwargs', {})
        )
        return _extract_tldr(response)
    
    def generate_tldr(self, openai_client:OpenAI,llm_params:dict) -> str:
        tldr = self._generate_tldr_with_llm(openai_client,llm_params)
        self.tldr = tldr
        return tldr

@dataclass
class CorpusPaper:
    title: str
    abstract: str
    added_date: datetime
    paths: list[str]
