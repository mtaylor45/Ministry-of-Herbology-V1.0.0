"""Which operations need a session, read from the contract itself.

The exempt list is not written out here: it is every operation the OpenAPI
document marks ``security: []``. A route added later is protected unless the
contract says otherwise, and an exemption cannot drift from the document that
promises it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

PREFIX = "/api/v1"
_METHODS = ("get", "put", "post", "delete", "patch")


@dataclass(frozen=True, slots=True)
class Operation:
    method: str
    template: str
    pattern: re.Pattern[str]
    #: Every requirement the contract lists, by scheme name. Empty = open.
    schemes: frozenset[str]

    @property
    def open(self) -> bool:
        return not self.schemes

    @property
    def accepts_lunette(self) -> bool:
        return "lunette" in self.schemes


def _compile(template: str) -> re.Pattern[str]:
    parts = re.split(r"(\{[^}/]+\})", template)
    regex = "".join(r"[^/]+" if p.startswith("{") else re.escape(p) for p in parts)
    return re.compile(f"^{re.escape(PREFIX)}{regex}$")


def _schemes(requirements: list[dict[str, object]] | None) -> frozenset[str] | None:
    if requirements is None:
        return None
    return frozenset(name for requirement in requirements for name in requirement)


@dataclass(frozen=True, slots=True)
class Policy:
    operations: tuple[Operation, ...]

    def match(self, method: str, path: str) -> Operation | None:
        method = method.lower()
        # Literal segments beat parameters: `/journal/plates` before
        # `/journal/{specimen_id}`. Sorting by parameter count does it.
        for operation in self.operations:
            if operation.method == method and operation.pattern.match(path):
                return operation
        return None

    def open_operations(self) -> list[tuple[str, str]]:
        return sorted((o.method, o.template) for o in self.operations if o.open)


def build_policy(spec: dict) -> Policy:
    default = _schemes(spec.get("security")) or frozenset()
    operations = []
    for template, item in (spec.get("paths") or {}).items():
        for method in _METHODS:
            operation = item.get(method)
            if operation is None:
                continue
            declared = _schemes(operation.get("security"))
            operations.append(
                Operation(
                    method=method,
                    template=template,
                    pattern=_compile(template),
                    schemes=default if declared is None else declared,
                )
            )
    operations.sort(key=lambda o: (o.template.count("{"), -len(o.template)))
    return Policy(tuple(operations))


@lru_cache(maxsize=1)
def load_policy(contracts_dir: Path) -> Policy:
    spec = yaml.safe_load((contracts_dir / "openapi" / "openapi.yaml").read_text())
    return build_policy(spec)
