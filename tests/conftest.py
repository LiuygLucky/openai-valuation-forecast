from pathlib import Path
from uuid import uuid4


def pytest_configure(config):
    # Avoid shared Windows TEMP ACL conflicts; each test run owns a new workspace directory.
    if config.option.basetemp is None:
        root = Path(__file__).resolve().parents[1] / "data" / "test_tmp"
        root.mkdir(parents=True, exist_ok=True)
        config.option.basetemp = str(root / uuid4().hex)
