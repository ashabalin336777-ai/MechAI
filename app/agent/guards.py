"""Guardrails кодом (ТЗ §6.4): инъекции в данных, проверка цитат ответа, правила заявки.

Промпт их не заменяет: каждое правило здесь проверяется функцией и попадает в журнал.
"""

import re

from pydantic import BaseModel

from app.agent.verdict import Verdict
from app.clients.toir_client import Reference
from app.rag.citations import check_citations, split_sentences
from app.rag.search import Fragment

UNCONFIRMED_MARK = "(не подтверждено руководством)"

INJECTION_RE = re.compile(
    r"SYSTEM\s*:"
    r"|предыдущие инструкции"
    r"|игнорируй"
    r"|не\s+создавай\s+заявк"
    r"|заявку\s+не\s+создавай"
    r"|сообщи\s+механику"
    r"|ignore\s+(?:all\s+)?previous\s+instructions",
    re.IGNORECASE,
)


def find_injection_markers(text: str) -> list[str]:
    """Совпадения с известными маркерами команд в данных инструмента (ТЗ §6.4, п.5)."""
    return sorted({match.group(0).lower() for match in INJECTION_RE.finditer(text)})


def wrap_tool_data(payload_json: str) -> str:
    """Данные инструментов отдаём только в блоке <tool_data>: промпт велит считать их данными."""
    return f"<tool_data>\n{payload_json}\n</tool_data>"


class AnswerCheck(BaseModel):
    ok: bool
    problems: list[str]


def check_answer(answer: str, fragments: list[Fragment]) -> AnswerCheck:
    result = check_citations(answer, fragments)
    return AnswerCheck(ok=result.ok, problems=result.problems)


def sanitize_answer(answer: str, fragments: list[Fragment]) -> str:
    """Фразы с непроверенными цифрами или ссылками заменяем пометкой (ТЗ §6.4, п.1)."""
    kept: list[str] = []
    for sentence in split_sentences(answer):
        if not sentence.strip() or check_citations(sentence, fragments).ok:
            kept.append(sentence)
        else:
            kept.append(UNCONFIRMED_MARK)
    return " ".join(part.strip() for part in kept if part.strip())


class TicketCheck(BaseModel):
    ok: bool
    problems: list[str]


def check_ticket_draft(
    *,
    verdict: Verdict | None,
    references: list[Reference],
    retrieved: list[Fragment],
    engine_manuals: dict[str, int],
    urgency: str,
) -> TicketCheck:
    """ticket_guard (§6.4 п.3): заявки нет при check_failed, normal, без ссылок RAG этого диалога.

    engine_manuals: обозначение руководства двигателя ТС -> число страниц PDF.
    """
    problems: list[str] = []
    if verdict is None:
        return TicketCheck(ok=False, problems=["сначала получите результат диагностики"])
    if not verdict.ticket_possible:
        problems.append(f"заявка не создаётся при вердикте «{verdict.headline}»")
    if verdict.urgency is not None and urgency != verdict.urgency:
        problems.append(f"приоритет {urgency} не совпадает с правилом §7.2: {verdict.urgency}")
    if not references:
        problems.append(
            "нет ссылок на руководство: в руководстве этого двигателя инструкции не найдено"
        )
    seen = {(_norm(f.manual), f.pdf_page) for f in retrieved}
    for ref in references:
        key = _norm(ref.manual)
        pages = _pages_for(key, engine_manuals)
        if pages is None:
            problems.append(f"руководство «{ref.manual}» не относится к двигателю этой машины")
            continue
        if not 1 <= ref.pdf_page <= pages:
            problems.append(f"страница {ref.pdf_page} вне диапазона PDF 1–{pages}")
            continue
        if (key, ref.pdf_page) not in seen:
            problems.append(
                f"страница {ref.pdf_page} «{ref.manual}» не получена в этом диалоге через поиск"
            )
    return TicketCheck(ok=not problems, problems=problems)


def _pages_for(key: str, engine_manuals: dict[str, int]) -> int | None:
    for designation, pages in engine_manuals.items():
        if _norm(designation) == key:
            return pages
    return None


def _norm(value: str) -> str:
    return " ".join(value.lower().split())
