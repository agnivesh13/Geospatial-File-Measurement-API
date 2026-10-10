"""Facade over reading, measuring and storing files. The API layer talks only to this class."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import BinaryIO

from app.config import Settings
from app.domain import FileStatus, MeasuredFeature, ParsedDataset
from app.errors import (
    EmptyUpload,
    FileTooLarge,
    InvalidGeoFile,
    MeasurementsUnavailable,
    ProcessingFailed,
)
from app.geo.crs import parse_crs
from app.geo.measurement import measure_feature
from app.geo.readers import reader_for
from app.models import Feature, GeoFile
from app.repository import GeoFileRepository, MeasurementSummary

CHUNK_SIZE = 1024 * 1024
MAX_FILENAME_LENGTH = 255
UNEXPECTED_ERROR = "Unexpected error while processing the file."


@dataclass(frozen=True)
class MeasurementsPage:
    file: GeoFile
    summary: MeasurementSummary
    features: list[Feature]


class FileProcessingService:
    def __init__(self, repository: GeoFileRepository, settings: Settings) -> None:
        self._repository = repository
        self._settings = settings

    def process_upload(self, filename: str, content: BinaryIO, source_crs: str | None = None) -> GeoFile:
        """Validate, read, measure and store an upload. Processing is synchronous; see README."""
        reader = reader_for(filename, self._settings)
        fallback_crs = parse_crs(source_crs)
        with TemporaryDirectory(prefix="geo-upload-") as folder:
            # A server-generated name: the client's filename never touches the file system.
            path = self._save_upload(content, Path(folder) / f"upload{Path(filename).suffix.lower()}")
            record = self._repository.start(_display_name(filename))
            with self._failure_recorded(record):
                dataset = reader.read(path, fallback_crs)
                self._repository.complete(record, dataset.crs, _measure_all(dataset))
        return record

    def get_file(self, file_id: str) -> GeoFile:
        return self._repository.get(file_id)

    def get_measurements(self, file_id: str, offset: int, limit: int) -> MeasurementsPage:
        record = self._repository.get(file_id)
        if record.status is not FileStatus.COMPLETED:
            raise MeasurementsUnavailable(
                f"File {file_id!r} is {record.status}. Measurements exist only for COMPLETED files."
            )
        summary = self._repository.summary(file_id)
        return MeasurementsPage(record, summary, self._repository.features_page(file_id, offset, limit))

    def _save_upload(self, content: BinaryIO, target: Path) -> Path:
        written = 0
        with target.open("wb") as out:
            while chunk := content.read(CHUNK_SIZE):
                written += len(chunk)
                if written > self._settings.max_upload_bytes:
                    raise FileTooLarge(f"The upload exceeds the {self._settings.max_upload_bytes}-byte limit.")
                out.write(chunk)
        if written == 0:
            raise EmptyUpload("The uploaded file is empty.")
        return target

    @contextmanager
    def _failure_recorded(self, record: GeoFile) -> Iterator[None]:
        """Marks the record FAILED if anything inside the block raises, then re-raises."""
        try:
            yield
        except InvalidGeoFile as exc:
            self._repository.fail(record, str(exc))
            raise ProcessingFailed(record.id, str(exc)) from exc
        except Exception:
            self._repository.fail(record, UNEXPECTED_ERROR)
            raise


def _measure_all(dataset: ParsedDataset) -> list[MeasuredFeature]:
    return [MeasuredFeature(feature, measure_feature(feature)) for feature in dataset.features]


def _display_name(filename: str) -> str:
    """Keep only the base name; some browsers send a full client path."""
    return filename.replace("\\", "/").rsplit("/", 1)[-1][:MAX_FILENAME_LENGTH]
