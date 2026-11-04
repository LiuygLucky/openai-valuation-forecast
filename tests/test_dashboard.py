from pathlib import Path

import yaml
from streamlit.testing.v1 import AppTest

from core.config import load_config


def test_dashboard_initial_and_demo_flow(tmp_path, monkeypatch):
    settings, _ = load_config()
    settings.database = str(tmp_path / "dashboard.sqlite")
    settings.output_dir = str(tmp_path / "reports")
    config_path = tmp_path / "settings.yaml"
    config_path.write_text(yaml.safe_dump(settings.model_dump()), encoding="utf-8")
    monkeypatch.setenv("FORECAST_SETTINGS", str(config_path))
    app = AppTest.from_file(
        str(Path(__file__).resolve().parents[1] / "app/streamlit_app.py"), default_timeout=30
    ).run()
    assert not app.exception
    app.button[0].click().run(timeout=30)
    assert not app.exception
    assert app.session_state["forecast_state"].status == "completed"
    for page in ["认知研究过程", "预测结果", "预测历史"]:
        app.sidebar.radio[0].set_value(page).run()
        assert not app.exception
