"""Guardrails кодом (ТЗ §6.4): инъекции в данных, проверка цитат ответа, правила заявки.

Промпт их не заменяет: каждое правило здесь проверяется функцией и попадает в журнал.
"""

import re
from typing import Any

from pydantic import BaseModel, Field

from app.agent.verdict import Verdict
from app.clients.toir_client import Reference
from app.rag.citations import (
    check_citations,
    is_list_item,
    split_sentences,
    unsupported_claims,
)
from app.rag.conflicts import ConflictNotice
from app.rag.search import Fragment

UNCONFIRMED_MARK = "(не подтверждено руководством)"
NO_DATA_ANSWER = "В руководстве на этот двигатель этих данных нет. Рекомендую дефектовку узла."

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


RAW_ANSWER_LIMIT_BYTES = 8 * 1024


def raw_answer_snapshot(text: str) -> dict[str, Any]:
    """Сырой ответ модели до правок кодом, для журнала: обрезаем до 8 КБ, символ не рвём."""
    raw = text.encode("utf-8")
    cut = raw[:RAW_ANSWER_LIMIT_BYTES].decode("utf-8", errors="ignore")
    return {"text": cut, "bytes": len(raw), "truncated": len(raw) > RAW_ANSWER_LIMIT_BYTES}


class AnswerCheck(BaseModel):
    ok: bool
    problems: list[str]


def check_answer(answer: str, fragments: list[Fragment]) -> AnswerCheck:
    result = check_citations(answer, fragments)
    return AnswerCheck(ok=result.ok, problems=result.problems)


def sanitize_answer(answer: str, fragments: list[Fragment]) -> str:
    """Непроверенное убираем (ТЗ §6.4, п.1): пункт списка — целиком, без заглушки;
    обычную фразу заменяем пометкой.

    Переносы строк и отступы между фразами сохраняем: по ним интерфейс строит заголовки и списки.
    Пункт списка удаляем вместе с переводом строки после него, чтобы не оставлять пустых строк.
    """
    out: list[str] = []
    cursor = 0
    for sentence in split_sentences(answer):
        start = answer.find(sentence, cursor)
        if start < 0:
            continue
        out.append(answer[cursor:start])
        end = start + len(sentence)
        if not sentence.strip() or check_citations(sentence, fragments).ok:
            out.append(sentence)
        elif is_list_item(sentence):
            if answer[end : end + 1] == "\n":
                end += 1
        else:
            out.append(UNCONFIRMED_MARK)
        cursor = end
    out.append(answer[cursor:])
    return "".join(out).strip()


HEADING_LINE_RE = re.compile(r"^\s*(?:#{1,6}\s|\*\*[^*\n]+\*\*\s*$)")
LEFTOVER_LINE_RE = re.compile(
    rf"^\s*(?:{re.escape(UNCONFIRMED_MARK)}|рекоменду(?:ем|ю|ется))\.?\s*$"
    r"|^\s*(?:[-*•]|\d+[.)])\s*$",
    re.IGNORECASE,
)
MIN_TOPIC_HEADING = 12


def tidy_answer(answer: str, topics: list[str]) -> str:
    """Чистка после sanitize_answer.

    Раздел, заголовок которого совпадает с темой правила противоречия, — пересказ блока, который
    вставит код. Удаляем его целиком вместе с заголовком. Заглушки, висящие «Рекомендуем.»,
    пустые пункты и заголовки без текста удаляем строками.
    """
    plain_topics = [_plain_heading(topic) for topic in topics]
    sections: list[list[str]] = [[]]
    for line in answer.split("\n"):
        if HEADING_LINE_RE.match(line):
            sections.append([line])
        else:
            sections[-1].append(line)
    kept: list[str] = []
    for section in sections:
        heading = section[0] if section and HEADING_LINE_RE.match(section[0]) else None
        if heading is not None and _retells_conflict(heading, plain_topics):
            continue
        lines = [line for line in section if not LEFTOVER_LINE_RE.match(line)]
        if heading is not None and not any(line.strip() for line in lines[1:]):
            continue
        kept.extend(lines)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()


def _plain_heading(text: str) -> str:
    return text.strip().strip("#*").strip().rstrip(".:").lower()


def _retells_conflict(heading: str, plain_topics: list[str]) -> bool:
    title = _plain_heading(heading)
    if len(title) < MIN_TOPIC_HEADING:
        return False
    return any(
        topic and (title == topic or title in topic or topic in title) for topic in plain_topics
    )


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
    consult_removed: list[str] = Field(default_factory=list)


# Фраза для механика: её добавляет только код, в блоке противоречия.
CONSULT_PHRASE = "Уточните у специалиста или производителя до регулировки."
# «уточните у специалиста» из текста модели: вырезаем вместе с разделителем перед ним.
CONSULT_CLAUSE_RE = re.compile(
    r"\s*[,;]?\s*(?:уточн\w*\s+у\s+специалист|у\s+специалиста\s+или\s+производител)[^.!?\n]*[.!?]?",
    re.IGNORECASE,
)
BULLET_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s*")


def render_conflict_block(notices: list[ConflictNotice]) -> str:
    """Блок противоречия: формулировки из правила (дословно), ссылки, безопасное правило.

    Текст собирает код, модель его не переписывает. Формулировки берутся из known_conflicts.yaml
    и проверены по страницам при поиске (quote_for_ref).
    """
    blocks = []
    for notice in notices:
        lines = [
            "**В документации противоречие.** Формулировки в руководствах расходятся. "
            f"Тема: {notice.topic}."
        ]
        for quote in notice.quotes:
            lines.append(f"- «{quote.quote}» [{quote.manual}, стр. {quote.pdf_page}]")
        lines.append(f"Безопасное правило: {notice.safe_rule}.")
        lines.append("Причину расхождения не определяем. " + CONSULT_PHRASE)
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def apply_conflict_block(answer: str, notices: list[ConflictNotice]) -> ConflictBlock:
    """Ответ с противоречием: строки модели о трактовке убираем, её «уточните у специалиста»
    тоже, блок кода ставим в конец с фразой для механика."""
    if not notices:
        return ConflictBlock(text=answer, removed=[])
    kept: list[str] = []
    removed: list[str] = []
    consult_removed: list[str] = []
    for line in answer.split("\n"):
        if CONFLICT_TALK_RE.search(line):
            if line.strip():
                removed.append(line.strip())
            continue
        rest, found = _drop_consult(line)
        if not found:
            kept.append(line)
            continue
        consult_removed.extend(found)
        if BULLET_RE.sub("", rest).strip(" .!?"):
            kept.append(rest)
    body = "\n".join(kept).strip()
    block = render_conflict_block(notices)
    text = f"{body}\n\n{block}" if body else block
    return ConflictBlock(text=text, removed=removed, consult_removed=consult_removed)


def _drop_consult(line: str) -> tuple[str, list[str]]:
    """Строка без «уточните у специалиста» модели и сами удалённые фрагменты."""
    found = [match.group(0).strip(" ,;") for match in CONSULT_CLAUSE_RE.finditer(line)]
    if not found:
        return line, []
    ends_sentence = CONSULT_CLAUSE_RE.search(line).group(0).rstrip().endswith((".", "!", "?"))
    rest = CONSULT_CLAUSE_RE.sub("", line).rstrip()
    if ends_sentence and rest and rest[-1] not in ".!?:":
        rest += "."
    return rest, found
