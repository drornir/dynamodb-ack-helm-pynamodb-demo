"""Shared pynamodb helpers.

``PageIteratorWithScanLimit`` bounds how much of a table/index a single query or scan
is allowed to walk. It exists because of a genuinely surprising DynamoDB + pynamodb
edge case, explained below.

## The edge case: `limit` bounds results, not work

DynamoDB's raw ``Limit`` caps items *evaluated per page, before* the filter runs, so a
page can return fewer matches than ``Limit``. pynamodb's ``ResultIterator`` hides that
at the *results* level: ``Model.query(..., filter_condition=cond, limit=6)`` yields up
to 6 *matching* items by fetching more raw pages as needed.

The trap: ``limit`` bounds *results returned*, not *work done*. ``ResultIterator``
only checks/decrements its remaining-count *after* it yields an item; the inner loop
that fetches raw pages (following ``LastEvaluatedKey``) never consults ``limit`` at
all. So a ``filter_condition`` that matches zero or very few rows walks the **entire**
table (or GSI partition) to key exhaustion *before the first item is ever yielded* --
``limit=10`` and ``limit=100_000`` do identical work. This is worst for the
whole-table-listing GSI pattern (one constant partition key, no key range to shrink
the walk), where a caller- or agent-supplied filter value can trigger a full-partition
scan.

Things that do NOT fix it:
- ``page_size`` -- only changes how the same total walk is chunked into round trips.
- a wall-clock timeout around the loop -- the walk is blocking round trips inside a
  worker thread with no cancellation, and during a zero-match stretch the loop body
  (where you'd check the clock) never runs.
- ``rate_limit=`` -- throttles consumed capacity, a different axis, not walk length.

The only real bound is a **scanned-item budget**, checked *between* raw page fetches --
the one point that always executes, filtered or not. pynamodb exposes exactly one hook
for this: ``PageIterator.total_scanned_count``.

## How to use it

Swap it in for the ``ResultIterator``'s ``page_iter`` before consuming the iterator,
then consume as normal:

    results = Model.query(pk, filter_condition=cond, limit=20)
    results.page_iter = PageIteratorWithScanLimit(results.page_iter, max_scanned_items=5_000)
    items = [x.to_simple_dict() for x in results]

Raising ``StopIteration`` from inside propagates out through ``ResultIterator.__next__``
exactly like real exhaustion, so ``results.last_evaluated_key`` still comes back as a
valid, resumable cursor when the budget cuts a walk short -- callers keep resuming in
bounded increments instead of one call doing an unbounded walk.

It subclasses ``PageIterator`` purely so the ``page_iter =`` assignment satisfies the
type checker (pynamodb types that attribute nominally, not as a Protocol), skips
``super().__init__()``, and forwards every attribute it doesn't override
(``last_evaluated_key``, ``total_scanned_count``, ...) to the wrapped iterator.
"""

from collections.abc import Iterator
from typing import Any, override

from pynamodb.pagination import PageIterator


class PageIteratorWithScanLimit[T](PageIterator[Iterator[T]]):
    def __init__(self, page_iter: PageIterator[Iterator[T]], max_scanned_items: int = 10_000):
        if max_scanned_items <= 0:
            raise ValueError("max_scanned_items must be positive")
        self.wrapped_page_iter = page_iter
        self.max_scanned_items = max_scanned_items

    @override
    def __iter__(self) -> Iterator[Iterator[T]]:
        return self

    @override
    def __next__(self) -> Iterator[T]:
        scanned = self.wrapped_page_iter.total_scanned_count
        if scanned > self.max_scanned_items:
            raise StopIteration(f"Max scanned items exceeded ({scanned=} > {self.max_scanned_items=})")
        return next(self.wrapped_page_iter)

    def __getattr__(self, name: str) -> Any:
        """Pass through every attribute we don't override to the wrapped iterator."""
        return getattr(self.wrapped_page_iter, name)
