from flask import jsonify
from core import context as ctx
from core.job_store import get_job, set_job
from core.runpod_client import get_status, enabled as runpod_enabled
from core.dropbox_transport import download_file, unzip_file
import os


def register_api_routes(app):
    @app.route("/health")
    def health():
        return jsonify({
            "status": "ok",
            "processor_available": ctx.PROCESSOR_AVAILABLE,
            "processor_error": ctx.PROCESSOR_ERROR,
            "runpod_enabled": runpod_enabled()
        })

    @app.route("/api/status/<job_name>")
    def api_status(job_name):
        status = get_job(job_name, {
            "done": 0,
            "total": 0,
            "percent": 0,
            "message": "Waiting...",
            "complete": False,
            "error": ""
        })

        if (
            runpod_enabled()
            and status.get("runpod_job_id")
            and not status.get("complete")
        ):
            try:
                rp = get_status(status["runpod_job_id"])
                state = rp.get("status", "").upper()

                if state in ("IN_QUEUE", "QUEUED"):
                    status["message"] = "Queued on RunPod"

                elif state in ("IN_PROGRESS", "RUNNING"):
                    status["message"] = "Processing on RunPod..."
                    status["percent"] = max(status.get("percent", 0), 10)

                elif state == "COMPLETED":
                    status["message"] = "RunPod complete, downloading results..."
                    status["percent"] = 90

                    if "output" in rp:
                        status["runpod_output"] = rp["output"]

                    output = rp.get("output", {}) or {}
                    result_zip_dropbox_path = output.get("output_zip_dropbox_path")

                    if result_zip_dropbox_path:
                        transport_dir = os.path.join(ctx.BASE_DIR, "DropboxTransport")
                        os.makedirs(transport_dir, exist_ok=True)

                        result_zip_local = os.path.join(
                            transport_dir,
                            f"{job_name}_results.zip"
                        )

                        download_file(result_zip_dropbox_path, result_zip_local)

                        output_folder = os.path.join(ctx.TOURNAMENT_DIR, job_name)
                        unzip_file(result_zip_local, output_folder)

                        status["done"] = status.get("total", 0)
                        status["percent"] = 100
                        status["message"] = "Processing complete"
                        status["complete"] = True
                        status["results_downloaded"] = True
                        status["output_folder"] = output_folder
                    else:
                        status["message"] = "RunPod complete, but no results ZIP path was returned"
                        status["percent"] = 95
                        status["complete"] = False

                elif state in ("FAILED", "CANCELLED", "TIMED_OUT"):
                    status["complete"] = True
                    status["percent"] = 100
                    status["message"] = "RunPod job failed"
                    status["error"] = str(rp.get("error", rp))

                else:
                    status["message"] = f"RunPod status: {state or 'unknown'}"

                set_job(job_name, status)

            except Exception as e:
                status["message"] = "Could not check RunPod status"
                status["error"] = str(e)
                set_job(job_name, status)

        return jsonify(status)

    @app.route("/api/debug/storage")
    def debug_storage():
        import glob

        def latest_dirs(path):
            if not path or not os.path.exists(path):
                return []
            items = []
            for p in glob.glob(os.path.join(path, "*")):
                items.append({
                    "name": os.path.basename(p),
                    "is_dir": os.path.isdir(p),
                    "mtime": os.path.getmtime(p)
                })
            return sorted(items, key=lambda x: x["mtime"], reverse=True)[:20]

        def latest_files(path):
            if not path or not os.path.exists(path):
                return []
            items = []
            for p in glob.glob(os.path.join(path, "*")):
                if os.path.isfile(p):
                    items.append({
                        "name": os.path.basename(p),
                        "size": os.path.getsize(p),
                        "mtime": os.path.getmtime(p)
                    })
            return sorted(items, key=lambda x: x["mtime"], reverse=True)[:20]

        return jsonify({
            "tournament_dir": ctx.TOURNAMENT_DIR,
            "latest_tournaments": latest_dirs(ctx.TOURNAMENT_DIR),
            "latest_transport_files": latest_files(os.path.join(ctx.BASE_DIR, "DropboxTransport")),
            "latest_uploads": latest_dirs(ctx.UPLOAD_DIR),
        })

    @app.route("/api/debug/jobs")
    def debug_jobs():
        from core.job_store import _read_all
        return jsonify(_read_all())
