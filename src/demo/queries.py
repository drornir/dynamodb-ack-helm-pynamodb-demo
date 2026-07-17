"""Example read path for the Question table -- shows the whole-table-listing GSI in
use, cursor pagination, and where ``PageIteratorWithScanLimit`` gets swapped in to
bound the walk (see ``demo.dynamodb`` for why that bound is necessary).
"""

import base64
import json

from demo.dynamodb import PageIteratorWithScanLimit
from demo.models import Question


def list_questions_newest_first(
    *,
    creator_name: str | None = None,
    limit: int = 20,
    cursor: str | None = None,
    max_scanned_items: int = 10_000,
) -> tuple[list[dict[str, object]], str | None]:
    """A newest-first page of questions, optionally filtered by creator.

    Queries the constant-hash-key GSI (``models.QuestionsByCreatedAt``) so the whole
    table can be listed/sorted by ``created_at`` -- the same pattern that makes an
    unbounded walk possible, which is why the scan budget below is not optional.
    """
    filter_condition = None
    if creator_name:
        filter_condition = Question.creator_name == creator_name

    # An opaque cursor: base64(json(LastEvaluatedKey)) out, decoded back in.
    last_evaluated_key = json.loads(base64.urlsafe_b64decode(cursor)) if cursor else None

    # With a selective filter, scan more per round trip than the final count, so we
    # don't make many tiny requests to accumulate `limit` matches.
    page_size = limit + 100 if filter_condition is not None else limit

    results = Question.by_created_at.query(
        0,  # the constant partition key
        filter_condition=filter_condition,
        limit=limit,
        last_evaluated_key=last_evaluated_key,
        scan_index_forward=False,  # newest first
        page_size=page_size,
    )
    # Bound the walk BEFORE consuming the iterator (see demo.dynamodb).
    results.page_iter = PageIteratorWithScanLimit(results.page_iter, max_scanned_items)

    # Consume fully -- last_evaluated_key is only a valid cursor after exhaustion.
    items = [q.to_simple_dict() for q in results]

    next_cursor = (
        base64.urlsafe_b64encode(json.dumps(results.last_evaluated_key).encode()).decode()
        if results.last_evaluated_key
        else None
    )
    return items, next_cursor
