from flask import jsonify
from core import context as ctx
from core.job_store import get_job, set_job
from core.runpod_client import get_status, enabled as runpod_enabled
from core.dropbox_transport import download_file, unzip_file

import os
import glob
import csv
import json


IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png")
RAW_EXTENSIONS = (".nef", ".cr2", ".cr3", ".arw", ".dng")


def count_images_recursive(path):
    if not os.path.exists(path):
        return 0

    total = 0

    for root, _, files in os.walk(path):
        total += len([
            f for f in files
            if f.lower().endswith(IMAGE_EXTENSIONS)
        ])

    return total


def recover_completed_job(job_name, status):
    output_folder = os.path.join(ctx.TOURNAMENT_DIR, job_name)
    transport_dir = os.path.join(ctx.BASE_DIR, "DropboxTransport")
    result_zip_local = os.path.join(transport_dir, f"{job_name}_results.zip")

    if os.path.exists(result_zip_local):
        os.makedirs(output_folder, exist_ok=True)
        unzip_file(result_zip_local, output_folder)

    image_count = count_images_recursive(output_folder)

    if image_count > 0:
        status["done"] = image_count
        status["total"] = max(status.get("total", 0), image_count)
        status["percent"] = 100
        status["message"] = "Processing complete"
        status["complete"] = True
        status["results_downloaded"] = True
        status["output_folder"] = output_folder
        set_job(job_name, status)

    return status


def list_tree(root):
    files = []
    counts = {}

    if not os.path.exists(root):
        return files, counts

    for current_root, _, names in os.walk(root):
        for name in names:
            full = os.path.join(current_root, name)
            rel = os.path.relpath(full, root).replace("\\", "/")

            ext = os.path.splitext(name)[1].lower() or "no_ext"
            counts[ext] = counts.get(ext, 0) + 1

            files.append(rel)

    return sorted(files), counts


def read_report(root):
    report_path = os.path.join(root, "Reports", "diamondvision_report.csv")

    if not os.path.exists(report_path):
        return []

    try:
        with open(report_path, newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))
    except Exception as e:
        return [{"error": f"Could not read report: {e}"}]


def read_metadata(root):
    metadata_path = os.path.join(root, "Reports", "metadata.json")

    if not os.path.exists(metadata_path):
        return {}

    try:
        with open(metadata_path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as e:
        return {"error": f"Could not read metadata: {e}"}


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

        status = recover_completed_job(job_name, status)

        if status.get("complete"):
            return jsonify(status)

        if runpod_enabled() and status.get("runpod_job_id"):
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

                        image_count = count_images_recursive(output_folder)

                        status["done"] = image_count
                        status["total"] = max(status.get("total", 0), image_count)
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
            "upload_dir": ctx.UPLOAD_DIR,
            "latest_tournaments": latest_dirs(ctx.TOURNAMENT_DIR),
            "latest_transport_files": latest_files(os.path.join(ctx.BASE_DIR, "DropboxTransport")),
            "latest_uploads": latest_dirs(ctx.UPLOAD_DIR),
        })

    @app.route("/api/debug/tournament/<job_name>")
    def debug_tournament(job_name):
        root = os.path.join(ctx.TOURNAMENT_DIR, job_name)

        files, extension_counts = list_tree(root)

        originals = [
            f for f in files
            if f.startswith("Originals/")
        ]

        raw_originals = [
            f for f in originals
            if f.lower().endswith(RAW_EXTENSIONS)
        ]

        display_outputs = [
            f for f in files
            if f.lower().endswith(IMAGE_EXTENSIONS)
        ]

        raw_anywhere = [
            f for f in files
            if f.lower().endswith(RAW_EXTENSIONS)
        ]

        report_rows = read_report(root)
        metadata = read_metadata(root)

        missing_sorted_paths = []

        for row in report_rows:
            sorted_path = row.get("Sorted Path", "")

            if sorted_path and not os.path.exists(sorted_path):
                missing_sorted_paths.append({
                    "original": row.get("Original File", ""),
                    "sorted_path": sorted_path
                })

        return jsonify({
            "job_name": job_name,
            "root": root,
            "exists": os.path.exists(root),
            "total_files": len(files),
            "extension_counts": extension_counts,
            "originals": originals,
            "raw_originals": raw_originals,
            "raw_anywhere": raw_anywhere,
            "display_outputs": display_outputs,
            "display_output_count": len(display_outputs),
            "report_row_count": len(report_rows),
            "report_rows": report_rows,
            "missing_sorted_paths": missing_sorted_paths,
            "metadata_summary": metadata.get("summary", {}) if isinstance(metadata, dict) else {},
            "metadata_image_count": len(metadata.get("images", [])) if isinstance(metadata, dict) else 0,
            "metadata": metadata
        })