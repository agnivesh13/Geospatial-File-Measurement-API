"""Local projected CRSs for measuring a single feature.

Why not measure in degrees? A degree of longitude shrinks from about 111 km at the equator to 0 km
at the poles, so planar area or length computed on EPSG:4326 coordinates is meaningless.

Why not UTM? Its 0.9996 central scale factor alone makes areas 0.08 % too small on the central
meridian, and up to about 0.2 % too large at the zone edges. Yildirim & Kaya (2008) measured about
8,000 m² of UTM error on a 1,000 ha parcel. Instead we follow the selection rule behind Projection
Wizard (Šavrič et al. 2016, after Snyder 1987): pick the property that must be preserved, then
centre the projection on the area of interest.
- Area uses Lambert Azimuthal Equal-Area, centred on the feature. It preserves area everywhere.
- Length uses Azimuthal Equidistant, centred on the feature. Its scale error is about
  (r/R)²/6 at distance r from the centre (R = Earth radius): one part per million at 15 km.
  A transverse Mercator at the same distance is three times worse.

An edge between two vertices is taken to be the geodesic (the shortest path on the ellipsoid), the
same reading as PostGIS ``geography``, QGIS ellipsoidal measurement and Karney (2013). So long edges
are densified along their geodesic before projecting.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from itertools import pairwise

import numpy as np
import shapely
from pyproj import Geod, Transformer
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry, BaseMultipartGeometry

GEOD = Geod(ellps="WGS84")
# Edges up to 1 km already agree with the geodesic to about one part per billion.
MAX_EDGE_M = 1_000.0


@dataclass(frozen=True)
class LocalProjection:
    """A projected CRS centred on one feature. ``definition`` is a PROJ string, so anyone can
    reproduce a measurement (for example by pasting it into QGIS as a custom CRS)."""

    definition: str

    def project(self, geometry: BaseGeometry) -> BaseGeometry:
        """Reproject a WGS 84 longitude/latitude geometry into this CRS. Z values are dropped."""
        # An explicit pipeline skips PROJ's CRS-to-CRS operation search (about 6x faster to build).
        # Source and target share the WGS 84 ellipsoid, so no datum shift is involved.
        transformer = Transformer.from_pipeline(
            f"+proj=pipeline +step +proj=unitconvert +xy_in=deg +xy_out=rad +step {self.definition}"
        )
        return shapely.transform(
            geometry, lambda xy: np.column_stack(transformer.transform(xy[:, 0], xy[:, 1]))
        )


def local_equal_area(center: Point) -> LocalProjection:
    return _centred_on(center, "laea")


def local_equidistant(center: Point) -> LocalProjection:
    return _centred_on(center, "aeqd")


def follow_geodesics(geometry: BaseGeometry, max_edge_m: float = MAX_EDGE_M) -> BaseGeometry:
    """Add vertices along every edge longer than ``max_edge_m`` (WGS 84 input), so the edge follows
    its geodesic once projected. Shapely geometries cannot be extended with methods, so this is a
    foreign function that dispatches on the geometry's class."""
    match geometry:
        case Polygon():
            return Polygon(
                _densify(geometry.exterior.coords, max_edge_m),
                [_densify(ring.coords, max_edge_m) for ring in geometry.interiors],
            )
        case LineString():  # LinearRing is a LineString too
            return type(geometry)(_densify(geometry.coords, max_edge_m))
        case BaseMultipartGeometry():
            return type(geometry)([follow_geodesics(part, max_edge_m) for part in geometry.geoms])
        case _:
            return geometry


def _densify(coords: Iterable[Sequence[float]], max_edge_m: float) -> list[tuple[float, float]]:
    points = [(x, y) for x, y, *_z in coords]
    if len(points) < 2:
        return points
    lons, lats = np.array(points).T
    _, _, distances = GEOD.inv(lons[:-1], lats[:-1], lons[1:], lats[1:])
    dense = points[:1]
    for (start, end), distance in zip(pairwise(points), distances, strict=True):
        extra_points = int(distance // max_edge_m)
        if extra_points:
            dense.extend(GEOD.npts(*start, *end, extra_points))
        dense.append(end)
    return dense


def _centred_on(center: Point, projection: str) -> LocalProjection:
    return LocalProjection(
        f"+proj={projection} +lat_0={center.y:.6f} +lon_0={center.x:.6f} +ellps=WGS84 +units=m"
    )
