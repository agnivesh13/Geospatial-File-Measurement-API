"""Builders for test and sample files. Shapes sit around Bengaluru.

Shapes are built with geodesic "walk this far on this bearing" steps (pyproj.Geod.fwd), so their
true size is known. Tests then compare our projected measurements against Karney's geodesic
algorithm, an independent reference accurate to about 15 nanometres.
"""

import math
import zipfile
from collections.abc import Iterable
from pathlib import Path
from tempfile import TemporaryDirectory
from xml.sax.saxutils import escape

from geopandas import GeoDataFrame
from pyproj import Geod
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry

BENGALURU = (77.5946, 12.9716)
GEOD = Geod(ellps="WGS84")


def square(center: tuple[float, float] = BENGALURU, side_m: float = 1000.0) -> Polygon:
    lon, lat = center
    half_diagonal = side_m / math.sqrt(2)
    corners = [GEOD.fwd(lon, lat, azimuth, half_diagonal)[:2] for azimuth in (45, 135, 225, 315)]
    return Polygon(corners)


def line(start: tuple[float, float] = BENGALURU, bearing: float = 60.0, length_m: float = 5000.0) -> LineString:
    lon, lat = start
    end_lon, end_lat, _ = GEOD.fwd(lon, lat, bearing, length_m)
    return LineString([(lon, lat), (end_lon, end_lat)])


def bowtie(center: tuple[float, float] = BENGALURU, size_deg: float = 0.01) -> Polygon:
    """A self-intersecting ring: its raw shoelace area cancels to zero."""
    lon, lat = center
    return Polygon([(lon, lat), (lon + size_deg, lat + size_deg), (lon + size_deg, lat), (lon, lat + size_deg)])


def geodesic_area(geometry: BaseGeometry) -> float:
    return abs(GEOD.geometry_area_perimeter(geometry)[0])


def geodesic_length(geometry: BaseGeometry) -> float:
    return GEOD.geometry_length(geometry)


# --- KML -------------------------------------------------------------------------------------

def kml_document(folders: dict[str, list[str]]) -> str:
    body = "".join(f"<Folder><name>{escape(name)}</name>{''.join(items)}</Folder>" for name, items in folders.items())
    return f'<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>{body}</Document></kml>'


def placemark(name: str, geometry_xml: str = "", data: dict[str, str] | None = None) -> str:
    extended = "".join(f'<Data name="{escape(k)}"><value>{escape(v)}</value></Data>' for k, v in (data or {}).items())
    extended_xml = f"<ExtendedData>{extended}</ExtendedData>" if extended else ""
    return f"<Placemark><name>{escape(name)}</name>{extended_xml}{geometry_xml}</Placemark>"


def kml_polygon(polygon: Polygon) -> str:
    inner = "".join(f"<innerBoundaryIs>{_ring(ring.coords)}</innerBoundaryIs>" for ring in polygon.interiors)
    return f"<Polygon><outerBoundaryIs>{_ring(polygon.exterior.coords)}</outerBoundaryIs>{inner}</Polygon>"


def kml_line(geometry: LineString) -> str:
    return f"<LineString><coordinates>{_coordinates(geometry.coords)}</coordinates></LineString>"


def kml_point(point: Point) -> str:
    return f"<Point><coordinates>{point.x},{point.y}</coordinates></Point>"


def kml_multigeometry(*geometries_xml: str) -> str:
    return f"<MultiGeometry>{''.join(geometries_xml)}</MultiGeometry>"


def survey_kml() -> str:
    """A field survey covering every case: area, length, repair, point, unsupported and empty."""
    return kml_document(
        {
            "Fields": [
                placemark("north field", kml_polygon(square(side_m=1_000.0)), {"owner": "Asha"}),
                placemark("crossed fence", kml_polygon(bowtie())),
            ],
            "Assets": [
                placemark("access road", kml_line(line(length_m=5_000.0))),
                placemark("well", kml_point(Point(BENGALURU))),
                placemark("mixed", kml_multigeometry(kml_point(Point(BENGALURU)), kml_line(line()))),
                placemark("no geometry"),
            ],
        }
    )


def _ring(coords: Iterable[tuple[float, ...]]) -> str:
    return f"<LinearRing><coordinates>{_coordinates(coords)}</coordinates></LinearRing>"


def _coordinates(coords: Iterable[tuple[float, ...]]) -> str:
    return " ".join(",".join(f"{value:.9f}" for value in xy) for xy in coords)


# --- Shapefile -------------------------------------------------------------------------------

def frame(
    geometries: Iterable[BaseGeometry], crs: str | None = "EPSG:4326", names: list[str] | None = None
) -> GeoDataFrame:
    shapes = list(geometries)
    labels = names or [f"feature {i}" for i in range(len(shapes))]
    return GeoDataFrame({"name": labels}, geometry=shapes, crs=crs)


def shapefile_zip(
    target: Path,
    frame: GeoDataFrame,
    *,
    skip_suffixes: tuple[str, ...] = (),
    folder: str = "",
    extra_members: dict[str, bytes] | None = None,
) -> Path:
    """Write ``frame`` as a shapefile and zip its parts (optionally leaving some out)."""
    with TemporaryDirectory() as tmp:
        frame.to_file(Path(tmp) / "layer.shp")
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            for part in sorted(Path(tmp).iterdir()):
                if part.suffix not in skip_suffixes:
                    archive.write(part, f"{folder}{part.name}")
            for name, content in (extra_members or {}).items():
                archive.writestr(name, content)
    return target
