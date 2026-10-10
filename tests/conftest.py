from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}")


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def upload(client: TestClient) -> Callable[..., Any]:
    """POST a file to the upload endpoint: ``upload("a.kml", content, source_crs="EPSG:4326")``."""

    def _upload(filename: str, content: bytes, **form: str) -> Any:
        return client.post("/api/files/", files={"file": (filename, content)}, data=form)

    return _upload


@pytest.fixture
def measurements(client: TestClient) -> Callable[..., dict[str, Any]]:
    def _measurements(file_id: str, **params: int) -> dict[str, Any]:
        response = client.get(f"/api/files/{file_id}/measurements/", params=params)
        assert response.status_code == 200, response.text
        return response.json()

    return _measurements
