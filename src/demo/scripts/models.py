"""The single source of truth for which models need a real DynamoDB table -- both the
dev migrator (``dev_migrate.py``) and the ACK manifest generator (``gen_ack_tables.py``)
import ``MODELS`` from here, so adding a model here gets it picked up by both.

This is dev tooling (``scripts/``) and imports the model classes from ``app/`` -- never
the reverse.
"""

from pynamodb.models import Model

from demo.app.models import Question, Session

MODELS: list[type[Model]] = [Question, Session]
