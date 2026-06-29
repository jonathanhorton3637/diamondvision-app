import os
import zipfile
from datetime import datetime
from flask import render_template, redirect, url_for
from core import context as ctx


def register_admin_routes(app):

    @app.route("/admin/backup", methods=["POST"])
    def admin_backup():
        backup_dir = os.path.join(ctx.BASE_DIR, "Backups")
        os.makedirs(backup_dir, exist_ok=True)

        stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
        zip_name = f"DiamondVision_Backup_{stamp}.zip"
        zip_path = os.path.join(backup_dir, zip_name)

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for root, dirs, files in os.walk(ctx.BASE_DIR):
                dirs[:] = [
                    d for d in dirs
                    if d not in ("venv", ".git", "Backups", "__pycache__")
                ]

                for file in files:
                    if file.endswith(".zip") or file == "diamondvision.log":
                        continue

                    full = os.path.join(root, file)
                    rel = os.path.relpath(full, ctx.BASE_DIR)
                    z.write(full, rel)

        return redirect(url_for("admin"))

    @app.route("/admin")
    def admin():
        tournaments = []

        if os.path.exists(ctx.TOURNAMENT_DIR):
            for d in sorted(os.listdir(ctx.TOURNAMENT_DIR), reverse=True):
                if os.path.isdir(os.path.join(ctx.TOURNAMENT_DIR, d)):
                    tournaments.append(d)

        return render_template(
            "admin.html",
            tournaments=tournaments,
            processor_available=ctx.PROCESSOR_AVAILABLE,
            processor_error=ctx.PROCESSOR_ERROR
        )
