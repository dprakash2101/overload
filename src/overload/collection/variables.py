from __future__ import annotations

import logging
import random
import re
import time
import uuid

from overload.collection.models import CollectionVariable

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

    def resolve_url(self, url: str) -> str:
        return self.resolve(url)
