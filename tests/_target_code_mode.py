"""Shared explicit opt-in for test modules that run target code through detectors.Sandbox.

detectors.Sandbox refuses runtime runs by default where the governor's full OS sandbox tier is
missing (SEC-07): nothing executes and the run reports ``refused``. A test module whose cases
heal, run the runtime detectors on, or upgrade a target calls ``opt_in_without_full_tier()``
from its ``setUpModule``:

- full tier: nothing changes; every run of target code goes through the OS sandbox;
- GAIE_REQUIRE_FULL_SANDBOX=1 without the full tier: AssertionError, so the isolation job
  still fails instead of proving only the fallback;
- otherwise (for example a GitHub runner without user namespaces): this module opts into the
  audited ``process-only`` mode explicitly, for its own duration only; a module cleanup
  restores the default.

Product behaviour is unchanged: outside tests the default stays ``os`` and a host without the
full tier refuses. This file is not a test module (no ``test`` prefix).
"""

import os
import unittest
from unittest import mock

REQUIRE = "GAIE_REQUIRE_FULL_SANDBOX"


def opt_in_without_full_tier():
    """Opt the calling test module into process-only where the full tier is missing; True when it did."""
    from engineering_os import detectors, governor
    if governor.isolation_probe()["tier"] == "full":
        return False
    if os.environ.get(REQUIRE) == "1":
        raise AssertionError(f"{REQUIRE}=1 but the governor's full sandbox tier is missing")
    patcher = mock.patch.object(detectors, "DEFAULT_ISOLATION", "process-only")
    patcher.start()
    unittest.addModuleCleanup(patcher.stop)
    return True
