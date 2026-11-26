"""Инструмент get_vehicle: карточка ТС и руководства его двигателя (ТЗ §6.2)."""

from pydantic import BaseModel, Field

from app.tools.runtime import Runtime

NAME = "get_vehicle"
DESCRIPTION = (
    "Карточка машины по госномеру: марка, модель, двигатель, топливо и руководства двигателя. "
    "Вызывай, когда нужно назвать двигатель или узнать, какие руководства применимы."
)


class Args(BaseModel):
    vehicle_id: str = Field(min_length=1, description="Госномер машины, как в диалоге")


def run(rt: Runtime, args: Args) -> dict:
    vehicle = rt.deps.vehicles.get(args.vehicle_id)
    if vehicle is None:
        return {"ok": False, "error": "Машина с таким госномером не найдена."}
    if args.vehicle_id != rt.turn.vehicle_id:
        return {"ok": False, "error": "Машина этого диалога — другая. Работайте с ней."}
    return {
        "ok": True,
        "vehicle_id": vehicle.vehicle_id,
        "garage_no": vehicle.garage_no,
        "make": vehicle.make,
        "model": vehicle.model,
        "vehicle_type": vehicle.vehicle_type,
        "engine_model": vehicle.engine_model,
        "fuel": vehicle.fuel,
        "manuals": sorted(rt.engine_manuals(vehicle.engine_model)),
    }
