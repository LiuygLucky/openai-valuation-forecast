"""Run LIVE research outside Streamlit's rerun-prone script thread."""

import ctypes
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from uuid import uuid4

import yaml

from core.config import ROOT
from core.schemas import CognitiveState
from memory.evidence_store import EvidenceStore


def start_live_job(question, settings, rules):
    run_id = uuid4().hex
    folder = ROOT / "data" / "jobs" / run_id
    folder.mkdir(parents=True, exist_ok=False)
    settings_file, rules_file = folder / "settings.yaml", folder / "rules.yaml"
    settings_file.write_text(
        yaml.safe_dump(settings.model_dump(mode="json"), allow_unicode=True), encoding="utf-8"
    )
    rules_file.write_text(
        yaml.safe_dump(rules.model_dump(mode="json"), allow_unicode=True), encoding="utf-8"
    )
    command = [
        sys.executable,
        str(ROOT / "main.py"),
        "--run-id",
        run_id,
        "--settings",
        str(settings_file),
        "--rules",
        str(rules_file),
        "--question",
        question,
    ]
    with (
        (folder / "stdout.log").open("w", encoding="utf-8") as stdout,
        (folder / "stderr.log").open("w", encoding="utf-8") as stderr,
    ):
        worker = subprocess.Popen(
            command,
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            close_fds=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    metadata = {
        "run_id": run_id,
        "pid": worker.pid,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "question": question,
        "target_date": rules.target_date.isoformat(),
        "database": settings.database,
    }
    (folder / "job.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return run_id


def process_running(pid):
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return None
    kernel = ctypes.windll.kernel32
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    kernel.GetExitCodeProcess.restype = ctypes.c_int
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle.restype = ctypes.c_int
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return None if kernel.GetLastError() == 5 else False
    try:
        code = ctypes.c_ulong()
        return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
    finally:
        kernel.CloseHandle(handle)


def reconcile_jobs(settings):
    store = EvidenceStore(ROOT / settings.database)
    for path in (ROOT / "data" / "jobs").glob("*/job.json"):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
            if job.get("database") != settings.database or process_running(job["pid"]) is not False:
                continue
            run = next((s for s in store.runs("live") if s.run_id == job["run_id"]), None)
            if run is None:
                run = CognitiveState(
                    run_id=job["run_id"],
                    question=job["question"],
                    as_of=datetime.fromisoformat(job["started_at"]),
                    target_date=datetime.fromisoformat(job["target_date"]),
                    mode="live",
                )
            if run.status == "running":
                run.status = "failed"
                run.trace.append("Failed")
                run.warnings.append(
                    "后台任务进程已退出，未到达完成节点；请查看对应 job 的 stderr.log。"
                )
                store.snapshot(run, "Failed")
        except (KeyError, ValueError, OSError):
            continue
