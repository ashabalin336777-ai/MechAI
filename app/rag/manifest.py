"""Реестр руководств из data/manuals/manifest.yaml (ТЗ §3.2)."""

from pathlib import Path
from typing import Annotated

import yaml
from pydantic import BaseModel, Field, StringConstraints

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class ManualEntry(BaseModel):
    id: Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]+$")]
    designation: str
    title: str
    year: int
    file: str
    sha256: Sha256
    pages: int = Field(ge=1)
    engine_models: list[str] = Field(min_length=1)


class Manifest(BaseModel):
    manuals: list[ManualEntry]


def load_manifest(path: Path) -> Manifest:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Manifest.model_validate(raw)
