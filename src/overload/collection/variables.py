from __future__ import annotations

import logging
import random
import re
import time
import uuid
from typing import TYPE_CHECKING

from overload.collection.models import CollectionVariable

if TYPE_CHECKING:
    from overload.collection.models import ParsedCollection

logger = logging.getLogger(__name__)

VARIABLE_PATTERN = re.compile(r"\{\{([^}]+)\}\}")

DYNAMIC_VARIABLES: dict[str, callable] = {
    "$randomInt": lambda: str(random.randint(0, 1000)),
    "$timestamp": lambda: str(int(time.time())),
    "$guid": lambda: str(uuid.uuid4()),
    "$randomBoolean": lambda: random.choice(["true", "false"]),
    "$randomColor": lambda: random.choice(["red", "blue", "green", "yellow", "purple"]),
    "$randomFirstName": lambda: random.choice(["John", "Jane", "Alice", "Bob", "Charlie"]),
    "$randomEmail": lambda: f"user{random.randint(1, 9999)}@example.com",
}


class VariableContext:
    def __init__(
        self,
        collection_vars: list[CollectionVariable] | None = None,
        environment_vars: dict[str, str] | None = None,
        runtime_vars: dict[str, str] | None = None,
    ) -> None:
        self._scopes: list[dict[str, str]] = [
            runtime_vars or {},
            environment_vars or {},
            {v.key: v.value for v in (collection_vars or [])},
        ]
        self._unresolved: set[str] = set()

    @property
    def unresolved(self) -> set[str]:
        return self._unresolved.copy()

    def set_variable(self, key: str, value: str) -> None:
        self._scopes[0][key] = value

    def get_variable(self, key: str) -> str | None:
        for scope in self._scopes:
            if key in scope:
                return scope[key]
        return None

    def get_all_variables(self) -> dict[str, str]:
        merged: dict[str, str] = {}
        for scope in reversed(self._scopes):
            merged.update(scope)
        return merged

    def resolve(self, template: str) -> str:
        if not template or "{{" not in template:
            return template

        def _replacer(match: re.Match) -> str:
            var_name = match.group(1).strip()

            if var_name in DYNAMIC_VARIABLES:
                return DYNAMIC_VARIABLES[var_name]()

            for scope in self._scopes:
                if var_name in scope:
                    value = scope[var_name]
                    return self.resolve(value) if "{{" in value else value

            self._unresolved.add(var_name)
            logger.warning("Unresolved variable: {{%s}}", var_name)
            return match.group(0)

        return VARIABLE_PATTERN.sub(_replacer, template)

    def resolve_dict(self, d: dict[str, str]) -> dict[str, str]:
        return {self.resolve(k): self.resolve(v) for k, v in d.items()}

    def derive(self, extra: dict[str, str]) -> VariableContext:
        new = VariableContext.__new__(VariableContext)
        new._scopes = [extra, *self._scopes]
        new._unresolved = self._unresolved
        return new

    def resolve_url(self, url: str) -> str:
        return self.resolve(url)


def discover_placeholders(collection: ParsedCollection) -> set[str]:
    """Return all {{placeholder}} variable names used anywhere in a collection.

    Scans: url_raw, header keys+values, query param keys+values, body content,
    request auth params (keys+values), and collection-level auth params.
    """
    found: set[str] = set()

    def _scan(text: str) -> None:
        for name in VARIABLE_PATTERN.findall(text):
            found.add(name)

    if collection.auth:
        for k, v in collection.auth.params.items():
            _scan(k)
            _scan(v)

    for req in collection.requests:
        _scan(req.url_raw)
        for k, v in req.headers.items():
            _scan(k)
            _scan(v)
        for qp in req.query_params:
            _scan(qp.key)
            _scan(qp.value)
        _scan(str(req.body.content) if req.body.content else "")
        if req.auth:
            for k, v in req.auth.params.items():
                _scan(k)
                _scan(v)

    return found
