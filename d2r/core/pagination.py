"""Pagination — docs/backend/02-api.md §1.1."""

from collections import OrderedDict

from rest_framework import pagination
from rest_framework.response import Response


class PageNumberPagination(pagination.PageNumberPagination):
    page_size_query_param = "page_size"
    max_page_size = 96

    def get_paginated_response(self, data) -> Response:
        return Response(
            OrderedDict(
                results=data,
                pagination=OrderedDict(
                    count=self.page.paginator.count,
                    page=self.page.number,
                    page_size=self.get_page_size(self.request),
                    total_pages=self.page.paginator.num_pages,
                    next=self.get_next_link(),
                    previous=self.get_previous_link(),
                ),
            )
        )


class CursorPagination(pagination.CursorPagination):
    """For large, append-heavy sets — orders, movements, audit log.

    Stable under concurrent inserts, and OFFSET 50000 never happens.
    """

    page_size_query_param = "page_size"
    max_page_size = 100
    ordering = "-created_at"

    def get_paginated_response(self, data) -> Response:
        return Response(
            OrderedDict(
                results=data,
                pagination=OrderedDict(
                    next=self.get_next_link(),
                    previous=self.get_previous_link(),
                ),
            )
        )
