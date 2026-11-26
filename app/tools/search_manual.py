"""Инструмент search_manual: поиск по руководству ДВИГАТЕЛЯ ТС (ТЗ §6.2, rag.mdc).

Двигатель берётся из карточки машины диалога, а не из аргументов модели: модель не может
снять фильтр. Фрагменты чужого двигателя отбрасываем повторно (engine_guard).
Если код неисправности не применим к топливу двигателя, процедуру не ищем (compat.py).
Известные противоречия руководства (known_conflicts.yaml) добавляют обе формулировки в контекст.
"""

from pydantic import BaseModel, Field

from app.rag.conflicts import (
    ConflictNotice,
    ConflictQuote,
    KnownConflict,
    matching_conflicts,
    quote_for_ref,
)
from app.rag.search import Fragment
from app.tools.runtime import Runtime

NAME = "search_manual"
DESCRIPTION = (
    "Поиск процедур, моментов затяжки, зазоров, давлений и норм в руководстве ДВИГАТЕЛЯ машины. "
    "Единственный источник цифр. Запрос — по названию узла или типа неисправности. "
    "Если фрагментов нет, так и скажи механику: в руководстве на двигатель этих данных нет."
)
CONFLICT_INSTRUCTION = (
    "В документации противоречие. Блок с обеими формулировками из sources, безопасным правилом "
    "(safe_rule) и советом уточнить у специалиста система добавит в конец ответа дословно. "
    "Сам не цитируй формулировки, не пиши про противоречие и не трактуй расхождение. "
    "Ответь на вопрос механика по остальным данным."
)


class Args(BaseModel):
    query: str = Field(min_length=3, max_length=300, description="Узел, процедура или параметр")
    vehicle_id: str = Field(min_length=1)
    top_k: int = Field(default=6, ge=1, le=6)


def run(rt: Runtime, args: Args) -> dict:
    turn = rt.turn
    if args.vehicle_id != turn.vehicle_id:
        return {"ok": False, "error": "Руководство выбирается по машине этого диалога."}
    vehicle = rt.deps.vehicles.get(args.vehicle_id)
    if vehicle is None:
        return {"ok": False, "error": "Машина не найдена."}
    engine = vehicle.engine_model
    if _is_mismatch(turn.diagnosis):
        return {
            "ok": True,
            "found": False,
            "engine_model": engine,
            "message": _mismatch_text(turn.diagnosis),
        }
    allowed = set(rt.engine_manuals(engine))
    query = _build_query(args.query, turn.diagnosis)
    found = [f for f in rt.deps.search(query, engine, args.top_k) if f.manual in allowed]
    extra, notices = _conflicts(rt, engine, args.query, found, allowed)
    fragments = found + [f for f in extra if not _same(f, found)]
    if not fragments:
        _no_procedure(rt, engine)
        return {
            "ok": True,
            "found": False,
            "engine_model": engine,
            "message": f"в руководстве на {engine} этих данных нет. Рекомендуйте дефектовку.",
        }
    turn.remember(fragments)
    for notice in notices:
        if all(known.id != notice.id for known in turn.conflicts):
            turn.conflicts.append(notice)
    result: dict = {
        "ok": True,
        "found": True,
        "engine_model": engine,
        "fragments": [
            {
                "manual": f.manual,
                "pdf_page": f.pdf_page,
                "section": f.section,
                "text": f.text,
                "score": round(f.score, 3),
            }
            for f in fragments
        ],
    }
    if notices:
        result["conflicts"] = [_conflict_payload(notice) for notice in notices]
    return result


def _is_mismatch(diagnosis: dict | None) -> bool:
    return bool(diagnosis) and diagnosis["verdict"]["code"] == "mismatch"


def _mismatch_text(diagnosis: dict) -> str:
    anomaly = diagnosis.get("ml", {}).get("anomaly_type") or "код"
    return (
        f"код {anomaly} не применим к топливу двигателя ({diagnosis.get('fuel')}). "
        "Процедуру не подбираю. Рекомендуйте повторную дефектовку узла."
    )


def _conflicts(
    rt: Runtime,
    engine: str,
    query: str,
    found: list[Fragment],
    allowed: set[str],
) -> tuple[list[Fragment], list[ConflictNotice]]:
    """Обе формулировки противоречия (если найдены на страницах) и их уведомление для ответа."""
    text = query + " " + " ".join(f.text for f in found)
    extra: list[Fragment] = []
    notices: list[ConflictNotice] = []
    for conflict in matching_conflicts(rt.deps.conflicts, engine, text):
        notice = _notice(rt, engine, conflict, allowed, extra)
        if notice is not None:
            notices.append(notice)
    return extra, notices


def _notice(
    rt: Runtime,
    engine: str,
    conflict: KnownConflict,
    allowed: set[str],
    extra: list[Fragment],
) -> ConflictNotice | None:
    quotes: list[ConflictQuote] = []
    for ref in conflict.refs:
        if ref.manual not in allowed:
            continue
        for fragment in rt.deps.fetch_pages(engine, ref.manual, [ref.pdf_page]):
            quote = quote_for_ref(conflict, ref, fragment)
            if quote is None:
                continue
            quotes.append(ConflictQuote(manual=ref.manual, pdf_page=ref.pdf_page, quote=quote))
            extra.append(fragment)
            break
    # Показываем противоречие только если нашлись обе формулировки: одна — не противоречие.
    if len(quotes) < 2:
        return None
    return ConflictNotice(
        id=conflict.id, topic=conflict.topic, quotes=quotes, safe_rule=conflict.safe_rule
    )


def _conflict_payload(notice: ConflictNotice) -> dict:
    return {
        "topic": notice.topic,
        "sources": [quote.model_dump() for quote in notice.quotes],
        "safe_rule": notice.safe_rule,
        "instruction": CONFLICT_INSTRUCTION,
    }


def _same(fragment: Fragment, others: list[Fragment]) -> bool:
    key = (fragment.manual, fragment.pdf_page, fragment.text[:80])
    return any((o.manual, o.pdf_page, o.text[:80]) == key for o in others)


# Термины, которыми руководство называет узел, когда механик говорит иначе.
# Добавляем, когда все корни есть в запросе. Слова попадают в полнотекстовый поиск по «или»,
# поэтому подсказки расширяют выдачу, а не сужают её.
TERM_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (
        ("давлен", "масл", "холост"),
        "система смазки масляный насос редукционный клапан",
    ),
    (
        ("давлен", "масл"),
        # Слова норматива из РЭ стр. 19 и РК стр. 267: номинальная частота, минимальные обороты
        # холостого хода, магистраль. Общие слова («система», «насос», «кгс/см2») не добавляем:
        # они поднимают в полнотексте страницы с прочими таблицами (проверено на РК стр. 12).
        "давление масла кПа номинальной частоте минимальной холостого хода магистрали",
    ),
    (
        ("зазор", "клапан"),
        "регулировка тепловых зазоров клапанов",
    ),
    (
        ("затяж",),
        "момент затяжки",
    ),
    (
        ("заправ", "масл"),
        "заправочные емкости система смазки без радиатора л",
    ),
    (
        ("залив", "масл"),
        "заправочные емкости система смазки без радиатора л",
    ),
    (
        ("сколько", "масл"),
        "заправочные емкости система смазки без радиатора л",
    ),
)


def _build_query(query: str, diagnosis: dict | None) -> str:
    """Запрос: просьба модели + название неисправности из ML + подсказки терминов (rag.mdc).

    Модель двигателя сюда не добавляем: фильтр по двигателю уже в SQL, а название двигателя есть
    почти на каждой странице руководства и сбивает ранжирование полнотекста.
    """
    title = diagnosis["ml"].get("anomaly_title") if diagnosis else None
    lowered = f"{query} {title or ''}".lower()
    hints = [hint for roots, hint in TERM_HINTS if all(root in lowered for root in roots)]
    parts = [query] + ([title] if title else []) + hints
    return " ".join(parts)


def _no_procedure(rt: Runtime, engine: str) -> None:
    turn = rt.turn
    verdict = turn.diagnosis["verdict"]["code"] if turn.diagnosis else None
    if verdict in ("anomaly", "needs_confirmation"):
        rt.deps.store.save_recommendation(
            turn.vehicle_id,
            turn.session_id,
            "defect_inspection_no_procedure",
            f"В руководстве на {engine} нет процедуры по этому узлу: рекомендуется дефектовка.",
        )
