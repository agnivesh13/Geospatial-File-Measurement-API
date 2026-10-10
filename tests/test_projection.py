import pytest
from pyproj import CRS, Transformer
from shapely.geometry import GeometryCollection, LineString, Point, Polygon

from app.geo.projection import GEOD, follow_geodesics, local_equal_area, local_equidistant
from tests.sample_data import BENGALURU, line, square


def edge_lengths(geometry: LineString) -> list[float]:
    lons, lats = zip(*geometry.coords, strict=True)
    return list(GEOD.inv(lons[:-1], lats[:-1], lons[1:], lats[1:])[2])


def test_long_edges_are_split_into_segments_no_longer_than_the_limit():
    road = line(length_m=10_500.0)

    dense = follow_geodesics(road, max_edge_m=1_000.0)

    assert len(dense.coords) == 12  # 10 extra points -> 11 segments of ~955 m
    assert max(edge_lengths(dense)) <= 1_000.0
    assert dense.coords[0] == road.coords[0] and dense.coords[-1] == road.coords[-1]


def test_short_edges_are_left_alone():
    small = square(side_m=500.0)

    assert follow_geodesics(small).equals(small)


def test_polygon_holes_and_collections_are_densified_too():
    outer, hole = square(side_m=5_000.0), square(side_m=2_000.0)
    field = Polygon(outer.exterior.coords, [hole.exterior.coords])

    dense = follow_geodesics(GeometryCollection([field, Point(BENGALURU)]))

    dense_field, point = dense.geoms
    assert len(dense_field.exterior.coords) > len(outer.exterior.coords)
    assert len(dense_field.interiors[0].coords) > len(hole.exterior.coords)
    assert point.equals(Point(BENGALURU))


def test_z_values_are_dropped():
    assert not follow_geodesics(LineString([(77.59, 12.97, 900.0), (77.60, 12.98, 905.0)])).has_z


def test_local_projection_is_centred_on_the_given_point():
    centre = local_equal_area(Point(BENGALURU)).project(Point(BENGALURU))

    assert (centre.x, centre.y) == pytest.approx((0.0, 0.0), abs=1e-6)


def test_projection_definition_is_a_valid_metric_crs_users_can_reuse():
    crs = CRS.from_user_input(local_equidistant(Point(BENGALURU)).definition)

    assert crs.is_projected
    assert crs.axis_info[0].unit_name == "metre"


def test_pipeline_projection_matches_pyproj_crs_to_crs_transform():
    projection = local_equal_area(Point(BENGALURU))
    reference = Transformer.from_crs("EPSG:4326", CRS.from_user_input(projection.definition), always_xy=True)
    far_point = Point(78.5, 11.9)

    projected = projection.project(far_point)

    assert (projected.x, projected.y) == pytest.approx(reference.transform(far_point.x, far_point.y), abs=1e-6)
