"""The pynamodb Model classes -- runtime code (``app/``). The list of which models
need a real table lives in ``scripts/models.py`` (dev tooling), which imports these.
Runtime code never imports from ``scripts/``; only the other direction.
"""

from datetime import UTC, datetime

from pynamodb.attributes import NumberAttribute, TTLAttribute, UnicodeAttribute
from pynamodb.indexes import AllProjection, GlobalSecondaryIndex
from pynamodb.models import Model

from demo.app.consts import TABLES_PREFIX


class QuestionsByCreatedAt(GlobalSecondaryIndex["Question"]):
    """List-the-whole-table GSI: a constant partition key (`list_gsi_pk = 0`) with a
    time range key, so a single ``query`` returns every item newest-first.
    """

    class Meta:
        index_name = f"{TABLES_PREFIX}Questions-ByCreatedAt"
        projection = AllProjection()

    list_gsi_pk = NumberAttribute(hash_key=True, default=0)
    created_at = NumberAttribute(range_key=True)


class Question(Model):
    class Meta:  # pyright: ignore[reportIncompatibleVariableOverride]
        table_name = f"{TABLES_PREFIX}Questions"

    id = UnicodeAttribute(hash_key=True)
    created_at = NumberAttribute(
        range_key=True, default_for_new=lambda: datetime.now(UTC).timestamp()
    )
    creator_name = UnicodeAttribute()
    question = UnicodeAttribute()
    answer = UnicodeAttribute(null=True)

    # Constant value; only exists to give ``QuestionsByCreatedAt`` a partition key.
    list_gsi_pk = NumberAttribute(default=0)

    by_created_at = QuestionsByCreatedAt()


class Session(Model):
    """A second, simpler model -- shows the generator emitting ``timeToLive`` from a
    ``TTLAttribute`` and a table with just a hash key (no range key, no GSI).
    """

    class Meta:  # pyright: ignore[reportIncompatibleVariableOverride]
        table_name = f"{TABLES_PREFIX}Sessions"

    id = UnicodeAttribute(hash_key=True)
    expires_at = TTLAttribute()
