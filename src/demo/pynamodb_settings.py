"""PynamoDB global settings module (pointed at by the ``PYNAMODB_CONFIG`` env var).

pynamodb reads config from a *Python module* -- not one env var per setting -- whose
path is given by ``PYNAMODB_CONFIG``. It imports this module exactly once, at
``pynamodb.settings`` import time, and memoizes the values; see ``dev_migrate.py`` for
why the env var has to be set before any pynamodb-touching import.

Only override ``host`` in dev, so the same models talk to ``dynamodb-local`` locally
and to real AWS in production (where ``host`` stays ``None`` and pynamodb uses the
regional endpoint).
"""

import os

if os.environ.get("APP_ENV") == "dev":
    host = os.environ.get("DYNAMODB_HOST", "http://localhost:5555")
    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
else:
    host = None
