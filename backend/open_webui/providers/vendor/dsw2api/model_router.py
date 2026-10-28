"""
Model router — maps a client-supplied `model` field to DeepSeek's per-request
capability flags.

Background (verified against the live upstream on 2026-10-18):
  ``GET /api/v0/client/settings?scope=model`` now advertises

      {"model_type":"default","name":"快速模式","enabled":true, "switchable":true }
      {"model_type":"expert", "name":"专家模式","enabled":false,"switchable":false}
      {"model_type":"vision", "name":"识图模式","enabled":false,"switchable":false}

  and the completion endpoint rewrites any client-supplied ``model_type`` back
  to ``"default"`` (observed in the ``event: ready`` frame).  In other words
  DeepSeek merged the quick/expert modes: there is only ONE chat model, and the
  behaviour users associate with "expert mode" is produced solely by
  ``thinking_enabled``.  A/B runs of ``model_type=default`` vs ``expert`` on the
  same prompt produced byte-identical answers and indistinguishable latency, and
  DSML tool calling works identically in both.

What this module therefore does now:
  * ``model_type`` is a **protocol field**, not a capability selector.  It stays
    in ``RouteDecision`` so the request body keeps matching the browser's shape
    and so a future re-enable (e.g. ``vision``) only needs a routing-table edit —
    but it defaults to ``"default"`` and no longer carries quick/expert meaning.
  * the real capabilities are ``thinking`` (→ ``thinking_enabled``) and
    ``search`` (→ ``search_enabled``).
  * this proxy serves **one model**.  ``/v1/models`` lists the single configured
    name (``MODEL_NAME``); whether it thinks is configured server-side with
    ``THINKING``, not by picking a different model name.  Legacy names such as
    ``deepseek-reasoner`` are accepted as aliases (see ``LEGACY_MODEL_ALIASES``)
    but no longer change behaviour.

Optional per-model overrides (env var ``MODEL_ROUTES``, advanced use only —
leave it unset for the normal single-model setup)::

  MODEL_ROUTES='{"my-model":"thinking"}'          # alias name → thinking on
  MODEL_ROUTES='{"my-model":{"thinking":"disabled","search":"enabled"}}'

Shorthand strings (they are capability presets now):
  * ``"default"`` / ``"quick"``   — thinking off (fast, no chain-of-thought)
  * ``"thinking"`` / ``"expert"`` / ``"reasoner"`` — thinking on (the former
    "expert mode" experience)
  * ``{"model_type": "default", "thinking": "enabled", "search": "disabled"}``
    for full per-route control (``model_type`` is a protocol value only).

Resolution priority (highest first):
  1. A ``MODEL_ROUTES`` entry matching the client's ``model`` name.
  2. The ``THINKING`` / ``SEARCH`` env-var values (``MODE`` is legacy, see
     ``server.resolve_model_controls``).
  3. The per-request ``thinking_mode`` / ``search_enabled`` fields.

The router never raises on a missing model — it just falls through to the
existing env-var logic so the proxy is backward-compatible.
"""
from __future__ import annotations

from . import managed_env


import json
import os
from dataclasses import dataclass
from typing import Optional

from .logger import get_logger

log = get_logger("model_router")

#: Route shorthand → "thinking enabled?" capability preset.
#: ``expert``/``quick`` are retained purely as legacy aliases for pre-merge configs.
_SHORTHANDS: dict[str, bool] = {
    "default": False,
    "quick": False,       # legacy alias
    "thinking": True,
    "expert": True,       # legacy alias — upstream merged expert into thinking
    "reasoner": True,     # convenience alias
}

#: The only ``model_type`` the upstream still honours; everything else is
#: rewritten to this server-side.  Kept configurable for the day ``vision``
#: (or a re-enabled ``expert``) comes back.
DEFAULT_MODEL_TYPE = "default"

#: Model names that used to select a capability but are now just aliases of the
#: single model this proxy serves.  They are accepted (so existing clients keep
#: working) and normalised to the canonical name; they do **not** change
#: behaviour any more — ``THINKING`` / the request field does that.
LEGACY_MODEL_ALIASES: dict[str, str] = {
    "deepseek-reasoner": "deepseek-chat",
    "deepseek-r1": "deepseek-chat",
    "deepseek-thinking": "deepseek-chat",
    "deepseek-expert": "deepseek-chat",
    "deepseek-chat-thinking": "deepseek-chat",
    "deepseek-chat-direct": "deepseek-chat",
}


def canonical_model_name(model: str) -> str:
    """Map a legacy/aliased model name onto the single canonical model name."""
    if not model:
        return model
    return LEGACY_MODEL_ALIASES.get(model.strip().lower(), model)


@dataclass
class RouteDecision:
    model_type: str = DEFAULT_MODEL_TYPE   # protocol field; upstream normalises to "default"
    thinking: Optional[bool] = None        # True/False override; None = respect env/client
    search: Optional[bool] = None
    matched_model: Optional[str] = None    # the public model that matched, if any


@dataclass
class _Route:
    model_type: str = DEFAULT_MODEL_TYPE
    thinking: Optional[bool] = None
    search: Optional[bool] = None


class ModelRouter:
    def __init__(self, raw: str | None = None, models: list[str] | None = None):
        self._routes: dict[str, _Route] = {}
        self._fallback_models: list[str] = list(models or [])
        self._raw = raw if raw is not None else managed_env.get("MODEL_ROUTES", "")
        if self._raw:
            self._parse(self._raw)

    def _parse(self, raw: str) -> None:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            log.warning("model_routes_parse_failed", extra={"error": str(e), "raw": raw[:200]})
            return
        if not isinstance(data, dict):
            log.warning("model_routes_not_object", extra={"type": type(data).__name__})
            return
        for name, spec in data.items():
            try:
                self._routes[str(name)] = self._route_from_spec(spec)
            except Exception as e:  # noqa: BLE001
                log.warning("model_route_invalid", extra={"model": name, "error": str(e)})

    @staticmethod
    def _route_from_spec(spec) -> _Route:
        if isinstance(spec, str):
            key = spec.strip().lower()
            if key not in _SHORTHANDS:
                raise ValueError(f"unknown route shorthand: {spec!r}")
            return _Route(model_type=DEFAULT_MODEL_TYPE, thinking=_SHORTHANDS[key])
        if isinstance(spec, dict):
            mt = str(spec.get("model_type", DEFAULT_MODEL_TYPE)).strip().lower()
            if not mt:
                mt = DEFAULT_MODEL_TYPE
            return _Route(
                model_type=mt,
                thinking=ModelRouter._coerce_bool(spec.get("thinking")),
                search=ModelRouter._coerce_bool(spec.get("search")),
            )
        raise ValueError(f"unsupported route spec type: {type(spec).__name__}")

    @staticmethod
    def _coerce_bool(value) -> Optional[bool]:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            v = value.strip().lower()
            if v in {"1", "true", "yes", "on", "enabled"}:
                return True
            if v in {"0", "false", "no", "off", "disabled"}:
                return False
        return None

    @property
    def models(self) -> list[str]:
        """Public model names to advertise on ``/v1/models``.

        With ``MODEL_ROUTES`` unset this is a **single** entry — this proxy
        serves one model, and whether it thinks is configured server-side
        (``THINKING``), not chosen by picking a different model name.  The list
        is only ever injected by the caller, never derailed by legacy aliases.
        """
        if self._routes:
            return list(self._routes.keys())
        return list(self._fallback_models)

    def route_for(self, model: Optional[str]) -> RouteDecision:
        """Return a route decision for the given client ``model`` field.

        Legacy names (``deepseek-reasoner``, ``*-thinking``, …) resolve to the
        same single model: they are accepted so old clients keep working, but
        they no longer select a different behaviour — thinking is controlled by
        ``THINKING`` / the request field.

        A model that is not in the routing table returns a default decision
        (``model_type="default"``, no capability overrides) — the caller then
        applies THINKING / SEARCH env-var logic as before.
        """
        if not model:
            return RouteDecision()
        canonical = canonical_model_name(model)
        route = self._routes.get(model)
        if route is None and canonical != model:
            route = self._routes.get(canonical)
        if route is None:
            return RouteDecision()
        return RouteDecision(
            model_type=route.model_type,
            thinking=route.thinking,
            search=route.search,
            matched_model=model,
        )
