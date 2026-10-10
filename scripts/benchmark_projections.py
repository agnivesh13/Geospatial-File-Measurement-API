"""Compare ways of measuring area against Karney's geodesic reference, and time the service's measurer.

Run from the repository root:  python -m scripts.benchmark_projections
"""

import sys
import time

from geopandas import GeoSeries

from app.domain import ParsedFeature
from app.geo.measurement import measure_feature
from tests.sample_data import geodesic_area, square

SITES = {
    "Bengaluru (2.6° from UTM central meridian)": (77.5946, 12.9716),
    "On a UTM central meridian (75°E)": (75.0, 12.9716),
    "Near a UTM zone edge (77.9°E)": (77.9, 12.9716),
    "Oslo (60°N)": (10.75, 59.91),
}
SIDES_M = (1_000.0, 100_000.0)


def relative_error_ppm(value: float, reference: float) -> float:
    return (value - reference) / reference * 1e6


def planar_area(polygon, crs) -> float:
    return GeoSeries([polygon], crs="EPSG:4326").to_crs(crs).area.iloc[0]


def ours(polygon) -> float:
    return measure_feature(ParsedFeature(0, "bench", polygon, {}, "EPSG:4326")).value


def accuracy_table() -> str:
    rows = [
        "| Site | Square side | Web Mercator (EPSG:3857) | UTM zone | This service (local LAEA) |",
        "|---|---|---|---|---|",
    ]
    for site, center in SITES.items():
        for side in SIDES_M:
            polygon = square(center=center, side_m=side)
            reference = geodesic_area(polygon)
            utm = GeoSeries([polygon], crs="EPSG:4326").estimate_utm_crs()
            rows.append(
                f"| {site} | {side / 1000:g} km "
                f"| {relative_error_ppm(planar_area(polygon, 'EPSG:3857'), reference):+,.0f} ppm "
                f"| {relative_error_ppm(planar_area(polygon, utm), reference):+,.0f} ppm "
                f"| {relative_error_ppm(ours(polygon), reference):+.4f} ppm |"
            )
    return "\n".join(rows)


def throughput(count: int = 2_000) -> str:
    polygons = [square(center=(77.5 + i * 1e-3, 12.9), side_m=200.0) for i in range(count)]
    start = time.perf_counter()
    for polygon in polygons:
        ours(polygon)
    elapsed = time.perf_counter() - start
    return f"Measured {count} polygons in {elapsed:.2f} s ({count / elapsed:,.0f} features/s)."


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # site names contain "°"
    print("Relative area error vs Karney geodesic reference (ppm = parts per million):\n")
    print(accuracy_table())
    print()
    print(throughput())
