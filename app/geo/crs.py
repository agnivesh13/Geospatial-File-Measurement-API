"""Coordinate Reference System helpers."""

from pyproj import CRS
from pyproj.exceptions import CRSError

from app.errors import InvalidCrs

# KML and GeoJSON (RFC 7946) both use WGS 84 longitude/latitude.
WGS84 = CRS.from_epsg(4326)


def crs_label(crs: CRS) -> str:
    """A short, human-readable identifier such as ``EPSG:4326``, falling back to the CRS name."""
    authority = crs.to_authority()
    return ":".join(authority) if authority else crs.name


def parse_crs(text: str | None) -> CRS | None:
    """Parse a user-supplied CRS such as ``EPSG:32643``. Returns None when nothing was supplied."""
    if not text:
        return None
    try:
        return CRS.from_user_input(text)
    except CRSError as exc:
        raise InvalidCrs(f"{text!r} is not a CRS that PROJ recognises (try a code like 'EPSG:4326').") from exc
