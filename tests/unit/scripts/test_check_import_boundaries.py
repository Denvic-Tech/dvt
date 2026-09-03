import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = REPO_ROOT / "scripts" / ".pre_commit" / "check_import_boundaries.py"


def load_module():
    spec = importlib.util.spec_from_file_location("check_import_boundaries", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_services_rule_allows_import_from_own_service() -> None:
    module = load_module()

    reason = module._check_import(
        category="services",
        service_name="orchestrator",
        rel_path=Path("services/orchestrator/service.py"),
        top_level="services",
        parts=["services", "orchestrator", "service"],
    )

    assert reason is None


def test_services_rule_rejects_import_from_other_service() -> None:
    module = load_module()

    reason = module._check_import(
        category="services",
        service_name="orchestrator",
        rel_path=Path("services/orchestrator/service.py"),
        top_level="services",
        parts=["services", "gateway", "routes", "impl", "db_connection"],
    )

    assert reason == module.RULES["services"]["cross_service_error"]


def test_services_rule_allows_shared_src_import() -> None:
    module = load_module()

    reason = module._check_import(
        category="services",
        service_name="orchestrator",
        rel_path=Path("services/orchestrator/service.py"),
        top_level="src",
        parts=["src", "modules", "task_execution"],
    )

    assert reason is None
