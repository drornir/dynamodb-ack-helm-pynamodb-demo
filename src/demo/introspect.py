"""PynamoDB model reflection shared by the tooling (dev migration, ACK manifest
generation). Everything the generator and migrator need about a table -- its keys,
its indexes, its TTL attribute -- is read off the pynamodb ``Model`` class here, so
there is exactly one place that knows how to interrogate a model.
"""

from typing import Any, Literal

from pynamodb.attributes import Attribute, TTLAttribute
from pynamodb.indexes import Index
from pynamodb.models import Model

type KeyType = Literal["HASH", "RANGE"]


def key_schema(cls: type) -> list[tuple[str, KeyType, str]]:
    """``(attr_name, key_type, attr_type)`` for the HASH/RANGE keys declared directly
    on a Model or Index class, HASH first. ``attr_type`` is pynamodb's own "S"/"N"/"B"
    code, which is also DynamoDB's own AttributeType code.
    """
    keys: list[tuple[str, KeyType, str]] = []
    for name in dir(cls):
        attr = getattr(cls, name, None)
        if isinstance(attr, Attribute) and (attr.is_hash_key or attr.is_range_key):
            keys.append((attr.attr_name, "HASH" if attr.is_hash_key else "RANGE", attr.attr_type))
    keys.sort(key=lambda k: 0 if k[1] == "HASH" else 1)  # HASH before RANGE
    return keys


def declared_indexes(model: type[Model]) -> list[Index[Any]]:
    """Every GlobalSecondaryIndex/LocalSecondaryIndex instance declared on a Model."""
    return [a for n in dir(model) if isinstance(a := getattr(model, n, None), Index)]


def ttl_attribute_name(model: type[Model]) -> str | None:
    """The table's TTLAttribute attr_name, if it declares one (pynamodb enforces at
    most one per Model at class-definition time).
    """
    for name in dir(model):
        attr = getattr(model, name, None)
        if isinstance(attr, TTLAttribute):
            return attr.attr_name
    return None
