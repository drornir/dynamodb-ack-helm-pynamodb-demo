"""Generate ACK (AWS Controllers for Kubernetes) ``dynamodb.services.k8s.aws/v1alpha1``
``Table`` manifests from the pynamodb models in ``demo.models.MODELS``.

Writes a single top-level JSON array to the path given as the first argument, or to
stdout if it's omitted or "-". JSON (a subset of YAML) is read by Helm's
``fromJsonArray`` and sidesteps YAML's bool-token ambiguity, where a bare
``attributeType: N`` round-trips fine through PyYAML but silently becomes ``false`` in
Helm's Go YAML parser (Go's YAML 1.1 resolver treats bare ``y/Y/n/N/yes/no`` as
booleans; PyYAML's does not). The file is read by
``chart/templates/dynamodb-tables.yaml`` at render time and merged with per-table
overrides from ``values.yaml``, so it belongs under ``chart/files/`` (outside
``templates/``, which Helm excludes from ``.Files.Get``), not applied directly with
``kubectl``. Pass ``@chart`` as a shorthand for that canonical path:

  gen-ack-tables @chart

Reference CRD shape:
https://github.com/aws-controllers-k8s/dynamodb-controller/blob/main/test/e2e/resources/table_global_secondary_indexes.yaml
"""

import argparse
import json
import sys
from pathlib import Path

from pynamodb.constants import PAY_PER_REQUEST_BILLING_MODE, PROVISIONED_BILLING_MODE
from pynamodb.indexes import Index, LocalSecondaryIndex
from pynamodb.models import Model

from demo.introspect import declared_indexes, key_schema, ttl_attribute_name
from demo.models import MODELS, TABLES_PREFIX

# src/demo/gen_ack_tables.py -> src/demo -> src -> repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_CHART_TABLES_FILE = _REPO_ROOT / "chart" / "files" / "dynamodb-tables.json"

# DNS subdomain name limit (RFC 1123) that k8s object names must fit.
_K8S_NAME_MAX_LEN = 253


def _k8s_resource_name(table_name: str) -> str:
    """A DNS subdomain-compliant k8s object name (RFC 1123) for a Table's ACK
    resource -- lowercase (DynamoDB table names allow uppercase; k8s object names
    don't) and without ``TABLES_PREFIX`` (once the resource is namespaced by k8s, the
    account-uniqueness prefix is redundant). Trimmed to the 253-char subdomain limit,
    dropping any trailing "-"/"." the trim would otherwise leave (a k8s object name
    must end alphanumeric).
    """
    name = table_name.removeprefix(TABLES_PREFIX).lower()
    return name[:_K8S_NAME_MAX_LEN].rstrip("-.")


def _projection(index_cls: type[Index[Model]]) -> dict[str, object]:
    proj = index_cls.Meta.projection
    out: dict[str, object] = {"projectionType": proj.projection_type}
    non_key_attrs = getattr(proj, "non_key_attributes", None)
    if proj.projection_type == "INCLUDE" and non_key_attrs:
        out["nonKeyAttributes"] = list(non_key_attrs)
    return out


def _billing_fields(model: type[Model]) -> dict[str, object]:
    """billingMode (+ provisionedThroughput, if PROVISIONED) from Meta.billing_mode --
    the same attribute pynamodb's own ``create_table()`` reads, if a model bothers to
    set it. Defaults to PAY_PER_REQUEST (rather than pynamodb's own PROVISIONED
    default), matching how the dev migrator creates tables.
    """
    billing_mode = getattr(model.Meta, "billing_mode", PAY_PER_REQUEST_BILLING_MODE)

    fields: dict[str, object] = {"billingMode": billing_mode}
    if billing_mode == PROVISIONED_BILLING_MODE:
        read_units = getattr(model.Meta, "read_capacity_units", None)
        write_units = getattr(model.Meta, "write_capacity_units", None)
        if read_units is None or write_units is None:
            raise ValueError(
                f"{model.__name__}.Meta is PROVISIONED but missing "
                "read_capacity_units/write_capacity_units"
            )
        fields["provisionedThroughput"] = {
            "readCapacityUnits": read_units,
            "writeCapacityUnits": write_units,
        }
    elif billing_mode != PAY_PER_REQUEST_BILLING_MODE:
        raise ValueError(f"{model.__name__}.Meta.billing_mode is not a valid billing mode")
    return fields


def table_manifest(model: type[Model]) -> dict[str, object]:
    table_name = model.Meta.table_name
    table_keys = key_schema(model)

    # AttributeDefinitions must cover every key attribute used anywhere on the table,
    # table keys and GSI/LSI keys alike -- collect them de-duped, table keys first.
    attr_types: dict[str, str] = {name: attr_type for name, _, attr_type in table_keys}
    gsis: list[dict[str, object]] = []
    lsis: list[dict[str, object]] = []
    for index in declared_indexes(model):
        index_cls = type(index)
        index_keys = key_schema(index_cls)
        attr_types.update({name: attr_type for name, _, attr_type in index_keys})
        entry: dict[str, object] = {
            "indexName": index_cls.Meta.index_name,
            "keySchema": [{"attributeName": n, "keyType": t} for n, t, _ in index_keys],
            "projection": _projection(index_cls),
        }
        (lsis if isinstance(index, LocalSecondaryIndex) else gsis).append(entry)

    spec: dict[str, object] = {
        "tableName": table_name,
        **_billing_fields(model),
        "tableClass": "STANDARD",
        "attributeDefinitions": [
            {"attributeName": name, "attributeType": attr_type}
            for name, attr_type in attr_types.items()
        ],
        "keySchema": [{"attributeName": n, "keyType": t} for n, t, _ in table_keys],
    }
    if gsis:
        spec["globalSecondaryIndexes"] = gsis
    if lsis:
        spec["localSecondaryIndexes"] = lsis
    if ttl_attr := ttl_attribute_name(model):
        spec["timeToLive"] = {"attributeName": ttl_attr, "enabled": True}

    # Everything above comes from the pynamodb Model itself, so it can never drift.
    # NOT emitted, because nothing in a pynamodb Model represents them (set them via a
    # per-table override in values.yaml instead): continuousBackups,
    # contributorInsights, deletionProtectionEnabled, onDemandThroughput,
    # resourcePolicy, sseSpecification, streamSpecification, tableReplicas, tags.
    return {
        "apiVersion": "dynamodb.services.k8s.aws/v1alpha1",
        "kind": "Table",
        "metadata": {"name": _k8s_resource_name(table_name)},
        "spec": spec,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument(
        "output",
        nargs="?",
        default="-",
        help=(
            "File to write the manifests to. Omit or pass '-' for stdout, or '@chart' "
            f"for {_CHART_TABLES_FILE} (the chart's canonical location)."
        ),
    )
    args = parser.parse_args()

    docs = [table_manifest(model) for model in MODELS]
    text = json.dumps(docs, indent=2) + "\n"

    if args.output in ("", "-"):
        _ = sys.stdout.write(text)
    else:
        output_path = _CHART_TABLES_FILE if args.output == "@chart" else Path(args.output)
        _ = output_path.write_text(text)


if __name__ == "__main__":
    main()
