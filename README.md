# dynamodb-ack-helm-pynamodb-demo

A small, self-contained demo of one pattern: **describe a DynamoDB table once, as a
[PynamoDB](https://pynamodb.readthedocs.io/) model, and derive everything else from
it** — the local `dynamodb-local` table *and* the production table (as an
[AWS Controllers for Kubernetes (ACK)](https://aws-controllers-k8s.github.io/community/)
`Table` manifest rendered by Helm).

The model is the single source of truth, so the deployed table can't silently drift
from what the code expects.

```
                app/models.py  (PynamoDB Model classes)
                          │  scripts/models.py: MODELS = [...]
              ┌───────────┴───────────────┐
              ▼                            ▼
 scripts/dev_migrate.py         scripts/gen_ack_tables.py
   create tables in              emit chart/files/dynamodb-tables.json
   dynamodb-local                          │  (ACK Table specs, as JSON)
   (local dev)                             ▼
                              chart/templates/dynamodb-tables.yaml
                              fromJsonArray + per-table overrides
                              from values.yaml
                                           │  helm template
                                           ▼
                              dynamodb.services.k8s.aws/v1alpha1
                              Table manifests → ACK controller → real AWS
```

## Layout

Split into **`app/`** (runtime code) and **`scripts/`** (dev tooling / one-off
generators). The one rule: `scripts/` imports from `app/`, never the reverse — the
production code has no dependency on the tooling.

| Path | What it is |
| --- | --- |
| `src/demo/app/models.py` | PynamoDB Model classes (the source of truth). |
| `src/demo/app/consts.py` | `TABLES_PREFIX`. |
| `src/demo/app/dynamodb.py` | `PageIteratorWithScanLimit` — bounds an unbounded query/scan walk. |
| `src/demo/app/schemas.py` | Pydantic response layer: validate straight from a pynamodb Model + `Timestamp`. |
| `src/demo/app/queries.py` | Example newest-first listing: limiter + cursor pagination + typed responses. |
| `src/demo/scripts/models.py` | `MODELS` list — which models need a real table (imports from `app/`). |
| `src/demo/scripts/introspect.py` | Reflection helpers: key schema, indexes, TTL attribute. |
| `src/demo/scripts/gen_ack_tables.py` | Reads `MODELS`, writes ACK `Table` specs as a JSON array. |
| `src/demo/scripts/dev_migrate.py` | Creates the tables in `dynamodb-local`. |
| `src/demo/pynamodb_settings.py` | `PYNAMODB_CONFIG` module (points at `dynamodb-local` in dev). |
| `chart/` | Helm chart that merges the generated JSON with per-table overrides. |
| `docker-compose.yaml` | `dynamodb-local` on `localhost:5555`. |

## Quickstart

Uses [uv](https://docs.astral.sh/uv/), but plain `pip install -e .` works too.

```bash
# 1. Generate the ACK Table manifest from the models, into the chart.
uv run gen-ack-tables @chart          # or: gen-ack-tables -  (stdout)

# 2. Render the chart to see the final Table manifests.
helm template chart

# 3. (optional) Run the tables locally.
docker compose up -d                  # dynamodb-local on :5555
uv run dev-migrate
```

Add a field/index to a model, then re-run step 1 and commit the regenerated
`chart/files/dynamodb-tables.json` — that file is the deploy-time contract.

## What the generator derives (and what it can't)

Straight from the model: `tableName`, `keySchema`, `attributeDefinitions`,
`globalSecondaryIndexes`, `localSecondaryIndexes`, `billingMode`
(+`provisionedThroughput` if `Meta.billing_mode` is `PROVISIONED`), and `timeToLive`
(from a `TTLAttribute`).

Nothing in a PynamoDB model represents these, so they're **not** generated — set them
per-table in `chart/values.yaml` under `dynamodbTables` instead: `continuousBackups`,
`contributorInsights`, `deletionProtectionEnabled`, `onDemandThroughput`,
`resourcePolicy`, `sseSpecification`, `streamSpecification`, `tableReplicas`, `tags`.
The chart merges those overrides onto the generated doc, keyed by `spec.tableName`.

## Gotchas

These are the sharp edges that actually cost time. Most aren't obvious until they bite.

### 1. YAML's bare `N` becomes `false` — so we emit JSON, not YAML

A DynamoDB Number attribute has `attributeType: N`. In **YAML 1.1**, the bool type
includes bare `y/Y/n/N/yes/no`. Go's YAML library (what Helm's `fromYamlArray` uses)
follows that faithfully, so unquoted `N` parses as `false`. PyYAML *also* claims YAML
1.1 but its bool resolver deliberately omits the single letters, so when it *dumps*
the string `"N"` it sees no ambiguity and writes it bare — round-trips fine in Python,
silently rots on the Helm side.

The fix is to sidestep the whole ambiguity class: `gen_ack_tables.py` emits **JSON**
(a subset of YAML, all strings quoted) and the chart reads it with **`fromJsonArray`**.
No quoting hacks, no per-token allowlist.

### 2. `PYNAMODB_CONFIG` is read once, at import time

PynamoDB loads its config from a *Python module* named by the `PYNAMODB_CONFIG` env
var — and it reads that module exactly once, when `pynamodb.settings` is first
imported. A model's `Meta.host`/`region`/creds are frozen from it at
**class-definition time**. Any `from demo.models import ...` transitively imports
`pynamodb.models → pynamodb.settings`.

Consequence: env setup must run **before any pynamodb-touching import**, not merely
before the first query. See `dev_migrate.py` — it sets the env vars at the top of
`main()` and imports the models *lazily, below that*. Get the order wrong and
pynamodb's own connection silently targets **real AWS**, which rejects the fake local
creds with `UnrecognizedClientException: The security token ... is invalid` — which
reads like an expired SSO session but really means "never pointed at localhost at all".

### 3. Fake creds for `dynamodb-local` must be *forced*

Setting `AWS_ACCESS_KEY_ID=FAKE` isn't enough if a real `AWS_SESSION_TOKEN` or
`AWS_PROFILE` is still exported — a leftover session token paired with a fake key also
trips `UnrecognizedClientException`. `dev_migrate._setup_dev_env()` overwrites the key
vars and **pops** `AWS_SESSION_TOKEN`/`AWS_PROFILE`.

### 4. `.Files.Get` can't read `templates/`

Helm excludes `templates/` from `.Files`. The generated data file therefore lives in
`chart/files/`, and it's a single JSON **array** (not `---`-separated docs, which
`fromYamlArray`/`fromJsonArray` can't parse).

### 5. Regeneration is a manual step

Nothing here enforces that `chart/files/dynamodb-tables.json` is up to date with the
models — the local table (auto-migrated) keeps working even when the committed
manifest is stale. Regenerate and commit it whenever a model's keys, attributes,
indexes, TTL, or billing mode change (or a model is added/removed from `MODELS`). In a
real repo this belongs in CI or a pre-commit hook.

### 6. Whole-table listing needs a constant-hash-key GSI (and it's a walk risk)

DynamoDB `Query` requires a hash key, so "list the whole table sorted by
`created_at`" isn't directly possible. The `Question` model shows the common trick: a
GSI whose hash key is a constant (`list_gsi_pk = 0`) plus a `created_at` range key,
queried as `Question.by_created_at.query(0, ...)`. The table needs its *own* plain
(non-key) copy of `list_gsi_pk` too, so PynamoDB has something to serialize on save —
but note `hash_key=True` belongs **only** on the GSI's copy; putting it on the table's
copy raises `ValueError: has more than one hash key` at class-definition time.

Caveat for production: this pattern funnels the whole table through one partition, and
a `filter_condition` that matches few/no rows will walk it to exhaustion regardless of
`limit` (`limit` bounds *results*, not *items scanned*). pynamodb's `ResultIterator`
only checks the remaining count *after* yielding an item, so a zero-match filter walks
the whole partition *before the first item is yielded* — `limit=10` and `limit=100_000`
do identical work. `page_size`, a wall-clock timeout, and `rate_limit=` all fail to
bound it. The only real fix is a **scanned-item budget** checked between raw page
fetches — `src/demo/app/dynamodb.py`'s `PageIteratorWithScanLimit`, swapped in for the
iterator's `page_iter` before consuming it (see `src/demo/app/queries.py` for a worked
example, including cursor pagination). Its full rationale is in the module docstring.

### 7. PynamoDB is sync-only

PynamoDB (6.x) has no async support — every `.query()/.scan()/.get()/.save()` blocks
the calling thread for the full round trip. If you wrap it in an async server, keep
the handlers `def` (run in a threadpool), never `async def` (which would block the
event loop for *every* in-flight request).

## Notes

This repo is AI-generated — extracted and genericized from a private codebase I work
in, kept here as a reusable reference for the pattern. Names and models are generic.
The ACK `Table` CRD reference is
[here](https://github.com/aws-controllers-k8s/dynamodb-controller/tree/main/test/e2e/resources).
