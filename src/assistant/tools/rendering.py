"""Turn a validated tool call into an argv list. Pure and shell-free."""

from __future__ import annotations

import re
import shlex
import subprocess
import sys
from collections.abc import Mapping

from assistant.domain import ConditionalArgs, InvalidArgumentsError, Platform, ToolSpec
from assistant.domain.tool import PLACEHOLDER_RE, ScalarValue


def render_arguments(
    spec: ToolSpec, args: Mapping[str, ScalarValue], platform: Platform
) -> list[str]:
    """Render the argument list (without the executable) for the given platform."""
    variant = spec.variant_for(platform)
    if variant is None:
        raise InvalidArgumentsError(f"tool {spec.name} has no variant for {platform.value}")
    rendered: list[str] = []
    for item in variant.args:
        if isinstance(item, ConditionalArgs):
            if _truthy(args.get(item.when)):
                rendered.extend(_substitute(arg, args, spec.name) for arg in item.args)
        else:
            rendered.append(_substitute(item, args, spec.name))
    return rendered


def format_command(argv: list[str]) -> str:
    """Display-only command line for approval prompts and logs."""
    if sys.platform.startswith("win"):
        return subprocess.list2cmdline(argv)
    return shlex.join(argv)


def _truthy(value: ScalarValue | None) -> bool:
    return value is not None and value is not False and value != ""


def _substitute(template: str, args: Mapping[str, ScalarValue], tool: str) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in args:
            raise InvalidArgumentsError(f"tool {tool}: no value for placeholder {{{name}}}")
        value = args[name]
        return ("true" if value else "false") if isinstance(value, bool) else str(value)

    return PLACEHOLDER_RE.sub(replace, template)
