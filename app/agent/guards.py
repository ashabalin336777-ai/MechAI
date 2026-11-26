"""Guardrails кодом (ТЗ §6.4): инъекции в данных, проверка цитат ответа, правила заявки.

Промпт их не заменяет: каждое правило здесь проверяется функцией и попадает в журнал.
"""

import re

from pydantic import BaseModel

from app.agent.verdict import Verdict
from app.clients.toir_client import Reference
from app.rag.citations import check_citations, split_sentences, unsupported_claims
from app.rag.conflicts import ConflictNotice
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


INJECTION_CLAUSE_RE = re.compile(
    r"[^.!?\n\"]*(?:" + INJECTION_RE.pattern + r")[^.!?\n\"]*", re.IGNORECASE
)
REDACTED_CLAUSE = "[инструкция из данных удалена]"


def find_injection_markers(text: str) -> list[str]:
    """Совпадения с известными маркерами команд в данных инструмента (ТЗ §6.4, п.5)."""
    return sorted({match.group(0).lower() for match in INJECTION_RE.finditer(text)})


def redact_injection(text: str) -> str:
    """Вырезаем целое предложение с командой: модель не видит её и не может процитировать."""
    return INJECTION_CLAUSE_RE.sub(REDACTED_CLAUSE, text)


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
    """Фразы с непроверенными цифрами или ссылками заменяем пометкой (ТЗ §6.4, п.1).

    Переносы строк и отступы между фразами сохраняем: по ним интерфейс строит заголовки и списки.
    Заменяется только сама фраза, разделители из исходного текста остаются как были.
    """
    out: list[str] = []
    cursor = 0
    for sentence in split_sentences(answer):
        start = answer.find(sentence, cursor)
        if start < 0:
            continue
        out.append(answer[cursor:start])
        if not sentence.strip() or check_citations(sentence, fragments).ok:
            out.append(sentence)
        else:
            out.append(UNCONFIRMED_MARK)
        cursor = start + len(sentence)
    out.append(answer[cursor:])
    return "".join(out).strip()


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
    texts: list[str] | None = None,
) -> TicketCheck:
    """ticket_guard (§6.4 п.3): заявки нет при check_failed, normal, без ссылок RAG этого диалога.

    engine_manuals: обозначение руководства двигателя ТС -> число страниц PDF.
    texts: вывод и операции черновика — в них цифры только из фрагментов этого диалога.
    """
    problems: list[str] = []
    if verdict is None:
        return TicketCheck(ok=False, problems=["сначала получите результат диагностики"])
    if not verdict.ticket_possible:
        problems.append(f"заявка не создаётся при вердикте «{verdict.headline}»")
    for text in texts or []:
        for claim in unsupported_claims(text, retrieved):
            problems.append(
                f"цифра «{claim}» не найдена в руководстве этого диалога: уберите число "
                "или получите норматив через search_manual"
            )
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


# Фразы, в которых модель трактует противоречие вместо того, чтобы показать его формулировки.
CONFLICT_TALK_RE = re.compile(
    r"противореч|взаимоисключ|не конфликт|можно понимать|следует понимать|на самом деле|фактически",
    re.IGNORECASE,
)


class ConflictBlock(BaseModel):
    text: str
    removed: list[str]


def render_conflict_block(notices: list[ConflictNotice]) -> str:
    """Блок противоречия: формулировки из правила (дословно), ссылки, безопасное правило.

    Текст собирает код, модель его не переписывает. Формулировки берутся из known_conflicts.yaml
    и проверены по страницам при поиске (quote_for_ref).
    """
    blocks = []
    for notice in notices:
        lines = [f"**В документации противоречие.** Тема: {notice.topic}."]
        for quote in notice.quotes:
            lines.append(f"- «{quote.quote}» [{quote.manual}, стр. {quote.pdf_page}]")
        lines.append(f"Безопасное правило: {notice.safe_rule}.")
        lines.append(
            "Причину расхождения не определяем. "
            "Уточните у специалиста или производителя до регулировки."
        )
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def apply_conflict_block(answer: str, notices: list[ConflictNotice]) -> ConflictBlock:
    """Ответ с противоречием: строки модели о трактовке убираем, блок кода ставим в конец."""
    if not notices:
        return ConflictBlock(text=answer, removed=[])
    kept: list[str] = []
    removed: list[str] = []
    for line in answer.split("\n"):
        if CONFLICT_TALK_RE.search(line):
            if line.strip():
                removed.append(line.strip())
        else:
            kept.append(line)
    body = "\n".join(kept).strip()
    block = render_conflict_block(notices)
    text = f"{body}\n\n{block}" if body else block
    return ConflictBlock(text=text, removed=removed)
