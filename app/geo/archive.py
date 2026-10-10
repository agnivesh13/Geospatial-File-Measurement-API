"""Safe inspection of an uploaded zip that should contain one Shapefile.

Nothing is ever extracted to disk. GDAL reads the shapefile straight out of the zip (``/vsizip/``),
so a malicious entry name cannot write files ("zip slip"). We still refuse archives that look like
zip bombs, following Fifield (2019, "A better zip bomb"):
- DEFLATE cannot exceed a 1032:1 compression ratio, so a larger declared ratio is forged.
- Several entries pointing at the same data (overlapping files) is the signature of his bomb.
The paper also warns that a pre-check outside the real parser is not a complete defence, so the
total uncompressed size is capped as well.
"""

import zipfile
from pathlib import Path, PurePosixPath

from app.errors import InvalidArchive

DEFLATE_MAX_COMPRESSION_RATIO = 1032
# ESRI Shapefile Technical Description (1998): "a main file, an index file, and a dBASE table".
REQUIRED_COMPANION_SUFFIXES = (".shx", ".dbf")
MACOS_METADATA_FOLDER = "__MACOSX"


def find_shapefile(zip_path: Path, max_uncompressed_bytes: int) -> str:
    """Validate the archive and return the member name of its single ``.shp`` file."""
    entries = _read_entries(zip_path)
    _reject_zip_bomb(entries, max_uncompressed_bytes)
    _reject_unsafe_names(entries)
    members = [entry.filename for entry in entries if not _is_metadata(entry)]
    shapefile = _single_shapefile(members)
    _require_companion_files(shapefile, members)
    return shapefile


def _read_entries(zip_path: Path) -> list[zipfile.ZipInfo]:
    try:
        with zipfile.ZipFile(zip_path) as archive:
            return archive.infolist()
    except zipfile.BadZipFile as exc:
        raise InvalidArchive("The upload is not a valid zip archive.") from exc


def _reject_zip_bomb(entries: list[zipfile.ZipInfo], max_uncompressed_bytes: int) -> None:
    total = sum(entry.file_size for entry in entries)
    if total > max_uncompressed_bytes:
        raise InvalidArchive(
            f"The archive expands to {total} bytes, above the {max_uncompressed_bytes}-byte limit."
        )
    if any(entry.file_size > entry.compress_size * DEFLATE_MAX_COMPRESSION_RATIO for entry in entries):
        raise InvalidArchive("The archive declares a compression ratio DEFLATE cannot produce.")
    offsets = [entry.header_offset for entry in entries]
    if len(set(offsets)) != len(offsets):
        raise InvalidArchive("The archive contains overlapping entries.")


def _reject_unsafe_names(entries: list[zipfile.ZipInfo]) -> None:
    for entry in entries:
        path = PurePosixPath(entry.filename.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts or ":" in entry.filename:
            raise InvalidArchive(f"Unsafe path inside the archive: {entry.filename!r}.")


def _is_metadata(entry: zipfile.ZipInfo) -> bool:
    """Directories and the resource-fork files macOS Finder adds when it zips a folder."""
    path = PurePosixPath(entry.filename)
    return entry.is_dir() or MACOS_METADATA_FOLDER in path.parts or path.name.startswith("._")


def _single_shapefile(members: list[str]) -> str:
    shapefiles = [name for name in members if name.lower().endswith(".shp")]
    if not shapefiles:
        raise InvalidArchive("The zip contains no .shp file.")
    if len(shapefiles) > 1:
        raise InvalidArchive(f"Expected exactly one .shp file, found {len(shapefiles)}: {shapefiles}.")
    return shapefiles[0]


def _require_companion_files(shapefile: str, members: list[str]) -> None:
    stem = shapefile[: -len(".shp")].lower()
    present = {name.lower() for name in members}
    missing = [suffix for suffix in REQUIRED_COMPANION_SUFFIXES if stem + suffix not in present]
    if missing:
        raise InvalidArchive(
            f"The shapefile is incomplete: missing {', '.join(missing)}. "
            "A shapefile needs .shp, .shx and .dbf files with the same name."
        )
