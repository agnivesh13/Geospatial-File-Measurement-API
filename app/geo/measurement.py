"""Measure one feature: area for polygons, length for lines, nothing for points.

Strategy pattern: each geometry type maps to a measurer with the same ``measure`` method, so
supporting another type is one dictionary entry, not another if/elif branch. ``NoMeasurement`` is a
Null Object for the types we deliberately do not measure.
"""

import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
from operator import attrgetter
from typing import Protocol

import shapely
from pyproj.exceptions import GeodError, ProjError
from shapely.errors import GEOSException
from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry

from app.domain import Measurement, MeasurementKind, MeasurementStatus, ParsedFeature
from app.geo.projection import LocalProjection, follow_geodesics, local_equal_area, local_equidistant

logger = logging.getLogger(__name__)

MAX_LONGITUDE = 180.0
MAX_LATITUDE = 90.0
REPAIRED_NOTE = (
    "The geometry was invalid (for example self-intersecting) and was repaired with "
    "shapely.make_valid before measuring."
)
UNKNOWN_CRS_NOTE = (
    "The file declares no CRS (for example a shapefile without a .prj). "
    "Upload it again with the source_crs form field."
)
INVALID_COORDINATES_NOTE = (
    "Coordinates fall outside longitude -180..180 / latitude -90..90. Is the declared CRS correct?"
)


class Measurer(Protocol):
    def measure(self, geometry: BaseGeometry) -> Measurement: ...


@dataclass(frozen=True)
class ProjectedMeasurer:
    """Projects into a local CRS that preserves the measured property, then reads one quantity."""

    kind: MeasurementKind
    unit: str
    local_projection: Callable[[Point], LocalProjection]
    quantity: Callable[[BaseGeometry], float]

    def measure(self, geometry: BaseGeometry) -> Measurement:
        valid, repaired = _repair_if_invalid(geometry)
        projection = self.local_projection(valid.centroid)
        value = self.quantity(projection.project(follow_geodesics(valid)))
        if not math.isfinite(value):  # NaN/inf would also break the JSON response
            raise ValueError(f"Projected {self.kind} is not a finite number: {value}")
        return Measurement.measured(
            self.kind, value, self.unit, projection.definition, REPAIRED_NOTE if repaired else None
        )


@dataclass(frozen=True)
class NoMeasurement:
    """Null Object: returns a skipped measurement instead of the caller checking types itself."""

    status: MeasurementStatus
    note: str

    def measure(self, geometry: BaseGeometry) -> Measurement:
        return Measurement.skipped(self.status, self.note.format(geometry_type=geometry.geom_type))


AREA = ProjectedMeasurer(MeasurementKind.AREA, "m2", local_equal_area, attrgetter("area"))
LENGTH = ProjectedMeasurer(MeasurementKind.LENGTH, "m", local_equidistant, attrgetter("length"))
NOT_REQUIRED = NoMeasurement(
    MeasurementStatus.NOT_REQUIRED, "{geometry_type} features have no area or length."
)
UNSUPPORTED = NoMeasurement(
    MeasurementStatus.UNSUPPORTED_GEOMETRY, "Measuring {geometry_type} geometries is not supported."
)

MEASURERS: dict[str, Measurer] = {
    "Polygon": AREA,
    "MultiPolygon": AREA,
    "LineString": LENGTH,
    "MultiLineString": LENGTH,
    "LinearRing": LENGTH,
    "Point": NOT_REQUIRED,
    "MultiPoint": NOT_REQUIRED,
}


def measure_feature(feature: ParsedFeature) -> Measurement:
    geometry = feature.geometry
    if geometry is None or geometry.is_empty:
        return Measurement.skipped(MeasurementStatus.EMPTY_GEOMETRY, "The feature has no geometry.")
    if feature.source_crs is None:
        return Measurement.skipped(MeasurementStatus.UNKNOWN_CRS, UNKNOWN_CRS_NOTE)
    if not _within_lon_lat_range(geometry):
        return Measurement.skipped(MeasurementStatus.INVALID_COORDINATES, INVALID_COORDINATES_NOTE)
    return _measure_safely(geometry)


def measurer_for(geometry_type: str) -> Measurer:
    return MEASURERS.get(geometry_type, UNSUPPORTED)


def _measure_safely(geometry: BaseGeometry) -> Measurement:
    """One malformed feature must not fail the whole file."""
    try:
        return measurer_for(geometry.geom_type).measure(geometry)
    except (GEOSException, ProjError, GeodError, ValueError) as exc:
        logger.warning("Could not measure a %s geometry: %s", geometry.geom_type, exc)
        return Measurement.skipped(MeasurementStatus.FAILED, "The geometry could not be measured.")


def _within_lon_lat_range(geometry: BaseGeometry) -> bool:
    min_lon, min_lat, max_lon, max_lat = geometry.bounds
    return (
        -MAX_LONGITUDE <= min_lon <= max_lon <= MAX_LONGITUDE
        and -MAX_LATITUDE <= min_lat <= max_lat <= MAX_LATITUDE
    )


def _repair_if_invalid(geometry: BaseGeometry) -> tuple[BaseGeometry, bool]:
    """Invalid polygons give wrong areas (a self-intersecting bowtie measures 0), so repair them."""
    if geometry.is_valid:
        return geometry, False
    return shapely.make_valid(geometry), True
