"""First-run setup: hardware-aware recommendations, a model catalog and the wizard flow."""

from assistant.setup.apply import (
    installed_tags,
    missing_tags,
    needed_tags,
    pull_model,
    write_config,
)
from assistant.setup.catalog import Catalog, ModelEntry, load_catalog
from assistant.setup.choices import (
    SAFETY_PROFILES,
    SetupChoices,
    build_settings,
    minimal_overrides,
)
from assistant.setup.hardware import Hardware, detect_hardware
from assistant.setup.planner import Advice, assess, estimate_memory_gb, recommend, recommend_tier
from assistant.setup.wizard import Option, Prompter, run_wizard, summary_lines

__all__ = [
    "SAFETY_PROFILES",
    "Advice",
    "Catalog",
    "Hardware",
    "ModelEntry",
    "Option",
    "Prompter",
    "SetupChoices",
    "assess",
    "build_settings",
    "detect_hardware",
    "estimate_memory_gb",
    "installed_tags",
    "load_catalog",
    "minimal_overrides",
    "missing_tags",
    "needed_tags",
    "pull_model",
    "recommend",
    "recommend_tier",
    "run_wizard",
    "summary_lines",
    "write_config",
]
