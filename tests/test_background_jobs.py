from datetime import datetime, timezone

from app import jobs
from core.config import load_config
from core.schemas import CognitiveState
from memory.evidence_store import EvidenceStore


def test_live_worker_survives_dashboard_rerun_and_orphan_is_finalized(tmp_path, monkeypatch):
    settings, rules = load_config()
    settings.database = str(tmp_path / "runs.sqlite")
    monkeypatch.setattr(jobs, "ROOT", tmp_path)
    launched = []

    class Worker:
        pid = 987654

    def launch(command, **kwargs):
        launched.append((command, kwargs))
        return Worker()

    monkeypatch.setattr(jobs.subprocess, "Popen", launch)
    run_id = jobs.start_live_job("OpenAI valuation", settings, rules)
    assert launched[0][0][1].endswith("main.py")
    assert launched[0][0][launched[0][0].index("--run-id") + 1] == run_id
    assert launched[0][1]["stdin"] == jobs.subprocess.DEVNULL
    assert (tmp_path / "data" / "jobs" / run_id / "job.json").is_file()

    state = CognitiveState(
        run_id=run_id,
        question="OpenAI valuation",
        as_of=datetime(2026, 11, 3, tzinfo=timezone.utc),
        target_date=rules.target_date,
        mode="live",
    )
    EvidenceStore(settings.database).snapshot(state, "Queued")
    monkeypatch.setattr(jobs, "process_running", lambda pid: True)
    jobs.reconcile_jobs(settings)
    assert EvidenceStore(settings.database).runs("live")[0].status == "running"
    monkeypatch.setattr(jobs, "process_running", lambda pid: False)
    jobs.reconcile_jobs(settings)
    assert EvidenceStore(settings.database).runs("live")[0].status == "failed"
