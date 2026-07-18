"""Global pytest safety policy for VenAgent.

Every test run prints the network-guard state in the pytest header. The guard
is enabled by default so a local ``config.local.yaml`` cannot accidentally
spend money through a real LLM, embedding, search, or other HTTP service.
"""

from network_guard import install_network_guard, network_tests_allowed, NETWORK_BYPASS_ENV


def pytest_configure(config):
    install_network_guard()


def pytest_report_header(config):
    if network_tests_allowed():
        return (
            "VenAgent test network guard: DISABLED "
            f"({NETWORK_BYPASS_ENV}=1)"
        )
    return (
        "VenAgent test network guard: ENABLED "
        f"(real HTTP blocked; set {NETWORK_BYPASS_ENV}=1 only for approved network tests)"
    )
