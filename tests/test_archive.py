import zipfile

import pytest

from app.errors import InvalidArchive
from app.geo.archive import _reject_zip_bomb, find_shapefile
from tests.sample_data import frame, shapefile_zip, square

LIMIT = 10 * 1024 * 1024


@pytest.fixture
def polygons():
    return frame([square()])


def test_finds_the_shapefile_inside_a_folder(tmp_path, polygons):
    archive = shapefile_zip(tmp_path / "a.zip", polygons, folder="survey/")

    assert find_shapefile(archive, LIMIT) == "survey/layer.shp"


def test_ignores_macos_metadata_files(tmp_path, polygons):
    junk = {"__MACOSX/._layer.shp": b"resource fork", "._layer.shp": b"resource fork"}
    archive = shapefile_zip(tmp_path / "a.zip", polygons, extra_members=junk)

    assert find_shapefile(archive, LIMIT) == "layer.shp"


def test_rejects_files_that_are_not_zips(tmp_path):
    fake = tmp_path / "a.zip"
    fake.write_bytes(b"definitely not a zip")

    with pytest.raises(InvalidArchive, match="not a valid zip"):
        find_shapefile(fake, LIMIT)


def test_rejects_zip_without_a_shapefile(tmp_path):
    archive = tmp_path / "a.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("readme.txt", "hello")

    with pytest.raises(InvalidArchive, match="no .shp"):
        find_shapefile(archive, LIMIT)


def test_rejects_more_than_one_shapefile(tmp_path, polygons):
    archive = shapefile_zip(tmp_path / "a.zip", polygons, extra_members={"other.shp": b"x"})

    with pytest.raises(InvalidArchive, match="exactly one"):
        find_shapefile(archive, LIMIT)


@pytest.mark.parametrize("missing", [".shx", ".dbf"])
def test_rejects_incomplete_shapefiles(tmp_path, polygons, missing):
    archive = shapefile_zip(tmp_path / "a.zip", polygons, skip_suffixes=(missing,))

    with pytest.raises(InvalidArchive, match=f"missing \\{missing}"):
        find_shapefile(archive, LIMIT)


def test_rejects_archives_that_expand_beyond_the_limit(tmp_path, polygons):
    archive = shapefile_zip(tmp_path / "a.zip", polygons, extra_members={"padding.bin": bytes(100_000)})

    with pytest.raises(InvalidArchive, match="limit"):
        find_shapefile(archive, max_uncompressed_bytes=50_000)


def test_rejects_entry_names_that_escape_the_archive(tmp_path, polygons):
    archive = shapefile_zip(tmp_path / "a.zip", polygons, extra_members={"../../evil.txt": b"x"})

    with pytest.raises(InvalidArchive, match="Unsafe path"):
        find_shapefile(archive, LIMIT)


def entry(name: str, file_size: int, compress_size: int, header_offset: int) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name)
    info.file_size, info.compress_size, info.header_offset = file_size, compress_size, header_offset
    return info


def test_rejects_compression_ratios_deflate_cannot_produce():
    forged = [entry("layer.shp", file_size=2_000_000, compress_size=1_000, header_offset=0)]

    with pytest.raises(InvalidArchive, match="compression ratio"):
        _reject_zip_bomb(forged, LIMIT)


def test_rejects_overlapping_entries():
    overlapping = [entry("a.shp", 10, 10, header_offset=0), entry("b.shp", 10, 10, header_offset=0)]

    with pytest.raises(InvalidArchive, match="overlapping"):
        _reject_zip_bomb(overlapping, LIMIT)
