"""HTTP routes, plus the single place where domain errors become HTTP responses."""

from collections.abc import Iterator
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.errors import (
    EmptyUpload,
    FileNotFound,
    FileTooLarge,
    GeoFileError,
    InvalidCrs,
    MeasurementsUnavailable,
    ProcessingFailed,
    UnsupportedFileType,
)
from app.repository import GeoFileRepository
from app.schemas import FileInfo, MeasurementsResponse
from app.service import FileProcessingService

DEFAULT_PAGE_SIZE = 500
MAX_PAGE_SIZE = 5000

router = APIRouter(prefix="/api/files", tags=["files"])


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


def get_service(request: Request, session: Annotated[Session, Depends(get_session)]) -> FileProcessingService:
    return FileProcessingService(GeoFileRepository(session), request.app.state.settings)


Service = Annotated[FileProcessingService, Depends(get_service)]


@router.post("/", status_code=HTTPStatus.CREATED, summary="Upload and process a KML or zipped Shapefile")
def upload_file(
    file: Annotated[UploadFile, File(description="A .kml file, or a .zip containing one Shapefile.")],
    service: Service,
    response: Response,
    source_crs: Annotated[
        str | None,
        Form(description="CRS to assume if the file declares none (e.g. a shapefile without .prj), e.g. EPSG:32643."),
    ] = None,
) -> FileInfo:
    record = service.process_upload(file.filename or "", file.file, source_crs)
    response.headers["Location"] = f"{router.prefix}/{record.id}/"
    return FileInfo.model_validate(record)


@router.get("/{file_id}/", summary="Information about an uploaded file")
def get_file(file_id: str, service: Service) -> FileInfo:
    return FileInfo.model_validate(service.get_file(file_id))


@router.get("/{file_id}/measurements/", summary="Per-feature measurements in metres")
def get_measurements(
    file_id: str,
    service: Service,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> MeasurementsResponse:
    return MeasurementsResponse.from_page(service.get_measurements(file_id, offset, limit), offset, limit)


ERROR_STATUS: dict[type[GeoFileError], HTTPStatus] = {
    UnsupportedFileType: HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
    FileTooLarge: HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
    EmptyUpload: HTTPStatus.BAD_REQUEST,
    InvalidCrs: HTTPStatus.UNPROCESSABLE_ENTITY,
    ProcessingFailed: HTTPStatus.UNPROCESSABLE_ENTITY,
    FileNotFound: HTTPStatus.NOT_FOUND,
    MeasurementsUnavailable: HTTPStatus.CONFLICT,
}


def problem_response(request: Request, exc: GeoFileError) -> JSONResponse:
    """Render a domain error as RFC 9457 Problem Details (``application/problem+json``)."""
    status = _status_for(exc)
    body = {
        "type": "about:blank",
        "title": status.phrase,
        "status": status.value,
        "detail": str(exc),
        "instance": request.url.path,
        **exc.extensions(),
    }
    return JSONResponse(body, status_code=status.value, media_type="application/problem+json")


def _status_for(exc: GeoFileError) -> HTTPStatus:
    """The status of the closest mapped class in the exception's hierarchy."""
    for cls in type(exc).__mro__:
        if cls in ERROR_STATUS:
            return ERROR_STATUS[cls]
    return HTTPStatus.BAD_REQUEST
