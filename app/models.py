"""Database tables (SQLAlchemy 2.0 ORM)."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Enum, Float, ForeignKey, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, composite, mapped_column, relationship

from app.domain import FileStatus, Measurement, MeasurementKind, MeasurementStatus


class Base(DeclarativeBase):
    pass


class GeoFile(Base):
    __tablename__ = "geo_files"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    filename: Mapped[str] = mapped_column(String(255))
    status: Mapped[FileStatus] = mapped_column(Enum(FileStatus, native_enum=False))
    crs: Mapped[str | None] = mapped_column(String(255))
    feature_count: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    features: Mapped[list["Feature"]] = relationship(
        back_populates="file", cascade="all, delete-orphan", order_by="Feature.feature_index"
    )


class Feature(Base):
    __tablename__ = "features"

    id: Mapped[int] = mapped_column(primary_key=True)
    file_id: Mapped[str] = mapped_column(ForeignKey("geo_files.id"), index=True)
    feature_index: Mapped[int]
    layer: Mapped[str] = mapped_column(String(255))
    geometry_type: Mapped[str | None] = mapped_column(String(32))
    source_crs: Mapped[str | None] = mapped_column(String(255))
    geometry: Mapped[dict[str, Any] | None] = mapped_column(JSON)  # GeoJSON, WGS 84
    properties: Mapped[dict[str, Any]] = mapped_column(JSON)

    measurement_status: Mapped[MeasurementStatus] = mapped_column(Enum(MeasurementStatus, native_enum=False))
    measurement_kind: Mapped[MeasurementKind | None] = mapped_column(Enum(MeasurementKind, native_enum=False))
    measurement_value: Mapped[float | None] = mapped_column(Float)
    measurement_unit: Mapped[str | None] = mapped_column(String(8))
    measurement_projection: Mapped[str | None] = mapped_column(String(255))
    measurement_note: Mapped[str | None] = mapped_column(Text)
    # The six columns above load and save as one Measurement value object.
    measurement: Mapped[Measurement] = composite(
        "measurement_status",
        "measurement_kind",
        "measurement_value",
        "measurement_unit",
        "measurement_projection",
        "measurement_note",
    )

    file: Mapped[GeoFile] = relationship(back_populates="features")
