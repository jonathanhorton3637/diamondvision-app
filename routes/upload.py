import os
import threading
from datetime import datetime
from flask import render_template, request, redirect, url_for
from werkzeug.utils import secure_filename

from core import context as ctx


def register_upload_routes(app, safe_name, process_mobile_job):

    def update_job_status(job_name, done, total, message):
        percent = 0
        if total > 0:
            percent = int((done / total) * 100)

        ctx.JOB_STATUS[job_name] = {
            "done": done,
            "total": total,
            "percent": percent,
            "message": message,
            "complete": done >= total and total > 0,
            "error": ""
        }

    def run_processing_job(job_name, upload_path, output_path, job_config):
        try:
            def progress(done, total, message):
                update_job_status(job_name, done, total, message)

            summary = process_mobile_job(
                upload_path,
                output_path,
                job_config,
                progress_callback=progress
            )

            ctx.JOB_STATUS[job_name]["summary"] = summary
            ctx.JOB_STATUS[job_name]["complete"] = True
            ctx.JOB_STATUS[job_name]["percent"] = 100
            ctx.JOB_STATUS[job_name]["message"] = "Processing complete"

        except Exception as e:
            ctx.JOB_STATUS[job_name] = {
                "done": 0,
                "total": 0,
                "percent": 0,
                "message": "Error",
                "complete": True,
                "error": str(e)
            }

    @app.route("/new", methods=["GET", "POST"])
    def new_job():
        if request.method == "POST":
            tournament = safe_name(request.form.get("tournament", "Tournament"))
            job_mode = request.form.get("job_mode", "single")

            team1 = safe_name(request.form.get("team", "Team"))
            team1_color = request.form.get("team1_color", "")
            roster1 = request.form.get("roster", "")

            team2 = safe_name(request.form.get("team2", "Opponent"))
            team2_color = request.form.get("team2_color", "")
            roster2 = request.form.get("roster2", "")

            date = datetime.now().strftime("%Y-%m-%d-%H%M%S")

            if job_mode == "two_team":
                job_name = f"{date}_{tournament}_TwoTeam"
            else:
                job_name = f"{date}_{tournament}_{team1}"

            upload_path = os.path.join(ctx.UPLOAD_DIR, job_name)
            output_path = os.path.join(ctx.TOURNAMENT_DIR, job_name)

            os.makedirs(upload_path, exist_ok=True)
            os.makedirs(output_path, exist_ok=True)
            os.makedirs(os.path.join(output_path, "Favorites"), exist_ok=True)

            job_config = {
                "mode": job_mode,
                "team1": team1,
                "team1_color": team1_color,
                "roster1": roster1,
                "team2": team2,
                "team2_color": team2_color,
                "roster2": roster2
            }

            with open(os.path.join(output_path, "job_config.txt"), "w", encoding="utf-8") as f:
                f.write(str(job_config))

            with open(os.path.join(output_path, "mobile_roster.txt"), "w", encoding="utf-8") as f:
                f.write(roster1)

            if job_mode == "two_team":
                with open(os.path.join(output_path, "mobile_roster_team2.txt"), "w", encoding="utf-8") as f:
                    f.write(roster2)

            files = request.files.getlist("photos")
            saved_count = 0

            for file in files:
                if not file or not file.filename:
                    continue

                filename = secure_filename(file.filename)
                ext = os.path.splitext(filename)[1].lower()

                if ext not in ctx.UPLOAD_EXTENSIONS:
                    continue

                destination = os.path.join(upload_path, filename)

                if os.path.exists(destination):
                    name, extension = os.path.splitext(filename)
                    stamp = datetime.now().strftime("%H%M%S%f")
                    filename = f"{name}_{stamp}{extension}"
                    destination = os.path.join(upload_path, filename)

                file.save(destination)
                saved_count += 1

            if saved_count == 0:
                return "No supported photos uploaded. Use JPG, JPEG, PNG, or NEF.", 400

            if ctx.PROCESSOR_AVAILABLE:
                ctx.JOB_STATUS[job_name] = {
                    "done": 0,
                    "total": saved_count,
                    "percent": 0,
                    "message": "Queued",
                    "complete": False,
                    "error": ""
                }

                thread = threading.Thread(
                    target=run_processing_job,
                    args=(job_name, upload_path, output_path, job_config),
                    daemon=True
                )
                thread.start()

                return redirect(url_for("processing", job_name=job_name))

            return redirect(url_for("tournament", name=job_name))

        return render_template(
            "job.html",
            processor_available=ctx.PROCESSOR_AVAILABLE
        )

    @app.route("/processing/<job_name>")
    def processing(job_name):
        return render_template(
            "processing.html",
            job_name=job_name
        )
