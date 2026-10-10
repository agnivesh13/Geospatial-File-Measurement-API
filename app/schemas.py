"""Response bodies of the HTTP API."""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from app.domain import FileStatus, MeasurementKind, MeasurementStatus
from app.models import Feature
from app.service import MeasurementsPage


class FileInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    feature_count: int
    crs: str | None
    status: FileStatus
    error: str | None = None
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _assume_utc(cls, value: datetime) -> datetime:
        """SQLite drops the timezone on read; every timestamp is written in UTC."""
        return value if value.tzinfo else value.replace(tzinfo=UTC)


class MeasurementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: MeasurementStatus
    kind: MeasurementKind | None
    value: float | None
    unit: str | None
    projection: str | None
    note: str | None


class FeatureOut(BaseModel):
    feature_id: int
    layer: str
    geometry_type: str | None
    crs: str | None
    geometry: dict[str, Any] | None
    properties: dict[str, Any]
    measurement: MeasurementOut

    @classmethod
    def from_row(cls, row: Feature) -> "FeatureOut":
        return cls(
            feature_id=row.feature_index,
            layer=row.layer,
            geometry_type=row.geometry_type,
            crs=row.source_crs,
            geometry=row.geometry,
            properties=row.properties,
            measurement=MeasurementOut.model_validate(row.measurement),
        )


class SummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    total_area_m2: float
    total_length_m: float
    status_counts: dict[MeasurementStatus, int]


class MeasurementsResponse(BaseModel):
    file_id: str
    crs: str | None
    feature_count: int
    offset: int
    limit: int
    summary: SummaryOut
    features: list[FeatureOut]

    @classmethod
    def from_page(cls, page: MeasurementsPage, offset: int, limit: int) -> "MeasurementsResponse":
        return cls(
            file_id=page.file.id,
            crs=page.file.crs,
            feature_count=page.file.feature_count,
            offset=offset,
            limit=limit,
            summary=SummaryOut.model_validate(page.summary),
            features=[FeatureOut.from_row(row) for row in page.features],
        )
