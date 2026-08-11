import tarfile
import re
import glob
import math
from collections import Counter
from loguru import logger
import pymupdf
pymupdf.TOOLS.mupdf_display_errors(False)

_TOKEN_RE = re.compile(r'[a-zA-Z0-9]+')

def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def _bm25_pick(
    query: str,
    candidates: dict[str, str],
    *,
    k1: float = 1.5,
    b: float = 0.75,
) -> str:
    """Return the candidate key whose content best matches *query* by BM25."""
    query_tokens = _tokenize(query)
    if not query_tokens:
        return next(iter(candidates))

    doc_tokens = {name: _tokenize(content) for name, content in candidates.items()}
    N = len(doc_tokens)
    avgdl = sum(len(t) for t in doc_tokens.values()) / max(N, 1)

    df: Counter[str] = Counter()
    for tokens in doc_tokens.values():
        df.update(set(tokens))

    best_name, best_score = None, -1.0
    for name, tokens in doc_tokens.items():
        tf = Counter(tokens)
        dl = len(tokens)
        score = 0.0
        for q in query_tokens:
            n_q = df.get(q, 0)
            idf = math.log((N - n_q + 0.5) / (n_q + 0.5) + 1)
            f_q = tf.get(q, 0)
            score += idf * (f_q * (k1 + 1)) / (f_q + k1 * (1 - b + b * dl / max(avgdl, 1)))
        if score > best_score:
            best_score = score
            best_name = name
    return best_name


def _main_tex_from_bbl(
    tex_files: list[str],
    bbl_files: list[str],
    paper_id: str,
) -> str | None:
    if not bbl_files:
        if len(tex_files) == 1:
            return tex_files[0]
        logger.debug(
            f"Cannot find main tex file of {paper_id} from bbl: "
            "There are multiple tex files while no bbl file."
        )
        return None
    if len(bbl_files) > 1:
        logger.debug(f"Cannot find main tex file of {paper_id} from bbl: There are multiple bbl files.")
        return None
    main_tex = f"{bbl_files[0].removesuffix('.bbl')}.tex"
    if main_tex in tex_files:
        return main_tex
    logger.debug(
        f"Cannot find main tex file of {paper_id} from bbl: "
        "The bbl file does not match any tex file."
    )
    return None


def _clean_tex_content(content: str) -> str:
    content = re.sub(r'%.*\n', '\n', content)
    content = re.sub(r'\\begin{comment}.*?\\end{comment}', '', content, flags=re.DOTALL)
    content = re.sub(r'\\iffalse.*?\\fi', '', content, flags=re.DOTALL)
    content = re.sub(r'\n+', '\n', content)
    content = re.sub(r'\\\\', '', content)
    return re.sub(r'[ \t\r\f]{3,}', ' ', content)


def _read_tex_contents(
    archive: tarfile.TarFile,
    tex_files: list[str],
    collect_candidates: bool,
) -> tuple[dict[str, str], list[str]]:
    contents: dict[str, str] = {}
    candidates: list[str] = []
    for name in tex_files:
        member = archive.extractfile(name)
        if member is None:
            raise ValueError(f"Unable to read {name} from tar archive")
        content = _clean_tex_content(member.read().decode('utf-8', errors='ignore'))
        if collect_candidates and _is_document_candidate(name, content):
            candidates.append(name)
        contents[name] = content
    return contents, candidates


def _is_document_candidate(name: str, content: str) -> bool:
    excluded_names = ('example', 'sample', 'template')
    return re.search(r'\\begin\{document\}', content) is not None and not any(
        word in name for word in excluded_names
    )


def _choose_document_candidate(
    candidates: list[str],
    contents: dict[str, str],
    *,
    paper_id: str,
    paper_title: str | None,
) -> str | None:
    if len(candidates) == 1:
        logger.debug(f"Choose {candidates[0]} as main tex file of {paper_id}")
        return candidates[0]
    if not candidates:
        return None
    if paper_title:
        selected = _bm25_pick(paper_title, {name: contents[name] for name in candidates})
        logger.debug(f"Multiple document blocks found in {paper_id}; BM25 selected {selected} from {candidates}")
        return selected
    logger.debug(f"Multiple document blocks found in {paper_id}; no title provided, using first candidate {candidates[0]}")
    return candidates[0]


def _resolve_input_sources(main_source: str, contents: dict[str, str]) -> str:
    include_files = re.findall(r'\\input\{(.+?)\}', main_source)
    include_files += re.findall(r'\\include\{(.+?)\}', main_source)
    for name in include_files:
        file_name = name if name.endswith('.tex') else f"{name}.tex"
        main_source = main_source.replace(f'\\input{{{name}}}', contents.get(file_name, ''))
    return main_source


def _extract_tex_archive(
    archive: tarfile.TarFile,
    paper_id: str,
    paper_title: str | None,
) -> dict[str, str | None] | None:
    names = archive.getnames()
    tex_files = [name for name in names if name.endswith('.tex')]
    if not tex_files:
        logger.debug(f"Failed to find main tex file of {paper_id}: No tex file.")
        return None
    bbl_files = [name for name in names if name.endswith('.bbl')]
    main_tex = _main_tex_from_bbl(tex_files, bbl_files, paper_id)
    if main_tex is None:
        logger.debug(f"Trying to choose tex file containing the document block as main tex file of {paper_id}")
    contents, candidates = _read_tex_contents(archive, tex_files, main_tex is None)
    if main_tex is None:
        main_tex = _choose_document_candidate(
            candidates,
            contents,
            paper_id=paper_id,
            paper_title=paper_title,
        )
    if main_tex is None:
        logger.debug(f"Failed to find main tex file of {paper_id}: No tex file containing the document block.")
        return {**contents, "all": None}
    return {**contents, "all": _resolve_input_sources(contents[main_tex], contents)}


def extract_tex_code_from_tar(
    file_path: str,
    paper_id: str,
    paper_title: str | None = None,
) -> dict[str, str | None] | None:
    try:
        with tarfile.open(file_path) as archive:
            return _extract_tex_archive(archive, paper_id, paper_title)
    except tarfile.ReadError:
        logger.debug(f"Failed to find main tex file of {paper_id}: Not a tar file.")
        return None

def extract_markdown_from_pdf(file_path:str) -> str:
    import pymupdf.layout
    import pymupdf4llm

    pymupdf.layout.activate()
    return pymupdf4llm.to_markdown(file_path,use_ocr=False,header=False,footer=False,ignore_code=True)

def glob_match(path:str, pattern:str) -> bool:
    re_pattern = glob.translate(pattern,recursive=True)
    return re.match(re_pattern, path) is not None
