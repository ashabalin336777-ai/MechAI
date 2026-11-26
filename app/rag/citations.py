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


def split_sentences(answer: str) -> list[str]:
    """Фразы ответа. Ссылки прячутся за маркеры, чтобы точки внутри них не резали фразу."""
    stashed: dict[str, str] = {}

    def hide(match: re.Match[str]) -> str:
        marker = f"\x00{len(stashed)}\x00"
        stashed[marker] = match.group(0)
        return marker

    masked = CITATION_RE.sub(hide, answer)
    sentences = SENTENCE_SPLIT_RE.split(masked)
    restored = []
    for sentence in sentences:
        for marker, citation in stashed.items():
            sentence = sentence.replace(marker, citation)
        restored.append(sentence)
    return restored


def _designation(value: str) -> str:
    return " ".join(value.lower().split())


def _claim_key(number: str, unit: str) -> tuple[float, str]:
    return float(number.replace(",", ".")), _unit_key(unit)


def _unit_key(unit: str) -> str:
    return unit.lower().replace(" ", "").replace("·", "").replace("°", "").replace("с", "c")
