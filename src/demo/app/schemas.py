"""A thin pydantic response layer over the pynamodb models. Two pieces worth copying:

- ``PydanticModel`` validates *directly* from a pynamodb ``Model`` instance -- its wrap
  validator calls ``.to_simple_dict()`` when handed a Model, so you can write
  ``QuestionResponse.model_validate(question)`` with no intermediate dict.
- ``Timestamp`` converts the numeric epoch values DynamoDB stores (this repo keeps
  ``created_at`` as a Number) into timezone-aware ``datetime`` on the way out.
"""

from datetime import UTC, datetime
from typing import Annotated, Any, Self

from pydantic import BaseModel, BeforeValidator, ModelWrapValidatorHandler, model_validator
from pynamodb.models import Model


def ts_to_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=UTC)
    raise ValueError(f"Invalid timestamp type {type(value)=}: {value=}")


type Timestamp = Annotated[datetime, BeforeValidator(ts_to_dt)]


class PydanticModel(BaseModel):
    @model_validator(mode="wrap")
    @classmethod
    def _from_db_model(cls, data: Any, handler: ModelWrapValidatorHandler[Self]) -> Any:
        if isinstance(data, Model):
            data = data.to_simple_dict()
        return handler(data)


class QuestionResponse(PydanticModel):
    id: str
    created_at: Timestamp
    creator_name: str
    question: str
    answer: str | None = None


class QuestionListResponse(PydanticModel):
    items: list[QuestionResponse]
    next_cursor: str | None = None
