"""PynamoDB models -- the single source of truth for both dev-time table migration
(``dev_migrate.py``) and ACK manifest generation (``gen_ack_tables.py``).

Add a model to ``MODELS`` and it is picked up by both: the local ``dynamodb-local``
table *and* the deployed AWS table (via the generated ACK ``Table`` manifest) are
derived from the same class, so they can't drift apart.
"""

from datetime import UTC, datetime

from pynamodb.attributes import NumberAttribute, TTLAttribute, UnicodeAttribute
from pynamodb.indexes import AllProjection, GlobalSecondaryIndex
from pynamodb.models import Model

# Prefixing AWS-side table names keeps them unique across stacks/envs that share one
# AWS account. It's stripped back off when deriving the (already namespaced) k8s
# object name -- see ``gen_ack_tables._k8s_resource_name``.
TABLES_PREFIX = "demo-"


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


MODELS: list[type[Model]] = [Question, Session]
