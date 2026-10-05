# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Fixtures for charm tests."""

import pytest

_ABORTED_MODULES: set[str] = set()


def _item_module_name(item: pytest.Item) -> str | None:
    """Return the test module name for a pytest item, if available.

    Args:
        item: test item.

    Returns:
        The module ``__name__``, or None if the item has no module.
    """
    module = getattr(item, "module", None)
    return getattr(module, "__name__", None)


def pytest_addoption(parser: pytest.Parser):
    """Parse additional pytest options.

    Args:
        parser: pytest command line parser.
    """
    # The prebuilt charm file.
    parser.addoption("--charm-file", action="append", default=[])


def pytest_configure(config: pytest.Config):
    """Register markers previously provided by pytest-operator.

    Args:
        config: pytest config object.
    """
    config.addinivalue_line(
        "markers",
        "abort_on_fail: xfail remaining tests in the module if a marked test fails",
    )


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo):
    """Record abort_on_fail after a marked test fails or errors.

    Args:
        item: test item.
        call: test call phase.
    """
    outcome = yield
    report = outcome.get_result()
    module_name = _item_module_name(item)
    if report.failed and item.get_closest_marker("abort_on_fail") and module_name:
        _ABORTED_MODULES.add(module_name)


def pytest_runtest_setup(item: pytest.Item):
    """Xfail remaining tests in a module after abort_on_fail.

    Args:
        item: test item.
    """
    module_name = _item_module_name(item)
    if module_name and module_name in _ABORTED_MODULES:
        pytest.xfail("previous abort_on_fail test failed")
