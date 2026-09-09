"""Procurement business logic.

Services own the rules. Views and serializers stay thin, and anything that
touches money or stock runs inside transaction.atomic() with explicit row
locks — see docs/backend/03-flows.md §1.
"""
