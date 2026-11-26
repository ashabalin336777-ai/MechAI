"""Инструмент search_manual: поиск по руководству ДВИГАТЕЛЯ ТС (ТЗ §6.2, rag.mdc).

Двигатель берётся из карточки машины диалога, а не из аргументов модели: модель не может
снять фильтр. Фрагменты чужого двигателя отбрасываем повторно (engine_guard).
"""

from pydantic import BaseModel, Field

from app.tools.runtime import Runtime

NAME = "search_manual"
DESCRIPTION = (
    "Поиск процедур, моментов затяжки, зазоров, давлений и норм в руководстве ДВИГАТЕЛЯ машины. "
    "Единственный источник цифр. Запрос — по названию узла или типа неисправности. "
    "Если фрагментов нет, так и скажи механику: в руководстве на двигатель этих данных нет."
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
    allowed = set(rt.engine_manuals(engine))
    query = _build_query(args.query, engine, turn.diagnosis)
    fragments = rt.deps.search(query, engine, args.top_k)
    fragments = [fragment for fragment in fragments if fragment.manual in allowed]
    if not fragments:
        _no_procedure(rt, engine)
        return {
            "ok": True,
            "found": False,
            "engine_model": engine,
            "message": f"в руководстве на {engine} этих данных нет. Рекомендуйте дефектовку.",
        }
    turn.remember(fragments)
    return {
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


def _build_query(query: str, engine: str, diagnosis: dict | None) -> str:
    """Запрос: просьба модели + модель двигателя + название неисправности из ML (rag.mdc)."""
    title = diagnosis["ml"].get("anomaly_title") if diagnosis else None
    parts = [query, engine] + ([title] if title else [])
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
