"""Adapters from GDAL (read through pyogrio) to our domain types, plus a factory that picks one.

Library types (GeoDataFrames, pyproj CRS objects) stay inside this module. What leaves it is a plain
``ParsedDataset``, with every geometry already reprojected to WGS 84 when its CRS is known.
"""

import datetime as dt
import logging
import math
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

import numpy as np
import pandas as pd
import pyogrio
from geopandas import GeoDataFrame
from pyogrio.errors import DataLayerError, DataSourceError
from pyproj import CRS
from pyproj.exceptions import ProjError

from app.config import Settings
from app.domain import ParsedDataset, ParsedFeature
from app.errors import UnreadableGeoFile, UnsupportedCrs, UnsupportedFileType
from app.geo.archive import find_shapefile
from app.geo.crs import WGS84, crs_label

logger = logging.getLogger(__name__)

# Styling fields GDAL's LIBKML driver adds to every KML layer. They describe looks, not data.
KML_STYLE_FIELDS = ["tessellate", "extrude", "visibility", "drawOrder", "icon"]


class GeoReader(Protocol):
    def read(self, path: Path, fallback_crs: CRS | None = None) -> ParsedDataset: ...


class KmlReader:
    """Reads every layer. Each KML <Folder> is its own GDAL layer, and GDAL reads only the first
    one unless asked, which would silently drop features."""

    def read(self, path: Path, fallback_crs: CRS | None = None) -> ParsedDataset:
        source = str(path)
        layers = [
            (name, _read_layer(source, name).drop(columns=KML_STYLE_FIELDS, errors="ignore"))
            for name in _layer_names(source)
        ]
        return _to_dataset(layers, fallback_crs)


class ShapefileZipReader:
    """Reads the single shapefile inside a zip, straight from the archive without extracting it."""

    def __init__(self, max_uncompressed_bytes: int) -> None:
        self._max_uncompressed_bytes = max_uncompressed_bytes

    def read(self, path: Path, fallback_crs: CRS | None = None) -> ParsedDataset:
        member = find_shapefile(path, self._max_uncompressed_bytes)
        source = f"/vsizip/{path.resolve().as_posix()}/{member}"
        return _to_dataset([(PurePosixPath(member).stem, _read_layer(source))], fallback_crs)


READER_FACTORIES: dict[str, Callable[[Settings], GeoReader]] = {
    ".kml": lambda settings: KmlReader(),
    ".zip": lambda settings: ShapefileZipReader(settings.max_uncompressed_bytes),
}


def reader_for(filename: str, settings: Settings) -> GeoReader:
    suffix = Path(filename).suffix.lower()
    if suffix not in READER_FACTORIES:
        raise UnsupportedFileType(
            f"Unsupported file type {suffix or '(none)'!r}. "
            "Upload a .kml file or a .zip containing a Shapefile."
        )
    return READER_FACTORIES[suffix](settings)


def _layer_names(source: str) -> list[str]:
    try:
        return [str(name) for name, _geometry_type in pyogrio.list_layers(source)]
    except DataSourceError as exc:
        raise _unreadable(exc) from exc


def _read_layer(source: str, layer: str | None = None) -> GeoDataFrame:
    try:
        return pyogrio.read_dataframe(source, layer=layer)
    except (DataSourceError, DataLayerError) as exc:
        raise _unreadable(exc) from exc


def _unreadable(exc: Exception) -> UnreadableGeoFile:
    # GDAL messages include server-side temp paths, so log them instead of returning them.
    logger.warning("GDAL could not read an upload: %s", exc)
    return UnreadableGeoFile("The file could not be read. It may be corrupt or not match its extension.")


def _to_dataset(layers: list[tuple[str, GeoDataFrame]], fallback_crs: CRS | None) -> ParsedDataset:
    features: list[ParsedFeature] = []
    labels: set[str | None] = set()
    for name, frame in layers:
        frame, label = _to_wgs84(frame, fallback_crs)
        labels.add(label)
        features.extend(_features(name, frame, label, first_index=len(features)))
    return ParsedDataset(crs=labels.pop() if len(labels) == 1 else None, features=features)


def _to_wgs84(frame: GeoDataFrame, fallback_crs: CRS | None) -> tuple[GeoDataFrame, str | None]:
    """Reproject to WGS 84 and label the source CRS. Unknown CRS: unchanged frame and None."""
    crs = frame.crs if frame.crs is not None else fallback_crs
    if crs is None:
        return frame, None
    try:
        return frame.set_crs(crs, allow_override=True).to_crs(WGS84), crs_label(crs)
    except ProjError as exc:  # e.g. a local engineering grid with no link to the Earth
        raise UnsupportedCrs(
            f"The file's CRS ({crs_label(crs)}) cannot be converted to WGS 84, so it cannot be measured."
        ) from exc


def _features(layer: str, frame: GeoDataFrame, source_crs: str | None, first_index: int) -> list[ParsedFeature]:
    rows = frame.drop(columns=frame.geometry.name).to_dict("records")
    return [
        ParsedFeature(first_index + offset, layer, geometry, _clean(row), source_crs)
        for offset, (geometry, row) in enumerate(zip(frame.geometry, rows, strict=True))
    ]


def _clean(row: dict[str, Any]) -> dict[str, Any]:
    """Drop empty attributes and convert the rest into JSON-friendly Python values."""
    values = {str(key): _json_value(value) for key, value in row.items()}
    return {key: value for key, value in values.items() if value is not None}


def _json_value(value: Any) -> Any:
    if isinstance(value, (list, tuple, np.ndarray)):
        return [_json_value(item) for item in value]
    if pd.isna(value):
        return None
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    return value
