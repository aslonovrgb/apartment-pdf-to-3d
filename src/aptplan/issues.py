from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List

LEVELS = ("error", "warning", "info")
_LABEL = {"error": "ОШИБКА", "warning": "ПРЕДУПРЕЖДЕНИЕ", "info": "ИНФО"}


@dataclass(frozen=True)
class Issue:
    level: str   # error | warning | info
    ref: str     # ID of the element (or a path in plan.json)
    message: str

    def __str__(self) -> str:
        return f"{_LABEL[self.level]} [{self.ref}] {self.message}"


def errors(issues: Iterable[Issue]) -> List[Issue]:
    return [i for i in issues if i.level == "error"]


def warnings(issues: Iterable[Issue]) -> List[Issue]:
    return [i for i in issues if i.level == "warning"]
