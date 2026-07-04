import os
import zipfile
from flask import redirect, url_for, abort, send_from_directory
from core import context as ctx


def register_dropbox_routes(app, safe_name, dropbox_zip_path, dropbox_token, dropbox_parent_folder):

    @app.route("/export-dropbox/<tournament>", methods=["POST"])
    def export_dropbox(tournament):
        tournament_path = os.path.join(ctx.TOURNAMENT_DIR, tournament)

        if not os.path.exists(tournament_path):
            abort(404)

        zip_path = dropbox_zip_path(tournament)

        if os.path.exists(zip_path):
            os.remove(zip_path)

        export_name = safe_name(tournament) + "_ParentGallery"

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            index_rows = []

            teams_path = os.path.join(tournament_path, "Teams")
            players_path = os.path.join(tournament_path, "Players")

            if os.path.exists(teams_path):
                for team in sorted(os.listdir(teams_path)):
                    team_players = os.path.join(teams_path, team, "Players")

                    if not os.path.exists(team_players):
                        continue

                    for player in sorted(os.listdir(team_players)):
                        player_path = os.path.join(team_players, player)

                        if not os.path.isdir(player_path):
                            continue

                        photo_count = 0

                        for file in sorted(os.listdir(player_path)):
                            if file.lower().endswith(ctx.IMAGE_EXTENSIONS):
                                full = os.path.join(player_path, file)
                                rel = os.path.join(export_name, team, player, file)
                                z.write(full, rel)
                                photo_count += 1

                        if photo_count > 0:
                            index_rows.append((team, player, photo_count, f"{team}/{player}/"))

            elif os.path.exists(players_path):
                for player in sorted(os.listdir(players_path)):
                    player_path = os.path.join(players_path, player)

                    if not os.path.isdir(player_path):
                        continue

                    photo_count = 0

                    for file in sorted(os.listdir(player_path)):
                        if file.lower().endswith(ctx.IMAGE_EXTENSIONS):
                            full = os.path.join(player_path, file)
                            rel = os.path.join(export_name, "Players", player, file)
                            z.write(full, rel)
                            photo_count += 1

                    if photo_count > 0:
                        index_rows.append(("Players", player, photo_count, f"Players/{player}/"))

            index_html = """<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DiamondVision Parent Gallery</title>
<style>
body{font-family:Arial,sans-serif;background:#f7f7fb;margin:0;padding:20px;color:#111}
h1{margin-bottom:6px}
.card{display:block;background:white;margin:12px 0;padding:16px;border-radius:18px;text-decoration:none;color:#111;box-shadow:0 6px 18px rgba(0,0,0,.08)}
.small{color:#666}
</style>
</head>
<body>
<h1>DiamondVision Parent Gallery</h1>
<p class="small">Tap a player folder to view photos.</p>
"""

            for team, player, count, link in index_rows:
                index_html += f'<a class="card" href="{link}"><strong>{player.replace("_"," ")}</strong><br><span class="small">{team.replace("_"," ")} · {count} photos</span></a>\n'

            index_html += "</body></html>"

            z.writestr(os.path.join(export_name, "index.html"), index_html)

        return redirect(url_for("tournament", name=tournament))

    @app.route("/sync-dropbox/<tournament>", methods=["POST"])
    def sync_dropbox(tournament):
        if not dropbox_token:
            return "Dropbox token missing. Add it to config.py.", 400

        zip_path = dropbox_zip_path(tournament)

        if not os.path.exists(zip_path):
            return redirect(url_for("export_dropbox", tournament=tournament))

        try:
            import dropbox

            dbx = dropbox.Dropbox(dropbox_token.strip())

            dropbox_path = (
                dropbox_parent_folder.rstrip("/")
                + "/"
                + safe_name(tournament)
                + "/"
                + os.path.basename(zip_path)
            )

            with open(zip_path, "rb") as f:
                dbx.files_upload(
                    f.read(),
                    dropbox_path,
                    mode=dropbox.files.WriteMode.overwrite
                )

            return redirect(url_for("admin"))

        except Exception as e:
            return f"Dropbox sync failed: {e}", 500

    @app.route("/download-dropbox/<tournament>")
    def download_dropbox(tournament):
        zip_path = dropbox_zip_path(tournament)

        if not os.path.exists(zip_path):
            abort(404)

        filename = os.path.basename(zip_path)

        return send_from_directory(
            ctx.DROPBOX_EXPORT_DIR,
            filename,
            as_attachment=True
        )
