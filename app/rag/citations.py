"""Проверка цитат ответа (ТЗ §6.4, правило rag.mdc): проверяется кодом, не только промптом.

- Ссылка `[обозначение, стр. N]` должна указывать на страницу, которая была в выдаче этого хода.
- Цифра с единицей должна встречаться во фрагменте этой страницы (0,15 = 0.15, «Н·м» = «Н м»).
- Цифра с единицей без ссылки в той же фразе — ошибка.
"""

import re

from pydantic import BaseModel

from app.rag.search import Fragment

CITATION_RE = re.compile(r"\[([^\[\]]+?),\s*стр\.\s*(\d+)\]")
UNIT = r"(?:Н·м|Н\s?м|кгс·см|кгс·м|кПа|МПа|бар|мм|см|мкм|м|°[CС]|кг|г|мл|л|%|об/мин|мин|кВт|Вт|В|А)"
CLAIM_RE = re.compile(rf"(?<![\w.,])(\d+(?:[.,]\d+)?)\s?({UNIT})(?![\wа-яА-ЯёЁ])")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
LIST_ITEM_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
HEADING_RE = re.compile(r"^\s*#{1,6}\s")


class CitationCheck(BaseModel):
    ok: bool
    problems: list[str]


def check_citations(answer: str, fragments: list[Fragment]) -> CitationCheck:
    texts_by_page: dict[tuple[str, int], list[str]] = {}
    for fragment in fragments:
        key = (_designation(fragment.manual), fragment.pdf_page)
        texts_by_page.setdefault(key, []).append(fragment.text)
    claims_by_page = {
        key: {_claim_key(number, unit) for text in texts for number, unit in CLAIM_RE.findall(text)}
        for key, texts in texts_by_page.items()
    }

    problems: list[str] = []
    for sentence in split_sentences(answer):
        claims = list(CLAIM_RE.finditer(sentence))
        citations = [
            (_designation(desig), int(page)) for desig, page in CITATION_RE.findall(sentence)
        ]
        valid = [key for key in citations if key in texts_by_page]
        for desig, page in citations:
            if (desig, page) not in texts_by_page:
                problems.append(
                    f"ссылка [{desig}, стр. {page}] не соответствует полученным фрагментам"
                )
        for claim in claims:
            raw = claim.group(0)
            if not citations:
                problems.append(f"цифра «{raw}» без ссылки [обозначение, стр. N] в той же фразе")
                continue
            key = _claim_key(claim.group(1), claim.group(2))
            if not any(key in claims_by_page[page] for page in valid):
                problems.append(
                    f"цифра «{raw}» не найдена во фрагментах, на которые ссылается фраза"
                )
    return CitationCheck(ok=not problems, problems=problems)


class CitationFix(BaseModel):
    old: str
    new: str
    claim: str


class CitationFixes(BaseModel):
    text: str
    fixes: list[CitationFix]


def fix_citations(answer: str, fragments: list[Fragment]) -> CitationFixes:
    """Ссылка на страницу без цифры → ссылка на страницу ЭТОГО хода, где цифра дословно есть.

    Исправляем однозначный случай: во фразе одна ссылка, и все её цифры без подтверждения есть на
    одной и той же другой странице из fragments. Иначе фразу не трогаем: её вырежет sanitize_answer.
    """
    sources = [
        (
            fragment.manual,
            fragment.pdf_page,
            _designation(fragment.manual),
            _claim_keys(fragment.text),
        )
        for fragment in fragments
    ]
    fixes: list[CitationFix] = []
    out: list[str] = []
    cursor = 0
    for sentence in split_sentences(answer):
        start = answer.find(sentence, cursor)
        if start < 0:
            continue
        out.append(answer[cursor:start])
        out.append(_fix_sentence(sentence, sources, fixes))
        cursor = start + len(sentence)
    out.append(answer[cursor:])
    return CitationFixes(text="".join(out), fixes=fixes)


def _fix_sentence(
    sentence: str,
    sources: list[tuple[str, int, str, set[tuple[float, str]]]],
    fixes: list[CitationFix],
) -> str:
    citations = list(CITATION_RE.finditer(sentence))
    claims = list(CLAIM_RE.finditer(sentence))
    if len(citations) != 1 or not claims:
        return sentence
    citation = citations[0]
    cited = (_designation(citation.group(1)), int(citation.group(2)))
    cited_keys = set().union(*(keys for _, page, desig, keys in sources if (desig, page) == cited))
    missing = [
        claim for claim in claims if _claim_key(claim.group(1), claim.group(2)) not in cited_keys
    ]
    if not missing:
        return sentence
    candidates: list[tuple[str, int]] | None = None
    for claim in missing:
        key = _claim_key(claim.group(1), claim.group(2))
        pages = [
            (manual, page)
            for manual, page, desig, keys in sources
            if key in keys and (desig, page) != cited
        ]
        candidates = pages if candidates is None else [p for p in candidates if p in pages]
    if not candidates:
        return sentence
    manual, page = candidates[0]
    new = f"[{manual}, стр. {page}]"
    fixes.append(CitationFix(old=citation.group(0), new=new, claim=missing[0].group(0)))
    return sentence[: citation.start()] + new + sentence[citation.end() :]


def _claim_keys(text: str) -> set[tuple[float, str]]:
    return {_claim_key(number, unit) for number, unit in CLAIM_RE.findall(text)}


def unsupported_claims(text: str, fragments: list[Fragment]) -> list[str]:
    """Цифры с единицей из текста, которых нет ни в одном фрагменте (для черновика заявки)."""
    known = {
        _claim_key(number, unit)
        for fragment in fragments
        for number, unit in CLAIM_RE.findall(fragment.text)
    }
    return [
        match.group(0)
        for match in CLAIM_RE.finditer(text)
        if _claim_key(match.group(1), match.group(2)) not in known
    ]


def split_sentences(answer: str) -> list[str]:
    """Фразы ответа.

    Пункт списка (маркер «-», «•», «1.») — одна фраза целиком, вместе с продолжением строк:
    цифра и её ссылка внутри пункта проверяются вместе. Обычный текст режется по знакам конца
    предложения. Ссылки прячутся за маркеры, чтобы точки внутри них не резали фразу.
    """
    stashed: dict[str, str] = {}

    def hide(match: re.Match[str]) -> str:
        marker = f"\x00{len(stashed)}\x00"
        stashed[marker] = match.group(0)
        return marker

    masked = CITATION_RE.sub(hide, answer)
    blocks: list[tuple[bool, str]] = []
    for line in masked.split("\n"):
        if LIST_ITEM_RE.match(line):
            blocks.append((True, line))
        elif blocks and blocks[-1][0] and line.strip() and not HEADING_RE.match(line):
            blocks[-1] = (True, f"{blocks[-1][1]}\n{line}")
        else:
            blocks.append((False, line))
    sentences: list[str] = []
    for is_item, text in blocks:
        if is_item:
            sentences.append(text)
        else:
            sentences.extend(piece for piece in SENTENCE_SPLIT_RE.split(text) if piece.strip())
    restored = []
    for sentence in sentences:
        for marker, citation in stashed.items():
            sentence = sentence.replace(marker, citation)
        restored.append(sentence)
    return restored


def is_list_item(sentence: str) -> bool:
    """Фраза из split_sentences — пункт списка (начинается с маркера)."""
    return LIST_ITEM_RE.match(sentence) is not None


def _designation(value: str) -> str:
    return " ".join(value.lower().split())


def _claim_key(number: str, unit: str) -> tuple[float, str]:
    return float(number.replace(",", ".")), _unit_key(unit)


def _unit_key(unit: str) -> str:
    return unit.lower().replace(" ", "").replace("·", "").replace("°", "").replace("с", "c")
