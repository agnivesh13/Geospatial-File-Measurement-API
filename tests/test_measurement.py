import re

import pytest
import shapely
from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
)

from app.domain import MeasurementKind, MeasurementStatus, ParsedFeature
from app.geo.measurement import measure_feature
from tests.sample_data import BENGALURU, bowtie, geodesic_area, geodesic_length, line, square

# One part per million. UTM's scale factor alone would be off by up to ~1,000 parts per million.
RELATIVE_TOLERANCE = 1e-6


def feature(geometry, source_crs: str | None = "EPSG:4326") -> ParsedFeature:
    return ParsedFeature(index=0, layer="test", geometry=geometry, properties={}, source_crs=source_crs)


@pytest.mark.parametrize("side_m", [10.0, 1_000.0, 20_000.0, 100_000.0])
def test_polygon_area_matches_the_geodesic_reference(side_m):
    polygon = square(side_m=side_m)

    result = measure_feature(feature(polygon))

    assert result.status is MeasurementStatus.MEASURED
    assert (result.kind, result.unit) == (MeasurementKind.AREA, "m2")
    assert result.value == pytest.approx(geodesic_area(polygon), rel=RELATIVE_TOLERANCE)


@pytest.mark.parametrize("center", [(10.75, 59.91), (-58.38, -34.60), (0.0, 0.0)])
def test_area_stays_accurate_at_any_latitude(center):
    polygon = square(center=center, side_m=1_000.0)

    assert measure_feature(feature(polygon)).value == pytest.approx(geodesic_area(polygon), rel=RELATIVE_TOLERANCE)


def test_polygon_holes_are_subtracted():
    outer, hole = square(side_m=1_000.0), square(side_m=200.0)
    field = Polygon(outer.exterior.coords, [hole.exterior.coords])

    result = measure_feature(feature(field))

    assert result.value == pytest.approx(geodesic_area(outer) - geodesic_area(hole), rel=RELATIVE_TOLERANCE)


def test_multipolygon_area_is_the_sum_of_its_parts():
    east = square(center=(BENGALURU[0] + 0.05, BENGALURU[1]))
    parts = MultiPolygon([square(), east])

    assert measure_feature(feature(parts)).value == pytest.approx(geodesic_area(parts), rel=RELATIVE_TOLERANCE)


@pytest.mark.parametrize("length_m", [100.0, 5_000.0, 50_000.0])
def test_line_length_matches_the_geodesic_reference(length_m):
    road = line(length_m=length_m)

    result = measure_feature(feature(road))

    assert (result.kind, result.unit) == (MeasurementKind.LENGTH, "m")
    assert result.value == pytest.approx(geodesic_length(road), rel=RELATIVE_TOLERANCE)
    assert "+proj=aeqd" in result.projection


def test_bent_line_length_matches_the_geodesic_reference():
    corner = line(bearing=0.0, length_m=10_000.0).coords[-1]
    bent = LineString([*line(bearing=0.0, length_m=10_000.0).coords, *line(start=corner, bearing=90.0).coords[1:]])

    assert measure_feature(feature(bent)).value == pytest.approx(geodesic_length(bent), rel=RELATIVE_TOLERANCE)


def test_multilinestring_length_is_the_sum_of_its_parts():
    roads = MultiLineString([line(bearing=0.0), line(bearing=90.0)])

    assert measure_feature(feature(roads)).value == pytest.approx(10_000.0, rel=RELATIVE_TOLERANCE)


def test_self_intersecting_polygon_is_repaired_before_measuring():
    shape = bowtie()
    assert shape.area == 0.0  # the two lobes cancel out without repair

    result = measure_feature(feature(shape))

    assert result.status is MeasurementStatus.MEASURED
    assert result.value == pytest.approx(geodesic_area(shapely.make_valid(shape)), rel=RELATIVE_TOLERANCE)
    assert "repaired" in result.note


def test_projection_is_centred_on_the_feature():
    polygon = square(center=(10.75, 59.91))

    projection = measure_feature(feature(polygon)).projection

    lat_0 = float(re.search(r"\+lat_0=(\S+)", projection).group(1))
    lon_0 = float(re.search(r"\+lon_0=(\S+)", projection).group(1))
    assert (lon_0, lat_0) == pytest.approx((polygon.centroid.x, polygon.centroid.y), abs=1e-5)


@pytest.mark.parametrize("geometry", [Point(BENGALURU), MultiPoint([BENGALURU, (77.6, 12.98)])])
def test_points_need_no_measurement(geometry):
    result = measure_feature(feature(geometry))

    assert result.status is MeasurementStatus.NOT_REQUIRED
    assert result.value is None


def test_geometry_collections_are_reported_as_unsupported_not_crashed():
    mixed = GeometryCollection([Point(BENGALURU), line()])

    result = measure_feature(feature(mixed))

    assert result.status is MeasurementStatus.UNSUPPORTED_GEOMETRY
    assert "GeometryCollection" in result.note


@pytest.mark.parametrize("geometry", [None, Polygon()])
def test_missing_or_empty_geometry(geometry):
    assert measure_feature(feature(geometry)).status is MeasurementStatus.EMPTY_GEOMETRY


def test_unknown_crs_is_never_measured():
    assert measure_feature(feature(square(), source_crs=None)).status is MeasurementStatus.UNKNOWN_CRS


@pytest.mark.parametrize(
    "geometry",
    [LineString([(10, 95), (11, 96)]), Polygon([(500_000, 1_400_000), (501_000, 1_400_000), (501_000, 1_401_000)])],
)
def test_coordinates_outside_the_lon_lat_range_are_reported_not_crashed(geometry):
    result = measure_feature(feature(geometry))

    assert result.status is MeasurementStatus.INVALID_COORDINATES
    assert "declared CRS" in result.note
