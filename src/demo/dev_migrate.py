"""Create/update the ``MODELS`` tables against a local ``dynamodb-local`` (never real
AWS -- production tables are provisioned by ACK from the generated manifest instead).

Run it: start ``dynamodb-local`` (``docker compose up -d``), then ``dev-migrate``.

IMPORT-ORDER GOTCHA (the whole reason this file is shaped the way it is):
``pynamodb.settings`` reads ``PYNAMODB_CONFIG`` *once*, at its own import time, and a
``Model``'s ``Meta.host``/``region``/creds are frozen from it at class-definition
time. Any ``from demo.models import ...`` transitively imports ``pynamodb.models`` ->
``pynamodb.settings``. So the env vars MUST be set before that import -- which is why
``_setup_dev_env()`` runs at the very top of ``if __name__``/``main`` and the models
are imported lazily *inside* ``main()``, below it. Set them too late and pynamodb's
own connection silently targets real AWS, which rejects the fake creds with
``UnrecognizedClientException`` -- easy to misread as an expired SSO session when the
real cause is "never pointed at localhost at all".
"""

import os


def _setup_dev_env() -> None:
    os.environ["APP_ENV"] = "dev"
    os.environ["PYNAMODB_CONFIG"] = os.path.join(os.path.dirname(__file__), "pynamodb_settings.py")
    # Force fake creds so pynamodb's own connection can't fall through to a real (or
    # expired) SSO session. A leftover AWS_SESSION_TOKEN paired with a fake key also
    # trips dynamodb-local's UnrecognizedClientException, so clear it (and AWS_PROFILE).
    os.environ["AWS_ACCESS_KEY_ID"] = "FAKE"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "FAKE"
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
    _ = os.environ.pop("AWS_SESSION_TOKEN", None)
    _ = os.environ.pop("AWS_PROFILE", None)


def main() -> None:
    _setup_dev_env()

    # Imported here, AFTER _setup_dev_env() -- see the module docstring.
    from pynamodb.constants import PAY_PER_REQUEST_BILLING_MODE

    from demo.models import MODELS

    for model in MODELS:
        if model.exists():
            print(f"exists   {model.Meta.table_name}")
            continue
        model.create_table(billing_mode=PAY_PER_REQUEST_BILLING_MODE, wait=True)
        print(f"created  {model.Meta.table_name}")


if __name__ == "__main__":
    main()
