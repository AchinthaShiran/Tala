"""Backend health checks used by ``lpa doctor`` and at start-up."""

from __future__ import annotations

from dataclasses import dataclass

import ollama

from assistant.config import Settings


@dataclass(frozen=True, slots=True)
class HealthCheck:
    name: str
    ok: bool
    detail: str
    fatal: bool = True


def _has_model(installed: set[str], wanted: str) -> bool:
    return wanted in installed or (":" not in wanted and f"{wanted}:latest" in installed)


def check_backend(settings: Settings, timeout: float = 3.0) -> list[HealthCheck]:
    """Verify Ollama is reachable and every configured model is pulled."""
    checks: list[HealthCheck] = []
    hosts = {m.base_url for m in settings.models.values()}
    if settings.embeddings:
        hosts.add(settings.embeddings.base_url)

    installed_by_host: dict[str, set[str]] = {}
    for host in sorted(hosts):
        try:
            client = ollama.Client(host=host, timeout=timeout)
            installed_by_host[host] = {m.model or "" for m in client.list().models}
            checks.append(HealthCheck(f"ollama@{host}", True, "reachable"))
        except Exception as exc:
            checks.append(HealthCheck(f"ollama@{host}", False, f"unreachable: {exc}"))

    for key, model in settings.models.items():
        installed = installed_by_host.get(model.base_url)
        if installed is None:
            continue
        found = _has_model(installed, model.name)
        detail = "pulled" if found else f"missing, run: ollama pull {model.name}"
        checks.append(HealthCheck(f"model '{key}' ({model.name})", found, detail))
        if found:
            checks.append(_tool_capability(model.base_url, model.name, key, timeout, settings))

    if settings.embeddings:
        installed = installed_by_host.get(settings.embeddings.base_url)
        if installed is not None:
            found = _has_model(installed, settings.embeddings.name)
            detail = (
                "pulled"
                if found
                else f"missing, run: ollama pull {settings.embeddings.name} "
                "(search falls back to keyword-only)"
            )
            checks.append(
                HealthCheck(f"embeddings ({settings.embeddings.name})", found, detail, fatal=False)
            )
    return [c for c in checks if c is not None]


def _tool_capability(
    host: str, name: str, key: str, timeout: float, settings: Settings
) -> HealthCheck:
    needs_tools = any(a.model == key for n, a in settings.agents.items() if n == "executor")
    if not needs_tools:
        return HealthCheck(f"tool calling '{key}'", True, "not required", fatal=False)
    try:
        caps = ollama.Client(host=host, timeout=timeout).show(name).capabilities or []
    except Exception:
        return HealthCheck(f"tool calling '{key}'", True, "could not verify", fatal=False)
    ok = "tools" in caps
    return HealthCheck(
        f"tool calling '{key}'",
        ok,
        "supported" if ok else "model does not advertise tool calling; pick another executor model",
        fatal=False,
    )
