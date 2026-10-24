"""Quality gate for everything we ship: every builtin tool must be valid, lint-clean and renderable."""

from __future__ import annotations

import pytest

from assistant.config import builtin_packs_dir
from assistant.domain import Platform, RiskLevel, ToolSpec
from assistant.domain.tool import ParamSpec
from assistant.packs import PackRoot, load_packs
from assistant.tools import render_arguments, validate_arguments

REPORT = load_packs([PackRoot(builtin_packs_dir(), "builtin")])
TOOLS = sorted(REPORT.tools.values(), key=lambda t: t.name)


def sample(param: ParamSpec) -> object:
    if param.default is not None:
        return param.default
    if param.enum:
        return param.enum[0]
    if param.type == "integer":
        return int(param.minimum or 5) if param.minimum is None or param.minimum >= 1 else 5
    if param.type == "number":
        return 1.0
    if param.type == "boolean":
        return True
    pattern = param.pattern or ""
    if "https?" in pattern:
        return "https://example.com/a"
    if "apk" in pattern:
        return "app.apk"
    if "0-9a-fA-F]{8}" in pattern:
        return "12345678-1234-1234-1234-123456789abc"
    return "a1"


def test_all_builtin_packs_load_without_errors_or_warnings():
    assert REPORT.errors == [], "\n".join(map(str, REPORT.errors))
    assert REPORT.warnings == [], "\n".join(map(str, REPORT.warnings))
    assert len(TOOLS) >= 90


def test_tool_names_unique_and_nonempty_descriptions():
    names = [t.name for t in TOOLS]
    assert len(names) == len(set(names))


@pytest.mark.parametrize("spec", TOOLS, ids=lambda t: t.name)
def test_every_tool_renders_on_every_supported_platform(spec: ToolSpec):
    args = validate_arguments(spec, {n: sample(p) for n, p in spec.parameters.items()})
    for platform in (Platform.WINDOWS, Platform.LINUX, Platform.MACOS):
        if spec.supports(platform):
            argv = render_arguments(spec, args, platform)
            assert all(isinstance(a, str) for a in argv)
            assert not any("{" + p + "}" in a for a in argv for p in spec.parameters)


def test_risk_distribution_is_sane():
    by_risk = {r: [t.name for t in TOOLS if t.risk is r] for r in RiskLevel}
    assert (
        by_risk[RiskLevel.READ_ONLY]
        and by_risk[RiskLevel.MUTATING]
        and by_risk[RiskLevel.DESTRUCTIVE]
    )
    for must_not_be_read_only in (
        "git_push",
        "git_commit",
        "docker_stop",
        "npm_install",
        "winget_install",
        "adb_reboot",
        "kill_process",
        "adb_delete_file",
    ):
        assert must_not_be_read_only in by_risk[RiskLevel.MUTATING] + by_risk[RiskLevel.DESTRUCTIVE]
    for destructive in ("git_push", "kill_process", "adb_delete_file", "adb_uninstall_app"):
        assert destructive in by_risk[RiskLevel.DESTRUCTIVE]


def test_every_os_has_core_capabilities():
    core = {"disk_free", "list_processes", "network_config", "ping_host", "memory_usage", "os_info"}
    for platform in (Platform.WINDOWS, Platform.LINUX, Platform.MACOS):
        supported = {t.name for t in TOOLS if t.supports(platform)}
        assert core <= supported, f"{platform}: missing {core - supported}"


def test_adb_shell_arguments_cannot_carry_shell_metacharacters():
    """`adb shell` re-parses its arguments on the device, so inputs must be tightly constrained."""
    import re

    for name in (
        "adb_list_files",
        "adb_find_package",
        "adb_get_property",
        "adb_launch_app",
        "adb_delete_file",
        "adb_force_stop_app",
    ):
        spec = REPORT.tools[name]
        for param in spec.parameters.values():
            if param.type == "string":
                assert param.pattern, f"{name} has an unconstrained string parameter"
                assert not re.search(param.pattern, "x; rm -rf /"), name
                assert not re.search(param.pattern, "x$(id)"), name


STATE_CHANGING_WORDS = {
    "install", "uninstall", "reboot", "reboot-bootloader", "rm", "push", "pull", "kill",
    "kill-server", "start-server", "stop", "start", "connect", "disconnect", "add", "commit",
    "tcpip", "setactive", "force-stop", "clear", "screencap", "monkey", "input", "taskkill",
    "flash", "erase", "delete", "format", "/setactive", "/PID",
}  # fmt: skip


def test_commands_with_state_changing_verbs_are_never_read_only():
    """Guards against mislabelling (adb_install_apk once shipped as read_only)."""
    offenders = []
    for spec in TOOLS:
        if spec.risk is not RiskLevel.READ_ONLY:
            continue
        for variant in spec.run.values():
            words = {a for a in variant.args if isinstance(a, str)}
            for item in variant.args:
                if not isinstance(item, str):
                    words |= set(item.args)
            if words & STATE_CHANGING_WORDS:
                offenders.append((spec.name, sorted(words & STATE_CHANGING_WORDS)))
    assert not offenders, offenders


def test_known_risk_labels_for_android_and_reboot_tools():
    expected = {
        "adb_install_apk": RiskLevel.MUTATING,
        "adb_reboot_bootloader": RiskLevel.MUTATING,
        "fastboot_reboot_bootloader": RiskLevel.MUTATING,
        "adb_uninstall_app": RiskLevel.DESTRUCTIVE,
        "adb_battery": RiskLevel.READ_ONLY,
        "adb_list_reversed": RiskLevel.READ_ONLY,
    }
    assert {name: REPORT.tools[name].risk for name in expected} == expected


def test_powershell_tools_cannot_be_given_quote_characters():
    """Values are embedded in single-quoted PowerShell strings, so quotes must never get through."""
    import re

    for spec in TOOLS:
        windows = spec.run.get(Platform.WINDOWS)
        if windows is None or windows.exe != "powershell":
            continue
        script = " ".join(str(a) for a in windows.args)
        for name, param in spec.parameters.items():
            if param.type == "string" and "{" + name + "}" in script:
                assert param.pattern or param.enum, (spec.name, name)
                if param.pattern:
                    for bad in ("x'; Remove-Item *; '", 'x" y', "x`y", "x\ny"):
                        assert not re.search(param.pattern, bad), (spec.name, name, bad)


def test_known_risk_labels_for_new_packs():
    expected = {
        "read_file": RiskLevel.READ_ONLY,
        "file_properties": RiskLevel.READ_ONLY,
        "copy_file": RiskLevel.MUTATING,
        "move_file": RiskLevel.MUTATING,
        "delete_file": RiskLevel.DESTRUCTIVE,
        "pip_install": RiskLevel.MUTATING,
        "pip_uninstall": RiskLevel.DESTRUCTIVE,
        "run_python_script": RiskLevel.DESTRUCTIVE,
        "ssh_run_command": RiskLevel.DESTRUCTIVE,
        "firewall_block_port": RiskLevel.DESTRUCTIVE,
        "service_stop": RiskLevel.DESTRUCTIVE,
        "git_reset_hard": RiskLevel.DESTRUCTIVE,
        "git_pull": RiskLevel.MUTATING,
        "download_file": RiskLevel.MUTATING,
        "http_get": RiskLevel.READ_ONLY,
    }
    assert {name: REPORT.tools[name].risk for name in expected} == expected
