"""Smoke tests for the standalone TUI package."""

import pkgutil

import phyagentos_tui
from phyagentos_tui.app import PhyAgentOSApp, run_tui


def test_public_entrypoints_are_importable() -> None:
    assert phyagentos_tui.__version__
    assert callable(run_tui)
    assert PhyAgentOSApp.CSS_PATH == "styles.tcss"


def test_demo_modules_are_not_packaged() -> None:
    module_names = {module.name for module in pkgutil.iter_modules(phyagentos_tui.__path__)}
    assert not any(name.startswith("demo") for name in module_names)
