import os
import requests

try:
    from config import RUNPOD_API_KEY, RUNPOD_ENDPOINT_ID
except Exception:
    RUNPOD_API_KEY = ""
    RUNPOD_ENDPOINT_ID = ""

RUNPOD_API_KEY = os.environ.get("RUNPOD_API_KEY", RUNPOD_API_KEY).strip()
RUNPOD_ENDPOINT_ID = os.environ.get("RUNPOD_ENDPOINT_ID", RUNPOD_ENDPOINT_ID).strip()


def base_url():
    return f"https://api.runpod.ai/v2/{RUNPOD_ENDPOINT_ID}"


def enabled():
    return bool(RUNPOD_API_KEY and RUNPOD_ENDPOINT_ID)


def submit_job(payload):
    if not enabled():
        raise RuntimeError("RunPod API key or endpoint ID is missing")

    response = requests.post(
        f"{base_url()}/run",
        headers={"Authorization": f"Bearer {RUNPOD_API_KEY}", "Content-Type": "application/json"},
        json={"input": payload},
        timeout=60
    )
    response.raise_for_status()
    return response.json()


def get_status(job_id):
    if not enabled():
        raise RuntimeError("RunPod API key or endpoint ID is missing")

    response = requests.get(
        f"{base_url()}/status/{job_id}",
        headers={"Authorization": f"Bearer {RUNPOD_API_KEY}"},
        timeout=60
    )
    response.raise_for_status()
    return response.json()
