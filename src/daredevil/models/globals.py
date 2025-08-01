import datetime as dt
from datetime import datetime
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel, text


class IdntfyModel(SQLModel):
    id: UUID = Field(
        default_factory=uuid4,
        index=True,
        nullable=False,
        primary_key=True,
    )


class TmStmpModel(SQLModel):
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(dt.timezone.utc),
        nullable=False,
        sa_column_kwargs={"server_default": text("current_timestamp")},
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(dt.timezone.utc),
        nullable=False,
        sa_column_kwargs={"server_default": text("current_timestamp")},
    )
