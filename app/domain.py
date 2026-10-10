"""Core types shared by the readers, measurers, service and API. No web or database imports here."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from shapely.geometry.base import BaseGeometry


class FileStatus(StrEnum):
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class MeasurementKind(StrEnum):
    AREA = "area"
    LENGTH = "length"


class MeasurementStatus(StrEnum):
    MEASURED = "MEASURED"
    NOT_REQUIRED = "NOT_REQUIRED"
    UNSUPPORTED_GEOMETRY = "UNSUPPORTED_GEOMETRY"
    EMPTY_GEOMETRY = "EMPTY_GEOMETRY"
    UNKNOWN_CRS = "UNKNOWN_CRS"
    INVALID_COORDINATES = "INVALID_COORDINATES"
    FAILED = "FAILED"


@dataclass(frozen=True)
class Measurement:
    """Result of measuring one feature. ``projection`` records exactly which projected CRS was used."""

    status: MeasurementStatus
    kind: MeasurementKind | None = None
    value: float | None = None
    unit: str | None = None
    projection: str | None = None
    note: str | None = None

    @classmethod
    def measured(
        cls, kind: MeasurementKind, value: float, unit: str, projection: str, note: str | None = None
    ) -> "Measurement":
        return cls(MeasurementStatus.MEASURED, kind, value, unit, projection, note)

    @classmethod
    def skipped(cls, status: MeasurementStatus, note: str) -> "Measurement":
        return cls(status, note=note)


@dataclass(frozen=True)
class ParsedFeature:
    """One feature read from an uploaded file.

    ``geometry`` is in WGS 84 longitude/latitude whenever ``source_crs`` is known, because the readers
    reproject it on the way in. When the file declares no CRS, the geometry keeps its raw coordinates.
    """

    index: int
    layer: str
    geometry: BaseGeometry | None
    properties: dict[str, Any]
    source_crs: str | None

    @property
    def geometry_type(self) -> str | None:
        return None if self.geometry is None else self.geometry.geom_type


@dataclass(frozen=True)
class ParsedDataset:
    """Everything read from one file. ``crs`` is the file-level CRS label, or None when undeclared."""

    crs: str | None
    features: list[ParsedFeature]


@dataclass(frozen=True)
class MeasuredFeature:
    feature: ParsedFeature
    measurement: Measurement
