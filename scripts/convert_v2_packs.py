"""One-off migration of the v2 prototype packs to the v3 format.

Usage: python scripts/convert_v2_packs.py <v2 suites dir> <output dir>

v2 packs lacked risk tags, enum values, numeric bounds and input constraints, and some commands
(``adb shell ...``) were open to remote-shell injection. This script applies explicit, reviewed
tables for those; the v3 loader/validator then checks the result.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import yaml

SUITES: dict[str, dict[str, Any]] = {
    "adb": {
        "platform": "any",
        "category": "android",
        "keywords": ["android", "phone", "device", "adb"],
    },
    "fastboot": {
        "platform": "any",
        "category": "android",
        "keywords": ["android", "bootloader", "fastboot"],
    },
    "scrcpy": {
        "platform": "any",
        "category": "android",
        "keywords": ["android", "mirror", "scrcpy"],
    },
    "docker": {
        "platform": "any",
        "category": "containers",
        "keywords": ["docker", "container", "image"],
    },
    "git": {
        "platform": "any",
        "category": "source-control",
        "keywords": ["git", "repository", "commit"],
    },
    "npm": {
        "platform": "any",
        "category": "javascript",
        "keywords": ["npm", "node", "package", "javascript"],
    },
    "winget": {
        "platform": "windows",
        "category": "software",
        "keywords": ["winget", "install", "app", "software", "update"],
    },
    "powercfg": {
        "platform": "windows",
        "category": "power",
        "keywords": ["power", "battery", "plan", "sleep"],
    },
    "schtasks": {
        "platform": "windows",
        "category": "automation",
        "keywords": ["scheduled", "task", "cron"],
    },
    "wevtutil": {
        "platform": "windows",
        "category": "logs",
        "keywords": ["event", "log", "errors", "windows"],
    },
}
SKIP_TOOLS = {"scrcpy_mirror", "scrcpy_mirror_screen_off"}  # long-running GUI processes

DESTRUCTIVE = {
    "adb_delete_file": "This permanently deletes a file on the connected Android device.",
    "adb_uninstall_app": "This uninstalls an app from the Android device and may delete its data.",
    "adb_clear_app_data": "This erases all data and settings of an app on the Android device.",
    "git_push": "This publishes your commits to the remote repository and is hard to undo.",
}
# Explicit, reviewed list of full names. A suffix heuristic once mislabelled adb_install_apk.
MUTATING = {
    "adb_start_server", "adb_kill_server", "adb_connect", "adb_disconnect", "adb_tcpip",
    "adb_clear_logcat", "adb_pull_file", "adb_push_file", "adb_screenshot", "adb_install_apk",
    "adb_force_stop_app", "adb_launch_app", "adb_press_key", "adb_reverse_port", "adb_reboot",
    "adb_reboot_bootloader", "fastboot_reboot", "fastboot_reboot_bootloader",
    "git_add", "git_commit", "docker_stop", "docker_start",
    "npm_install", "npm_add_package", "npm_run_script", "npm_test", "npm_uninstall",
    "winget_install", "winget_upgrade_package", "powercfg_set_active_plan",
}  # fmt: skip
LONG_TIMEOUT = {
    "npm_install": 600,
    "npm_add_package": 600,
    "npm_uninstall": 300,
    "npm_test": 600,
    "npm_run_script": 600,
    "winget_install": 900,
    "winget_upgrade_package": 900,
    "winget_search": 60,
    "winget_list_upgradable": 90,
    "winget_list_installed": 90,
    "adb_install_apk": 300,
    "adb_pull_file": 300,
    "adb_push_file": 300,
    "adb_wait_for_device": 20,
    "adb_screenshot": 30,
}

REMOTE = r"^[A-Za-z0-9._/@+-]+$"
NAMEISH = r"^[A-Za-z0-9._@/:-]+$"
PARAM_RULES: dict[str, dict[str, Any]] = {
    "address": {"pattern": r"^[A-Za-z0-9.:\[\]-]+$", "max_length": 80},
    "container": {"pattern": r"^[A-Za-z0-9][A-Za-z0-9_.-]*$", "max_length": 128},
    "filter": {"pattern": NAMEISH, "max_length": 100},
    "message": {"max_length": 300},
    "package": {"pattern": NAMEISH, "max_length": 214},
    "package_id": {"pattern": r"^[A-Za-z0-9._-]+$", "max_length": 120},
    "package_name": {"pattern": r"^[A-Za-z0-9._]+$", "max_length": 200},
    "path": {"max_length": 260},
    "plan_guid": {"pattern": r"^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$"},
    "property": {"pattern": r"^[A-Za-z0-9._]+$", "max_length": 100},
    "query": {"max_length": 100},
    "remote_dir": {"pattern": REMOTE, "max_length": 260},
    "remote_file": {"pattern": REMOTE, "max_length": 260},
    "remote_path": {"pattern": REMOTE, "max_length": 260},
    "task_name": {"pattern": r"^[\\A-Za-z0-9 ._-]+$", "max_length": 260},
    "script": {"pattern": r"^[A-Za-z0-9:_.-]+$", "max_length": 80},
    "apk_path": {"pattern": r"(?i)\.apk$", "max_length": 260},
    "local_dir": {"max_length": 260},
    "local_path": {"max_length": 260},
    "variable": {"pattern": r"^[A-Za-z0-9._-]+$", "max_length": 80},
    "port": {"minimum": 1, "maximum": 65535},
    "device_port": {"minimum": 1, "maximum": 65535},
    "host_port": {"minimum": 1, "maximum": 65535},
    "count": {"minimum": 1, "maximum": 1000},
    "lines": {"minimum": 1, "maximum": 1000},
    "max_size": {"minimum": 100, "maximum": 4000},
}
ENUMS = {
    "key": [
        "HOME",
        "BACK",
        "POWER",
        "VOLUME_UP",
        "VOLUME_DOWN",
        "WAKEUP",
        "SLEEP",
        "MENU",
        "ENTER",
        "APP_SWITCH",
    ],
    "level": ["V", "D", "I", "W", "E", "F"],
    "log_name": ["Application", "System"],
}


class _NoAliasDumper(yaml.SafeDumper):
    def ignore_aliases(self, data: Any) -> bool:
        return True


DEFAULT_RE = re.compile(r"\(Default:\s*([^)]+)\)", re.IGNORECASE)


def convert_param(name: str, raw: dict[str, Any]) -> dict[str, Any]:
    description = DEFAULT_RE.sub("", raw.get("description", "")).strip()
    kind = raw.get("type", "string")
    out: dict[str, Any] = {"type": {"path": "string", "enum": "string"}.get(kind, kind)}
    out["description"] = description or name.replace("_", " ").capitalize()
    match = DEFAULT_RE.search(raw.get("description", ""))
    if match:
        text = match.group(1).strip()
        if out["type"] == "boolean":
            out["default"] = text.lower() == "true"
        elif out["type"] == "integer":
            out["default"] = int(text)
        else:
            out["default"] = text
    if name in ENUMS:
        out["enum"] = ENUMS[name]
    out.update(PARAM_RULES.get(name, {}))
    return out


def convert_arg(item: Any, params: dict[str, Any]) -> Any:
    if isinstance(item, dict) and "when" in item:
        return {"when": item["when"].strip("{}"), "args": list(item["args"])}
    if isinstance(item, dict) and "format" in item:
        return item["format"]
    return item


def risk_for(name: str) -> str:
    if name in DESTRUCTIVE:
        return "destructive"
    return "mutating" if name in MUTATING else "read_only"


def humanize(name: str) -> str:
    return name.replace("_", " ")


def convert_tool(raw: dict[str, Any], suite: dict[str, Any]) -> dict[str, Any]:
    name = raw["name"]
    props = raw["parameters"].get("properties") or {}
    required = set(raw["parameters"].get("required") or [])
    params: dict[str, Any] = {}
    for pname, praw in props.items():
        spec = convert_param(pname, praw)
        if pname not in required and "default" not in spec and spec["type"] != "boolean":
            spec["optional"] = True
        params[pname] = spec

    args = [convert_arg(a, params) for a in raw.get("argv") or []]
    if name == "adb_press_key":
        args = ["shell", "input", "keyevent", "KEYCODE_{key}"]
    if name == "adb_tcpip":
        params["port"]["default"] = 5555
        params["port"].pop("optional", None)
        args = ["tcpip", "{port}"]
    if name == "adb_logcat_recent":
        params["lines"]["default"] = 100
        params["level"]["default"] = "W"
        params["lines"].pop("optional", None)
        params["level"].pop("optional", None)
    if name == "wevtutil_recent_events":
        params["count"]["default"] = 20
        params["count"].pop("optional", None)
    for pname, spec in params.items():  # optional params used unconditionally become conditional
        if spec.get("optional"):
            args = [
                {"when": pname, "args": [a]} if isinstance(a, str) and "{" + pname + "}" in a else a
                for a in args
            ]
    description = raw["description"].strip()
    if suite["category"] == "android":
        description = f"Android device (adb): {description}"  # keeps it distinct from PC tools
    tool: dict[str, Any] = {
        "name": name,
        "description": description,
        "risk": risk_for(name),
        "parameters": params,
        "run": {suite["platform"]: {"exe": raw["executable"], "args": args}},
        "examples": [humanize(name), description.split(". ")[0].rstrip(".").lower()]
        + ([f"{humanize(name)} on my android phone"] if suite["category"] == "android" else []),
        "keywords": suite["keywords"],
        "category": suite["category"],
    }
    if not params:
        del tool["parameters"]
    if name in DESTRUCTIVE:
        tool["confirm_message"] = DESTRUCTIVE[name]
    if name in LONG_TIMEOUT:
        tool["timeout"] = LONG_TIMEOUT[name]
    return tool


def main(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for suite_name, suite in SUITES.items():
        data = yaml.safe_load((src / f"{suite_name}.yaml").read_text(encoding="utf-8"))
        tools = [convert_tool(t, suite) for t in data["tools"] if t["name"] not in SKIP_TOOLS]
        pack = {
            "pack": suite_name,
            "version": "1.0.0",
            "description": f"{suite_name} commands (migrated from the v2 prototype).",
            "tools": tools,
        }
        (dst / f"{suite_name}.yaml").write_text(
            yaml.dump(pack, Dumper=_NoAliasDumper, sort_keys=False, allow_unicode=True, width=100),
            encoding="utf-8",
        )
        print(f"{suite_name}: {len(tools)} tools")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
