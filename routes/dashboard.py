import os
from flask import render_template
from core import context as ctx


def register_dashboard_routes(app, count_images, dropbox_zip_path):

    @app.route("/dashboard")
    def dashboard():
        tournaments = []

        if os.path.exists(ctx.TOURNAMENT_DIR):
            for d in sorted(os.listdir(ctx.TOURNAMENT_DIR), reverse=True):
                if os.path.isdir(os.path.join(ctx.TOURNAMENT_DIR, d)):
                    tournaments.append(d)

        latest = tournaments[0] if tournaments else None

        stats = {
            "review": 0,
            "best": 0,
            "keep": 0,
            "dropbox_ready": False
        }

        if latest:
            tpath = os.path.join(ctx.TOURNAMENT_DIR, latest)
            stats["review"] = count_images(os.path.join(tpath, "Players", "Unknown"))
            stats["best"] = count_images(os.path.join(tpath, "Best"))
            stats["keep"] = count_images(os.path.join(tpath, "Keep"))
            stats["dropbox_ready"] = os.path.exists(dropbox_zip_path(latest))

        return render_template(
            "dashboard.html",
            tournaments=tournaments,
            latest=latest,
            stats=stats
        )
