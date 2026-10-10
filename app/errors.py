"""Domain errors.

Code raises these instead of returning error codes. The API layer translates each class into an
HTTP status in exactly one place (``app/api.py``), so no domain code knows about HTTP.
"""


class GeoFileError(Exception):
    """Base class for every error this service raises on purpose."""

    def extensions(self) -> dict[str, str]:
        """Extra machine-readable fields for the error response (RFC 9457 extension members)."""
        return {}


class UploadRejected(GeoFileError):
    """The upload itself is unacceptable, so nothing is stored."""


class UnsupportedFileType(UploadRejected):
    pass


class FileTooLarge(UploadRejected):
    pass


class EmptyUpload(UploadRejected):
    pass


class InvalidCrs(UploadRejected):
    pass


class InvalidGeoFile(GeoFileError):
    """The upload was accepted, but its content cannot be processed."""


class InvalidArchive(InvalidGeoFile):
    pass


class UnreadableGeoFile(InvalidGeoFile):
    pass


class UnsupportedCrs(InvalidGeoFile):
    pass


class ProcessingFailed(GeoFileError):
    """Processing failed after a file record was created, so the record id is reported."""

    def __init__(self, file_id: str, reason: str) -> None:
        super().__init__(reason)
        self.file_id = file_id

    def extensions(self) -> dict[str, str]:
        return {"file_id": self.file_id}


class FileNotFound(GeoFileError):
    pass


class MeasurementsUnavailable(GeoFileError):
    pass
