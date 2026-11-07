"""Parsers used by API views that accept nested multipart payloads.

DRF's :class:`~rest_framework.parsers.MultiPartParser` only understands flat
form keys. A payload such as::

    color_variants[0][color_name]=Blue
    color_variants[0][sizes][0][size]=M
    color_variants[0][image]=<file>

therefore reaches the serializer as three literal strings instead of the nested
list of objects the product serializer expects.

``NestedMultiPartParser`` converts bracket (and dotted) notation back into
nested dicts/lists, including uploaded files, so product creation with variant
images can be a single atomic multipart request. Plain form data is unaffected.
"""

from __future__ import annotations

import re
from typing import Any

from django.utils.datastructures import MultiValueDict
from rest_framework import parsers

# Matches ``a``, ``[0]``, ``[key]``, ``[]`` and ``.key`` segments.
_TOKEN_RE = re.compile(r"([^\[\].]+)|\[([^\]]*)\]|\.([^\[\].]+)")


def _tokenize(key: str) -> list[str]:
    tokens: list[str] = []
    for match in _TOKEN_RE.finditer(key):
        token = next((group for group in match.groups() if group is not None), "")
        tokens.append(token)
    return tokens or [key]


def _set_value(container: dict, tokens: list[str], value: Any) -> None:
    """Assign ``value`` at ``tokens`` inside ``container``, creating nodes."""
    node: Any = container

    for index, token in enumerate(tokens):
        is_last = index == len(tokens) - 1

        if is_last:
            if isinstance(node, list):
                position = int(token) if token.isdigit() else len(node)
                while len(node) <= position:
                    node.append(None)
                node[position] = value
            else:
                existing = node.get(token)
                if existing is None:
                    node[token] = value
                elif isinstance(existing, list):
                    existing.append(value)
                else:
                    node[token] = [existing, value]
            return

        next_token = tokens[index + 1]

        if isinstance(node, list):
            position = int(token) if token.isdigit() else len(node)
            while len(node) <= position:
                node.append(None)
            if node[position] is None:
                node[position] = [] if next_token.isdigit() else {}
            node = node[position]
        else:
            child = node.get(token)
            if child is None:
                child = [] if next_token.isdigit() else {}
                node[token] = child
            node = child


def _normalise(value: Any) -> Any:
    """Turn numeric-keyed dicts into lists, recursively."""
    if isinstance(value, list):
        return [_normalise(item) for item in value if item is not None]
    if isinstance(value, dict):
        if value and all(str(key).isdigit() for key in value):
            items = sorted(value.items(), key=lambda item: int(item[0]))
            return [_normalise(item) for _, item in items]
        return {key: _normalise(item) for key, item in value.items()}
    return value


class NestedMultiPartParser(parsers.MultiPartParser):
    """Multipart parser that understands bracket/dot nested field names."""

    def parse(self, stream, media_type=None, parser_context=None):
        parsed = super().parse(stream, media_type, parser_context)
        data = parsed.data
        files = parsed.files
        nested: dict[str, Any] = {}

        # Text fields. ``lists()`` preserves repeated keys.
        for key, values in data.lists():
            for value in values:
                _set_value(nested, _tokenize(key), value)

        # Uploaded files are merged into the same nested structure.
        for key, values in files.lists():
            for value in values:
                _set_value(nested, _tokenize(key), value)

        return parsers.DataAndFiles(_normalise(nested), MultiValueDict())
