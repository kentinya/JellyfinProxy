"""Match incoming requests to a handler category."""

from __future__ import annotations

from routers.route_config import ROUTE_RULES, HandlerType, RouteRule


class Router:
    def __init__(self, rules: tuple[RouteRule, ...] = ROUTE_RULES) -> None:
        self._rules = rules

    def match(self, path: str, method: str) -> HandlerType:
        normalized_method = method.upper()
        for rule in self._rules:
            if rule.methods is not None and normalized_method not in rule.methods:
                continue
            if rule.pattern.fullmatch(path):
                return rule.handler_type
        return HandlerType.DEFAULT
