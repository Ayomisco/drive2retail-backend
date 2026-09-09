"""Operations read queries.

Query construction lives here so list endpoints keep their select_related
and prefetch_related in one place and stay inside the assertNumQueries
budgets in docs/backend/05-performance.md §3.1.
"""
