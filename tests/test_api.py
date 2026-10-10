import zipfile

import pytest
from fastapi.testclient import TestClient
from pyproj import CRS
from shapely.geometry import LineString, Polygon

from app.config import Settings
from app.main import create_app
from tests.sample_data import BENGALURU, frame, line, shapefile_zip, square, survey_kml

SURVEY_KML = survey_kml().encode()


@pytest.fixture
def survey(upload) -> dict:
    response = upload("survey.kml", SURVEY_KML)
    assert response.status_code == 201, response.text
    return response.json()


def test_upload_returns_file_information(survey):
    assert survey["filename"] == "survey.kml"
    assert survey["feature_count"] == 6
    assert survey["crs"] == "EPSG:4326"
    assert survey["status"] == "COMPLETED"


def test_upload_sets_location_header(upload):
    response = upload("survey.kml", SURVEY_KML)

    assert response.headers["location"] == f"/api/files/{response.json()['id']}/"


def test_get_file_information(client, survey):
    response = client.get(f"/api/files/{survey['id']}/")

    assert response.status_code == 200
    assert response.json() == survey


def test_measurements_cover_every_feature(survey, measurements):
    body = measurements(survey["id"])
    by_name = {f["properties"]["Name"]: f for f in body["features"]}

    assert by_name["north field"]["measurement"]["value"] == pytest.approx(1_000_000, rel=1e-3)
    assert by_name["north field"]["properties"]["owner"] == "Asha"
    assert by_name["access road"]["measurement"]["value"] == pytest.approx(5_000.0, rel=1e-6)
    assert by_name["crossed fence"]["measurement"]["note"].startswith("The geometry was invalid")
    assert by_name["well"]["measurement"]["status"] == "NOT_REQUIRED"
    assert by_name["mixed"]["measurement"]["status"] == "UNSUPPORTED_GEOMETRY"
    assert by_name["no geometry"]["measurement"]["status"] == "EMPTY_GEOMETRY"


def test_each_feature_reports_index_type_geometry_crs_and_properties(survey, measurements):
    first = measurements(survey["id"])["features"][0]

    assert first["feature_id"] == 0
    assert first["layer"] == "Fields"
    assert first["geometry_type"] == "Polygon"
    assert first["crs"] == "EPSG:4326"
    assert first["geometry"]["type"] == "Polygon"  # GeoJSON (RFC 7946)
    assert first["properties"]["Name"] == "north field"


def test_summary_totals_and_counts(survey, measurements):
    summary = measurements(survey["id"])["summary"]

    assert summary["total_length_m"] == pytest.approx(5_000.0, rel=1e-6)
    assert summary["total_area_m2"] > 1_000_000
    assert summary["status_counts"] == {
        "MEASURED": 3,
        "NOT_REQUIRED": 1,
        "UNSUPPORTED_GEOMETRY": 1,
        "EMPTY_GEOMETRY": 1,
    }


def test_measurements_are_paginated(survey, measurements):
    page = measurements(survey["id"], offset=2, limit=2)

    assert [f["feature_id"] for f in page["features"]] == [2, 3]
    assert (page["offset"], page["limit"], page["feature_count"]) == (2, 2, 6)


def test_projected_shapefile_is_measured_in_metres_and_returned_as_wgs84(upload, measurements, tmp_path):
    archive = shapefile_zip(tmp_path / "roads.zip", frame([line(length_m=5_000.0)]).to_crs("EPSG:32643"))

    file_info = upload("roads.zip", archive.read_bytes()).json()
    feature = measurements(file_info["id"])["features"][0]

    assert file_info["crs"] == "EPSG:32643"
    assert feature["measurement"]["value"] == pytest.approx(5_000.0, rel=1e-6)
    assert feature["geometry"]["coordinates"][0] == pytest.approx(list(BENGALURU), abs=1e-7)


def test_missing_prj_is_reported_then_fixed_with_source_crs(upload, measurements, tmp_path):
    archive = shapefile_zip(tmp_path / "parcels.zip", frame([square()]), skip_suffixes=(".prj",)).read_bytes()

    unknown = upload("parcels.zip", archive).json()
    assumed = upload("parcels.zip", archive, source_crs="EPSG:4326").json()

    assert unknown["crs"] is None
    assert measurements(unknown["id"])["features"][0]["measurement"]["status"] == "UNKNOWN_CRS"
    assert measurements(assumed["id"])["features"][0]["measurement"]["status"] == "MEASURED"


def test_wrong_source_crs_marks_features_instead_of_failing_the_file(upload, measurements, tmp_path):
    utm_without_prj = frame([line()]).to_crs("EPSG:32643")
    archive = shapefile_zip(tmp_path / "roads.zip", utm_without_prj, skip_suffixes=(".prj",))

    response = upload("roads.zip", archive.read_bytes(), source_crs="EPSG:4326")  # wrong: it is UTM

    assert response.status_code == 201
    feature = measurements(response.json()["id"])["features"][0]
    assert feature["measurement"]["status"] == "INVALID_COORDINATES"


def test_coordinates_that_reproject_to_infinity_do_not_break_the_response(upload, measurements, tmp_path):
    absurd = frame([LineString([(1e12, 1e12), (1e12 + 5, 1e12 + 5)])], crs=None)
    archive = shapefile_zip(tmp_path / "absurd.zip", absurd, skip_suffixes=(".prj",))

    response = upload("absurd.zip", archive.read_bytes(), source_crs="EPSG:32643")
    feature = measurements(response.json()["id"])["features"][0]

    assert feature["measurement"]["status"] == "INVALID_COORDINATES"
    assert feature["geometry"] is None  # JSON cannot hold infinity


def test_crs_without_a_link_to_the_earth_is_rejected_clearly(upload, tmp_path):
    site_grid = CRS.from_wkt(
        'ENGCRS["Site grid",EDATUM["Local datum"],CS[Cartesian,2],'
        'AXIS["x",east,ORDER[1],LENGTHUNIT["metre",1]],AXIS["y",north,ORDER[2],LENGTHUNIT["metre",1]]]'
    )
    local = frame([Polygon([(0, 0), (100, 0), (100, 100)])], crs=site_grid)

    response = upload("site.zip", shapefile_zip(tmp_path / "site.zip", local).read_bytes())

    assert response.status_code == 422
    assert "cannot be converted to WGS 84" in response.json()["detail"]


def test_empty_kml_completes_with_no_features(upload):
    empty = b'<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document/></kml>'

    response = upload("empty.kml", empty)

    assert response.status_code == 201
    assert response.json()["feature_count"] == 0


def test_corrupt_shapefile_inside_a_valid_zip_is_recorded_as_failed(upload, tmp_path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        for suffix in (".shp", ".shx", ".dbf"):
            handle.writestr(f"bad{suffix}", b"garbage bytes")

    response = upload("bad.zip", archive.read_bytes())

    assert response.status_code == 422
    assert "could not be read" in response.json()["detail"]


def test_errors_use_rfc9457_problem_details(upload):
    response = upload("notes.txt", b"hello")

    assert response.status_code == 415
    assert response.headers["content-type"] == "application/problem+json"
    assert set(response.json()) == {"type", "title", "status", "detail", "instance"}


def test_empty_upload_is_rejected(upload):
    assert upload("survey.kml", b"").status_code == 400


def test_invalid_source_crs_is_rejected(upload):
    assert upload("survey.kml", SURVEY_KML, source_crs="EPSG:nonsense").status_code == 422


def test_oversized_upload_is_rejected(tmp_path):
    settings = Settings(database_url=f"sqlite:///{(tmp_path / 'small.db').as_posix()}", max_upload_bytes=100)
    with TestClient(create_app(settings)) as small_client:
        response = small_client.post("/api/files/", files={"file": ("survey.kml", SURVEY_KML)})

    assert response.status_code == 413


def test_broken_archive_is_recorded_as_failed(client, upload):
    response = upload("parcels.zip", b"not really a zip")
    file_id = response.json()["file_id"]

    assert response.status_code == 422
    assert client.get(f"/api/files/{file_id}/").json()["status"] == "FAILED"
    assert "not a valid zip" in client.get(f"/api/files/{file_id}/").json()["error"]
    assert client.get(f"/api/files/{file_id}/measurements/").status_code == 409


def test_unknown_file_id_is_404(client):
    assert client.get("/api/files/does-not-exist/").status_code == 404
    assert client.get("/api/files/does-not-exist/measurements/").status_code == 404
