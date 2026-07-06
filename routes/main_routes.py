import os
import csv
import shutil
import threading
import zipfile
import tempfile
from datetime import datetime

from flask import render_template, request, redirect, url_for, abort, send_from_directory
from werkzeug.utils import secure_filename
from core import context as ctx


try:
    import dropbox
except Exception:
    dropbox = None


try:
    from config import DROPBOX_ACCESS_TOKEN, DROPBOX_PARENT_FOLDER
except Exception:
    DROPBOX_ACCESS_TOKEN = ""
    DROPBOX_PARENT_FOLDER = "/DiamondVision"


def log(message):
    print(f"[DiamondVision Recovery] {message}", flush=True)


def safe_join(base, *paths):
    base_abs = os.path.abspath(base)
    final = os.path.abspath(os.path.join(base_abs, *paths))

    if not final.startswith(base_abs):
        raise ValueError("Unsafe zip path detected")

    return final


def has_tournament_content(tournament):
    path = os.path.join(ctx.TOURNAMENT_DIR, tournament)

    if not os.path.exists(path):
        return False

    required = ["Reports", "Best", "Keep", "Reject", "Duplicates", "BestOfTournament", "Players"]

    for folder in required:
        if os.path.exists(os.path.join(path, folder)):
            return True

    for root, _, files in os.walk(path):
        for file in files:
            if file.lower().endswith(ctx.IMAGE_EXTENSIONS):
                return True

    return False


def extract_results_zip(zip_path, tournament):
    tournament_path = os.path.join(ctx.TOURNAMENT_DIR, tournament)
    os.makedirs(tournament_path, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as z:
        members = z.namelist()

        for member in members:
            if not member or member.endswith("/"):
                continue

            normalized = member.replace("\\", "/").lstrip("/")

            parts = normalized.split("/")

            if len(parts) > 1 and parts[0] in ("output", "results", tournament):
                normalized = "/".join(parts[1:])

            if not normalized:
                continue

            dest = safe_join(tournament_path, normalized)
            os.makedirs(os.path.dirname(dest), exist_ok=True)

            with z.open(member) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)

    os.makedirs(os.path.join(tournament_path, "Favorites"), exist_ok=True)

    log(f"Extracted results zip into Tournament/{tournament}")

    return True


def local_zip_candidates(tournament, dropbox_zip_path):
    candidates = []

    try:
        candidates.append(dropbox_zip_path(tournament))
    except Exception:
        pass

    safe = tournament.replace("/", "_").replace("\\", "_")

    candidates.extend([
        os.path.join(ctx.DROPBOX_EXPORT_DIR, f"{safe}.zip"),
        os.path.join(ctx.DROPBOX_EXPORT_DIR, f"{safe}_results.zip"),
        os.path.join(ctx.DROPBOX_EXPORT_DIR, f"{safe}_Dropbox_Player_Gallery.zip"),
    ])

    seen = []
    for path in candidates:
        if path and path not in seen:
            seen.append(path)

    return seen


def dropbox_path_candidates(tournament):
    safe = tournament.replace("/", "_").replace("\\", "_")
    parent = DROPBOX_PARENT_FOLDER or "/DiamondVision"

    if not parent.startswith("/"):
        parent = "/" + parent

    return [
        f"{parent}/{tournament}/results.zip",
        f"{parent}/{safe}/results.zip",
        f"{parent}/{safe}_results.zip",
        f"{parent}/{safe}.zip",
        f"{parent}/{safe}_Dropbox_Player_Gallery.zip",
        f"{parent}/results/{safe}.zip",
        f"{parent}/results/{safe}_results.zip",
        f"{parent}/outputs/{safe}.zip",
        f"{parent}/outputs/{safe}_results.zip",
    ]


def download_dropbox_zip(tournament):
    if dropbox is None:
        log("Dropbox SDK is not available.")
        return None

    if not DROPBOX_ACCESS_TOKEN:
        log("DROPBOX_ACCESS_TOKEN is missing.")
        return None

    dbx = dropbox.Dropbox(DROPBOX_ACCESS_TOKEN.strip())

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    tmp.close()

    for path in dropbox_path_candidates(tournament):
        try:
            log(f"Trying Dropbox recovery path: {path}")
            _, res = dbx.files_download(path)

            with open(tmp.name, "wb") as f:
                f.write(res.content)

            log(f"Downloaded recovery zip from Dropbox: {path}")
            return tmp.name

        except Exception as e:
            log(f"Dropbox path failed: {path} | {e}")

    try:
        os.remove(tmp.name)
    except Exception:
        pass

    return None


def recover_tournament(tournament, dropbox_zip_path):
    if has_tournament_content(tournament):
        return True

    log(f"Local tournament missing or empty: {tournament}")

    for zip_path in local_zip_candidates(tournament, dropbox_zip_path):
        if os.path.exists(zip_path):
            try:
                log(f"Recovering from local zip: {zip_path}")
                extract_results_zip(zip_path, tournament)
                return has_tournament_content(tournament)
            except Exception as e:
                log(f"Local zip recovery failed: {e}")

    downloaded = download_dropbox_zip(tournament)

    if downloaded:
        try:
            extract_results_zip(downloaded, tournament)
            return has_tournament_content(tournament)
        except Exception as e:
            log(f"Dropbox recovery extraction failed: {e}")
        finally:
            try:
                os.remove(downloaded)
            except Exception:
                pass

    log(f"Recovery failed for tournament: {tournament}")
    return False


def register_main_routes(
    app,
    safe_name,
    build_tournament_info,
    build_cards,
    first_image,
    count_images,
    copy_unique,
    dropbox_zip_path,
    process_mobile_job
):

    @app.route("/")
    def index():
        return redirect(url_for("dashboard"))

    @app.route("/tournaments")
    def tournaments_page():
        tournaments = []

        if os.path.exists(ctx.TOURNAMENT_DIR):
            for d in sorted(os.listdir(ctx.TOURNAMENT_DIR), reverse=True):
                path = os.path.join(ctx.TOURNAMENT_DIR, d)
                if os.path.isdir(path) and d.lower() not in ("input", "output", "__pycache__"):
                    tournaments.append(build_tournament_info(d))

        return render_template(
            "index.html",
            tournaments=tournaments,
            processor_available=ctx.PROCESSOR_AVAILABLE
        )

    @app.route("/tournament/<name>")
    def tournament(name):
        if not recover_tournament(name, dropbox_zip_path):
            abort(404)

        path = os.path.join(ctx.TOURNAMENT_DIR, name)
        os.makedirs(os.path.join(path, "Favorites"), exist_ok=True)

        return render_template(
            "tournament.html",
            tournament=name,
            cards=build_cards(name),
            export_ready=os.path.exists(dropbox_zip_path(name))
        )

    @app.route("/gallery/<tournament>/<path:folder>")
    def gallery(tournament, folder):
        if not recover_tournament(tournament, dropbox_zip_path):
            abort(404)

        folder_path = os.path.join(ctx.TOURNAMENT_DIR, tournament, folder)

        if not os.path.exists(folder_path):
            abort(404)

        subfolders = []
        images = []

        for item in sorted(os.listdir(folder_path)):
            full = os.path.join(folder_path, item)

            if os.path.isdir(full):
                subfolders.append({
                    "name": item,
                    "count": count_images(full),
                    "preview": first_image(full),
                    "url": f"/gallery/{tournament}/{folder}/{item}"
                })

            elif item.lower().endswith(ctx.IMAGE_EXTENSIONS):
                images.append(item)

        return render_template(
            "gallery.html",
            tournament=tournament,
            folder=folder,
            subfolders=subfolders,
            images=images
        )

    @app.route("/photo/<tournament>/<path:folder>")
    def photo_view(tournament, folder):
        if not recover_tournament(tournament, dropbox_zip_path):
            abort(404)

        filename = request.args.get("file")
        folder_path = os.path.join(ctx.TOURNAMENT_DIR, tournament, folder)

        if not os.path.exists(folder_path):
            abort(404)

        images = [
            f for f in sorted(os.listdir(folder_path))
            if f.lower().endswith(ctx.IMAGE_EXTENSIONS)
        ]

        if not filename or filename not in images:
            abort(404)

        i = images.index(filename)
        fav = os.path.join(ctx.TOURNAMENT_DIR, tournament, "Favorites", filename)

        return render_template(
            "photo.html",
            tournament=tournament,
            folder=folder,
            filename=filename,
            index=i,
            total=len(images),
            prev_file=images[i - 1] if i > 0 else None,
            next_file=images[i + 1] if i < len(images) - 1 else None,
            is_favorite=os.path.exists(fav)
        )

    @app.route("/favorite/<tournament>/<path:folder>/<filename>", methods=["POST"])
    def favorite_photo(tournament, folder, filename):
        if not recover_tournament(tournament, dropbox_zip_path):
            abort(404)

        source = os.path.join(ctx.TOURNAMENT_DIR, tournament, folder, filename)

        if not os.path.exists(source):
            abort(404)

        copy_unique(source, os.path.join(ctx.TOURNAMENT_DIR, tournament, "Favorites"))

        return redirect(url_for(
            "photo_view",
            tournament=tournament,
            folder=folder,
            file=filename
        ))

    @app.route("/image/<tournament>/<path:folder>/<filename>")
    def image(tournament, folder, filename):
        if not recover_tournament(tournament, dropbox_zip_path):
            abort(404)

        image_folder = os.path.join(ctx.TOURNAMENT_DIR, tournament, folder)

        if not os.path.exists(os.path.join(image_folder, filename)):
            abort(404)

        return send_from_directory(image_folder, filename)

    @app.route("/more")
    def more_menu():
        tournaments = []

        if os.path.exists(ctx.TOURNAMENT_DIR):
            for d in sorted(os.listdir(ctx.TOURNAMENT_DIR), reverse=True):
                if os.path.isdir(os.path.join(ctx.TOURNAMENT_DIR, d)):
                    tournaments.append(d)

        return render_template("more.html", tournaments=tournaments)

    @app.route("/review/<tournament>")
    def review_queue(tournament):
        if not recover_tournament(tournament, dropbox_zip_path):
            abort(404)

        items = []

        unk = os.path.join(ctx.TOURNAMENT_DIR, tournament, "Players", "Unknown")

        if os.path.exists(unk):
            for f in sorted(os.listdir(unk)):
                if f.lower().endswith(ctx.IMAGE_EXTENSIONS):
                    items.append({
                        "folder": "Players/Unknown",
                        "file": f,
                        "reason": "Unknown player",
                        "ocr_number": ""
                    })

        report = os.path.join(
            ctx.TOURNAMENT_DIR,
            tournament,
            "Reports",
            "diamondvision_report.csv"
        )

        if os.path.exists(report):
            with open(report, newline="") as fh:
                for row in csv.DictReader(fh):
                    try:
                        conf = float(row.get("OCR Confidence", 0) or 0)
                    except Exception:
                        conf = 0

                    pp = row.get("Player Path", "")

                    if pp and conf > 0 and conf < 0.50:
                        rel = os.path.relpath(
                            pp,
                            os.path.join(ctx.TOURNAMENT_DIR, tournament)
                        ).replace("\\", "/")

                        folder = "/".join(rel.split("/")[:-1])
                        file = rel.split("/")[-1]

                        if not any(x["folder"] == folder and x["file"] == file for x in items):
                            items.append({
                                "folder": folder,
                                "file": file,
                                "reason": f"Low OCR confidence: {conf:.2f}",
                                "ocr_number": row.get("OCR Number", "")
                            })

        players = []
        root = os.path.join(ctx.TOURNAMENT_DIR, tournament, "Players")

        if os.path.exists(root):
            for item in sorted(os.listdir(root)):
                if os.path.isdir(os.path.join(root, item)):
                    players.append(item)

        teams_root = os.path.join(ctx.TOURNAMENT_DIR, tournament, "Teams")

        if os.path.exists(teams_root):
            for team in sorted(os.listdir(teams_root)):
                pr = os.path.join(teams_root, team, "Players")

                if os.path.exists(pr):
                    for player in sorted(os.listdir(pr)):
                        if os.path.isdir(os.path.join(pr, player)):
                            opt = f"{team}/Players/{player}"
                            if opt not in players:
                                players.append(opt)

        groups = {}

        for item in items:
            key = f"Likely #{item.get('ocr_number')}" if item.get("ocr_number") else item.get("reason", "Review")

            if "Low OCR confidence" in key:
                key = "Low-confidence OCR"

            if key == "Unknown player":
                key = "Unknown player"

            groups.setdefault(key, []).append(item)

        return render_template(
            "review.html",
            tournament=tournament,
            items=items,
            groups=groups,
            players=players
        )

    def target_folder_for(tournament, target_player):
        if "/Players/" in target_player:
            return os.path.join(ctx.TOURNAMENT_DIR, tournament, "Teams", *target_player.split("/"))

        return os.path.join(ctx.TOURNAMENT_DIR, tournament, "Players", safe_name(target_player))

    @app.route("/review-move/<tournament>/<path:folder>/<filename>", methods=["POST"])
    def review_move(tournament, folder, filename):
        if not recover_tournament(tournament, dropbox_zip_path):
            abort(404)

        target_player = request.form.get("target_player", "").strip()

        if not target_player:
            return redirect(url_for("review_queue", tournament=tournament))

        source = os.path.join(ctx.TOURNAMENT_DIR, tournament, folder, filename)

        if not os.path.exists(source):
            abort(404)

        dest_folder = target_folder_for(tournament, target_player)
        os.makedirs(dest_folder, exist_ok=True)

        shutil.move(source, os.path.join(dest_folder, filename))

        return redirect(url_for("review_queue", tournament=tournament))

    @app.route("/review-group-move/<tournament>", methods=["POST"])
    def review_group_move(tournament):
        if not recover_tournament(tournament, dropbox_zip_path):
            abort(404)

        target_player = request.form.get("target_player", "").strip()
        files = request.form.getlist("files")

        if not target_player or not files:
            return redirect(url_for("review_queue", tournament=tournament))

        dest_folder = target_folder_for(tournament, target_player)
        os.makedirs(dest_folder, exist_ok=True)

        for item in files:
            if "||" not in item:
                continue

            folder, filename = item.split("||", 1)
            source = os.path.join(ctx.TOURNAMENT_DIR, tournament, folder, filename)

            if os.path.exists(source):
                dest = os.path.join(dest_folder, filename)

                if os.path.exists(dest):
                    n, e = os.path.splitext(filename)
                    dest = os.path.join(
                        dest_folder,
                        f"{n}_{datetime.now().strftime('%H%M%S%f')}{e}"
                    )

                shutil.move(source, dest)

        return redirect(url_for("review_queue", tournament=tournament))

    @app.route("/live/<tournament>", methods=["GET", "POST"])
    def live_upload(tournament):
        if not recover_tournament(tournament, dropbox_zip_path):
            abort(404)

        tpath = os.path.join(ctx.TOURNAMENT_DIR, tournament)
        live_dir = os.path.join(ctx.UPLOAD_DIR, "LIVE_" + tournament)
        os.makedirs(live_dir, exist_ok=True)

        log_path = os.path.join(tpath, "live_processed_files.txt")
        done = set(open(log_path, encoding="utf-8").read().splitlines()) if os.path.exists(log_path) else set()

        if request.method == "POST":
            stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
            batch = os.path.join(live_dir, stamp)
            os.makedirs(batch, exist_ok=True)

            saved = 0
            skipped = 0

            for f in request.files.getlist("photos"):
                if not f or not f.filename:
                    continue

                name = secure_filename(f.filename)
                ext = os.path.splitext(name)[1].lower()

                if ext not in ctx.UPLOAD_EXTENSIONS:
                    continue

                if name in done:
                    skipped += 1
                    continue

                f.save(os.path.join(batch, name))
                done.add(name)
                saved += 1

            with open(log_path, "w", encoding="utf-8") as out:
                for name in sorted(done):
                    out.write(name + "\n")

            if saved > 0 and ctx.PROCESSOR_AVAILABLE:
                roster_path = os.path.join(tpath, "mobile_roster.txt")
                roster = open(roster_path, encoding="utf-8").read() if os.path.exists(roster_path) else ""

                job = "LIVE_" + tournament + "_" + stamp

                ctx.JOB_STATUS[job] = {
                    "done": 0,
                    "total": saved,
                    "percent": 0,
                    "message": "Live upload queued",
                    "complete": False,
                    "error": ""
                }

                def progress(d, total, msg):
                    ctx.JOB_STATUS[job] = {
                        "done": d,
                        "total": total,
                        "percent": int((d / total) * 100) if total else 0,
                        "message": msg,
                        "complete": d >= total and total > 0,
                        "error": ""
                    }

                def runner():
                    try:
                        process_mobile_job(batch, tpath, roster, progress_callback=progress)
                        ctx.JOB_STATUS[job]["complete"] = True
                        ctx.JOB_STATUS[job]["percent"] = 100
                        ctx.JOB_STATUS[job]["message"] = "Processing complete"

                    except Exception as e:
                        ctx.JOB_STATUS[job] = {
                            "done": 0,
                            "total": 0,
                            "percent": 0,
                            "message": "Error",
                            "complete": True,
                            "error": str(e)
                        }

                threading.Thread(target=runner, daemon=True).start()

                return redirect(url_for("processing", job_name=job))

            return redirect(url_for("live_upload", tournament=tournament))

        stats = {
            "best": count_images(os.path.join(tpath, "Best")),
            "keep": count_images(os.path.join(tpath, "Keep")),
            "unknown": count_images(os.path.join(tpath, "Players", "Unknown")),
            "processed": len(done)
        }

        return render_template(
            "live.html",
            tournament=tournament,
            message="Add new photos to this same tournament.",
            cards=build_cards(tournament),
            live_stats=stats
        )

    @app.route("/review-workspace/<tournament>/<path:folder>")
    def review_workspace(tournament, folder):
        if not recover_tournament(tournament, dropbox_zip_path):
            abort(404)

        folder_path = os.path.join(ctx.TOURNAMENT_DIR, tournament, folder)

        if not os.path.exists(folder_path):
            abort(404)

        images = [
            f for f in sorted(os.listdir(folder_path))
            if f.lower().endswith(ctx.IMAGE_EXTENSIONS)
        ]

        if not images:
            abort(404)

        current = request.args.get("file") or images[0]

        if current not in images:
            current = images[0]

        index = images.index(current)

        return render_template(
            "review_workspace.html",
            tournament=tournament,
            folder=folder,
            images=images,
            current=current,
            index=index,
            total=len(images),
            prev_file=images[index - 1] if index > 0 else None,
            next_file=images[index + 1] if index < len(images) - 1 else None
        )