import json
import os
from threading import Lock

LOCK = Lock()
JOB_STATUS_FILE = os.environ.get("JOB_STATUS_FILE", "/tmp/diamondvision_job_status.json")


def _read_all():
    if not os.path.exists(JOB_STATUS_FILE):
        return {}
    try:
        with open(JOB_STATUS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _write_all(data):
    os.makedirs(os.path.dirname(JOB_STATUS_FILE), exist_ok=True)
    with open(JOB_STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f)


def set_job(job_name, status):
    with LOCK:
        data = _read_all()
        data[job_name] = status
        _write_all(data)


def get_job(job_name, default=None):
    with LOCK:
        data = _read_all()
        return data.get(job_name, default)


def update_job(job_name, updates):
    with LOCK:
        data = _read_all()
        status = data.get(job_name, {})
        status.update(updates)
        data[job_name] = status
        _write_all(data)
        return status
