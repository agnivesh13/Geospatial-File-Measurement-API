"""All database access for uploaded files, so the service never writes SQL itself."""

from dataclasses import dataclass
from typing import Any

import numpy as np
import shapely
from shapely.geometry import mapping
from shapely.geometry.base import BaseGeometry
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain import FileStatus, MeasuredFeature, MeasurementKind, MeasurementStatus
from app.errors import FileNotFound
from app.models import Feature, GeoFile


@dataclass(frozen=True)
class MeasurementSummary:
    total_area_m2: float
    total_length_m: float
    status_counts: dict[MeasurementStatus, int]


class GeoFileRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def start(self, filename: str) -> GeoFile:
        record = GeoFile(filename=filename, status=FileStatus.PROCESSING)
        self._save(record)
        return record

    def complete(self, record: GeoFile, crs: str | None, measured: list[MeasuredFeature]) -> None:
        record.crs = crs
        record.feature_count = len(measured)
        record.features = [_to_row(item) for item in measured]
        record.status = FileStatus.COMPLETED
        self._save(record)

    def fail(self, record: GeoFile, reason: str) -> None:
        self._session.rollback()  # discard any half-written features
        record.status = FileStatus.FAILED
        record.error = reason
        self._save(record)

    def get(self, file_id: str) -> GeoFile:
        record = self._session.get(GeoFile, file_id)
        if record is None:
            raise FileNotFound(f"No file with id {file_id!r}.")
        return record

    def features_page(self, file_id: str, offset: int, limit: int) -> list[Feature]:
        query = (
            select(Feature)
            .where(Feature.file_id == file_id)
            .order_by(Feature.feature_index)
            .offset(offset)
            .limit(limit)
        )
        return list(self._session.scalars(query))

    def summary(self, file_id: str) -> MeasurementSummary:
        totals = self._totals_by_kind(file_id)
        return MeasurementSummary(
            total_area_m2=totals.get(MeasurementKind.AREA, 0.0),
            total_length_m=totals.get(MeasurementKind.LENGTH, 0.0),
            status_counts=self._counts_by_status(file_id),
        )

    def _totals_by_kind(self, file_id: str) -> dict[MeasurementKind, float]:
        query = (
            select(Feature.measurement_kind, func.sum(Feature.measurement_value))
            .where(Feature.file_id == file_id, Feature.measurement_status == MeasurementStatus.MEASURED)
            .group_by(Feature.measurement_kind)
        )
        return {kind: total for kind, total in self._session.execute(query)}

    def _counts_by_status(self, file_id: str) -> dict[MeasurementStatus, int]:
        query = (
            select(Feature.measurement_status, func.count())
            .where(Feature.file_id == file_id)
            .group_by(Feature.measurement_status)
        )
        return {status: count for status, count in self._session.execute(query)}

    def _save(self, record: GeoFile) -> None:
        self._session.add(record)
        self._session.commit()


def _to_row(item: MeasuredFeature) -> Feature:
    feature = item.feature
    return Feature(
        feature_index=feature.index,
        layer=feature.layer,
        geometry_type=feature.geometry_type,
        source_crs=feature.source_crs,
        geometry=_geojson(feature.geometry),
        properties=feature.properties,
        measurement=item.measurement,
    )


def _geojson(geometry: BaseGeometry | None) -> dict[str, Any] | None:
    """GeoJSON (and JSON) cannot hold NaN or infinity, which reprojecting nonsense coordinates
    produces. Such geometries are stored as null; their measurement already says INVALID_COORDINATES."""
    if geometry is None or not np.isfinite(shapely.get_coordinates(geometry)).all():
        return None
    return mapping(geometry)
