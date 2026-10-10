import pytest
from shapely.geometry import Point

from app.config import Settings
from app.errors import InvalidCrs, UnreadableGeoFile, UnsupportedFileType
from app.geo.crs import parse_crs
from app.geo.readers import KmlReader, ShapefileZipReader, reader_for
from tests.sample_data import (
    BENGALURU,
    frame,
    kml_document,
    kml_line,
    kml_point,
    kml_polygon,
    line,
    placemark,
    shapefile_zip,
    square,
)

LIMIT = 10 * 1024 * 1024


def write_kml(tmp_path, folders) -> object:
    path = tmp_path / "test.kml"
    path.write_text(kml_document(folders), encoding="utf-8")
    return path


def test_kml_reader_reads_every_folder(tmp_path):
    path = write_kml(
        tmp_path,
        {
            "Fields": [placemark("field", kml_polygon(square()))],
            "Roads": [placemark("road", kml_line(line())), placemark("gate", kml_point(Point(BENGALURU)))],
        },
    )

    dataset = KmlReader().read(path)

    assert [(f.index, f.layer, f.geometry_type) for f in dataset.features] == [
        (0, "Fields", "Polygon"),
        (1, "Roads", "LineString"),
        (2, "Roads", "Point"),
    ]
    assert dataset.crs == "EPSG:4326"


def test_kml_properties_keep_data_and_drop_styling_and_blanks(tmp_path):
    path = write_kml(tmp_path, {"Fields": [placemark("field", kml_polygon(square()), {"owner": "Asha", "crop": "ragi"})]})

    properties = KmlReader().read(path).features[0].properties

    assert properties == {"Name": "field", "owner": "Asha", "crop": "ragi"}


def test_projected_shapefile_is_reprojected_to_wgs84_and_labelled(tmp_path):
    utm = frame([line()]).to_crs("EPSG:32643")  # UTM zone 43N, in metres
    archive = shapefile_zip(tmp_path / "roads.zip", utm)

    dataset = ShapefileZipReader(LIMIT).read(archive)

    assert dataset.crs == "EPSG:32643"
    start_lon, start_lat = dataset.features[0].geometry.coords[0]
    assert (start_lon, start_lat) == pytest.approx(BENGALURU, abs=1e-7)


def test_shapefile_without_prj_has_unknown_crs(tmp_path):
    archive = shapefile_zip(tmp_path / "a.zip", frame([square()]), skip_suffixes=(".prj",))

    dataset = ShapefileZipReader(LIMIT).read(archive)

    assert dataset.crs is None
    assert dataset.features[0].source_crs is None


def test_fallback_crs_is_used_only_when_the_file_declares_none(tmp_path):
    with_prj = shapefile_zip(tmp_path / "with.zip", frame([square()]))
    without_prj = shapefile_zip(tmp_path / "without.zip", frame([square()]), skip_suffixes=(".prj",))
    utm = parse_crs("EPSG:32643")

    assert ShapefileZipReader(LIMIT).read(with_prj, utm).crs == "EPSG:4326"
    assert ShapefileZipReader(LIMIT).read(without_prj, parse_crs("EPSG:4326")).crs == "EPSG:4326"


def test_unreadable_file_raises_a_domain_error(tmp_path):
    path = tmp_path / "broken.kml"
    path.write_bytes(b"\x00\x01 this is not KML")

    with pytest.raises(UnreadableGeoFile):
        KmlReader().read(path)


@pytest.mark.parametrize("filename", ["notes.txt", "survey.kml.exe", "no_extension"])
def test_reader_factory_rejects_unsupported_extensions(filename):
    with pytest.raises(UnsupportedFileType):
        reader_for(filename, Settings())


@pytest.mark.parametrize(("filename", "reader_type"), [("Survey.KML", KmlReader), ("parcels.zip", ShapefileZipReader)])
def test_reader_factory_picks_the_reader_by_extension(filename, reader_type):
    assert isinstance(reader_for(filename, Settings()), reader_type)


def test_parse_crs_rejects_nonsense():
    with pytest.raises(InvalidCrs):
        parse_crs("EPSG:not-a-code")
