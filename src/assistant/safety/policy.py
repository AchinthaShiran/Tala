"""Policy engine: decides how each tool call must be authorised."""

from __future__ import annotations

from dataclasses import dataclass

from assistant.config import SafetySettings
from assistant.domain import ApprovalMode, RiskLevel, ToolSpec

_STRICTNESS = {
    ApprovalMode.AUTO: 0,
    ApprovalMode.ASK: 1,
    ApprovalMode.CONFIRM: 2,
    ApprovalMode.DENY: 3,
}


@dataclass(frozen=True, slots=True)
class PolicyContext:
    """Facts about the current run that tighten the policy."""

    untrusted_output_seen: bool = False


@dataclass(frozen=True, slots=True)
class Decision:
    mode: ApprovalMode
    reason: str


def _stricter(a: ApprovalMode, b: ApprovalMode) -> ApprovalMode:
    return a if _STRICTNESS[a] >= _STRICTNESS[b] else b


class PolicyEngine:
    """Risk-based approval with bounded overrides.

    Invariants (also covered by tests):
      * destructive tools are never ``auto``;
      * mutating tools are ``auto`` only when ``allow_auto_mutating`` is explicitly set;
      * after any tool output entered the model context, non-read-only tools need at least ``ask``.
    """

    def __init__(self, settings: SafetySettings) -> None:
        self._settings = settings

    def decide(self, spec: ToolSpec, ctx: PolicyContext | None = None) -> Decision:
        ctx = ctx or PolicyContext()
        mode = self._settings.modes[spec.risk]
        reason = f"default for {spec.risk.value}"
        override = self._settings.tool_overrides.get(spec.name)
        source = f"override for tool {spec.name}"
        if override is None:
            override = self._settings.pack_overrides.get(spec.pack)
            source = f"override for pack {spec.pack}"
        if override is not None:
            mode, reason = override, source

        if spec.risk is RiskLevel.DESTRUCTIVE and mode is ApprovalMode.AUTO:
            mode, reason = ApprovalMode.CONFIRM, "destructive tools are never automatic"
        if (
            spec.risk is RiskLevel.MUTATING
            and mode is ApprovalMode.AUTO
            and not self._settings.allow_auto_mutating
        ):
            mode, reason = ApprovalMode.ASK, "automatic mutation is not enabled"
        if ctx.untrusted_output_seen and spec.risk is not RiskLevel.READ_ONLY:
            tightened = _stricter(mode, ApprovalMode.ASK)
            if tightened is not mode:
                mode, reason = tightened, "tool output is in context (possible prompt injection)"
        return Decision(mode, reason)
