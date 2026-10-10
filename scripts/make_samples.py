"""Write demo files into ``samples/`` for trying the API by hand (e.g. from /docs).

Run from the repository root:  python -m scripts.make_samples
"""

from pathlib import Path

from shapely.geometry import MultiPolygon

from tests.sample_data import BENGALURU, frame, line, shapefile_zip, square, survey_kml

SAMPLES = Path("samples")
LON, LAT = BENGALURU


def main() -> None:
    SAMPLES.mkdir(exist_ok=True)
    (SAMPLES / "bengaluru_survey.kml").write_text(survey_kml(), encoding="utf-8")

    parcels = [
        square(side_m=1_000.0),
        square(center=(LON + 0.02, LAT), side_m=250.0),
        MultiPolygon([square(center=(LON, LAT + 0.02), side_m=300.0), square(center=(LON + 0.01, LAT + 0.02), side_m=300.0)]),
    ]
    shapefile_zip(SAMPLES / "bengaluru_parcels_wgs84.zip", frame(parcels, names=["1 km block", "plot A", "split plot"]))

    roads = [line(length_m=5_000.0), line(bearing=150.0, length_m=12_500.0)]
    utm = frame(roads, names=["ring road stretch", "airport link"]).to_crs("EPSG:32643")
    shapefile_zip(SAMPLES / "bengaluru_roads_utm43n.zip", utm)

    shapefile_zip(SAMPLES / "parcels_without_prj.zip", frame([square()], names=["unknown CRS"]), skip_suffixes=(".prj",))
    print(f"Wrote {len(list(SAMPLES.iterdir()))} files to {SAMPLES.resolve()}")


if __name__ == "__main__":
    main()
