from flask import Flask, render_template, request, redirect, url_for, send_from_directory, abort, jsonify
import os
import shutil
import threading
import zipfile
from datetime import datetime
from werkzeug.utils import secure_filename
from core import context as ctx
from routes.api import register_api_routes
from routes.static_files import register_static_routes
from routes.dashboard import register_dashboard_routes
from routes.admin import register_admin_routes
from routes.upload import register_upload_routes
from routes.dropbox_routes import register_dropbox_routes

try:
    from processor import process_mobile_job, safe_name
    PROCESSOR_AVAILABLE = True
    PROCESSOR_ERROR = ""
except Exception as e:
    PROCESSOR_AVAILABLE = False
    PROCESSOR_ERROR = str(e)

    def safe_name(text):
        text = str(text).strip() or "Unknown"
        for ch in '<>:"/\\|?*#':
            text = text.replace(ch, "_")
        return text.replace(" ", "_")


app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TOURNAMENT_DIR = os.path.join(BASE_DIR, "Tournament")
UPLOAD_DIR = os.path.join(BASE_DIR, "MobileUploads")
DROPBOX_EXPORT_DIR = os.path.join(BASE_DIR, "DropboxExports")

os.makedirs(TOURNAMENT_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(DROPBOX_EXPORT_DIR, exist_ok=True)

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png")
UPLOAD_EXTENSIONS = (".jpg", ".jpeg", ".png", ".nef")

JOB_STATUS = {}

ctx.app = app
ctx.BASE_DIR = BASE_DIR
ctx.TOURNAMENT_DIR = TOURNAMENT_DIR
ctx.UPLOAD_DIR = UPLOAD_DIR
ctx.DROPBOX_EXPORT_DIR = DROPBOX_EXPORT_DIR
ctx.IMAGE_EXTENSIONS = IMAGE_EXTENSIONS
ctx.UPLOAD_EXTENSIONS = UPLOAD_EXTENSIONS
ctx.JOB_STATUS = JOB_STATUS
ctx.PROCESSOR_AVAILABLE = PROCESSOR_AVAILABLE
ctx.PROCESSOR_ERROR = PROCESSOR_ERROR

register_api_routes(app)
register_static_routes(app)

try:
    from config import DROPBOX_ACCESS_TOKEN, DROPBOX_PARENT_FOLDER
except Exception:
    DROPBOX_ACCESS_TOKEN = ""
    DROPBOX_PARENT_FOLDER = "/DiamondVision"


def count_images(path):
    if not os.path.exists(path):
        return 0

    return len([
        f for f in os.listdir(path)
        if f.lower().endswith(IMAGE_EXTENSIONS)
    ])


def first_image(folder_path):
    if not os.path.exists(folder_path):
        return None

    for item in sorted(os.listdir(folder_path)):
        full = os.path.join(folder_path, item)

        if os.path.isfile(full) and item.lower().endswith(IMAGE_EXTENSIONS):
            return item

    return None


def first_image_recursive(folder_path):
    if not os.path.exists(folder_path):
        return None

    for root, _, files in os.walk(folder_path):
        for file in sorted(files):
            if file.lower().endswith(IMAGE_EXTENSIONS):
                rel_folder = os.path.relpath(root, folder_path)

                if rel_folder == ".":
                    rel_folder = ""

                return {
                    "folder": rel_folder.replace("\\", "/"),
                    "file": file
                }

    return None


def folder_image_url(tournament, folder, filename):
    return f"/image/{tournament}/{folder}/{filename}"


def nested_image_url(tournament, base_folder, nested_folder, filename):
    if nested_folder:
        return f"/image/{tournament}/{base_folder}/{nested_folder}/{filename}"

    return f"/image/{tournament}/{base_folder}/{filename}"


def copy_unique(src, dest_folder):
    os.makedirs(dest_folder, exist_ok=True)

    dest = os.path.join(dest_folder, os.path.basename(src))

    if os.path.exists(dest):
        name, ext = os.path.splitext(os.path.basename(src))
        stamp = datetime.now().strftime("%H%M%S%f")
        dest = os.path.join(dest_folder, f"{name}_{stamp}{ext}")

    shutil.copy2(src, dest)

    return dest


def build_tournament_info(name):
    path = os.path.join(TOURNAMENT_DIR, name)
    best_path = os.path.join(path, "BestOfTournament")
    players_path = os.path.join(path, "Players")

    cover = first_image(best_path)
    cover_url = None

    if cover:
        cover_url = folder_image_url(name, "BestOfTournament", cover)
    else:
        recursive = first_image_recursive(path)

        if recursive:
            cover_url = f"/image/{name}/{recursive['folder']}/{recursive['file']}"

    players_count = 0

    if os.path.exists(players_path):
        players_count = len([
            d for d in os.listdir(players_path)
            if os.path.isdir(os.path.join(players_path, d))
        ])

    return {
        "name": name,
        "best": count_images(best_path),
        "players": players_count,
        "cover": cover_url
    }


def build_cards(name):
    path = os.path.join(TOURNAMENT_DIR, name)

    config = [
        ("BestOfTournament", "Best Shots", "Top tournament images"),
        ("Favorites", "Favorites", "Client-ready picks"),
        ("Players", "Players", "Sorted by roster/player"),
        ("Teams", "Teams", "Two-team sorted player folders"),
        ("Best", "Best", "Highest scoring photos"),
        ("Keep", "Keep", "Usable photos"),
        ("Reject", "Reject", "Rejected photos"),
        ("Duplicates", "Duplicates", "Similar burst photos"),
    ]

    cards = []

    for folder, label, subtitle in config:
        folder_path = os.path.join(path, folder)

        if not os.path.exists(folder_path):
            continue

        preview = first_image(folder_path)
        preview_url = None

        if preview:
            preview_url = folder_image_url(name, folder, preview)
        else:
            recursive = first_image_recursive(folder_path)

            if recursive:
                preview_url = nested_image_url(
                    name,
                    folder,
                    recursive["folder"],
                    recursive["file"]
                )

        cards.append({
            "name": folder,
            "label": label,
            "subtitle": subtitle,
            "count": count_images(folder_path),
            "preview": preview_url,
            "url": f"/gallery/{name}/{folder}"
        })

    return cards


def dropbox_zip_path(tournament):
    zip_name = f"{safe_name(tournament)}_Dropbox_Player_Gallery.zip"
    return os.path.join(DROPBOX_EXPORT_DIR, zip_name)


register_dashboard_routes(app, count_images, dropbox_zip_path)
register_admin_routes(app)
register_upload_routes(app, safe_name, process_mobile_job)
register_dropbox_routes(app, safe_name, dropbox_zip_path, DROPBOX_ACCESS_TOKEN, DROPBOX_PARENT_FOLDER)


@app.route("/")
def index():
    return redirect(url_for("dashboard"))


@app.route("/tournaments")
def tournaments_page():
    tournaments = []

    for d in sorted(os.listdir(TOURNAMENT_DIR), reverse=True):
        path = os.path.join(TOURNAMENT_DIR, d)

        if not os.path.isdir(path):
            continue

        if d.lower() in ("input", "output", "__pycache__"):
            continue

        tournaments.append(build_tournament_info(d))

    return render_template(
        "index.html",
        tournaments=tournaments,
        processor_available=PROCESSOR_AVAILABLE
    )



@app.route("/tournament/<name>")
def tournament(name):
    path = os.path.join(TOURNAMENT_DIR, name)

    if not os.path.exists(path):
        abort(404)

    os.makedirs(os.path.join(path, "Favorites"), exist_ok=True)

    export_ready = os.path.exists(dropbox_zip_path(name))

    return render_template(
        "tournament.html",
        tournament=name,
        cards=build_cards(name),
        summary=None,
        export_ready=export_ready
    )


@app.route("/gallery/<tournament>/<path:folder>")
def gallery(tournament, folder):
    folder_path = os.path.join(TOURNAMENT_DIR, tournament, folder)

    if not os.path.exists(folder_path):
        abort(404)

    subfolders = []
    images = []

    for item in sorted(os.listdir(folder_path)):
        full = os.path.join(folder_path, item)

        if os.path.isdir(full):
            preview = first_image(full)

            subfolders.append({
                "name": item,
                "count": count_images(full),
                "preview": preview,
                "url": f"/gallery/{tournament}/{folder}/{item}"
            })

        elif item.lower().endswith(IMAGE_EXTENSIONS):
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
    filename = request.args.get("file")
    folder_path = os.path.join(TOURNAMENT_DIR, tournament, folder)

    if not os.path.exists(folder_path):
        abort(404)

    images = [
        f for f in sorted(os.listdir(folder_path))
        if f.lower().endswith(IMAGE_EXTENSIONS)
    ]

    if not filename or filename not in images:
        abort(404)

    index = images.index(filename)
    prev_file = images[index - 1] if index > 0 else None
    next_file = images[index + 1] if index < len(images) - 1 else None

    favorite_path = os.path.join(
        TOURNAMENT_DIR,
        tournament,
        "Favorites",
        filename
    )

    is_favorite = os.path.exists(favorite_path)

    return render_template(
        "photo.html",
        tournament=tournament,
        folder=folder,
        filename=filename,
        index=index,
        total=len(images),
        prev_file=prev_file,
        next_file=next_file,
        is_favorite=is_favorite
    )


@app.route("/favorite/<tournament>/<path:folder>/<filename>", methods=["POST"])
def favorite_photo(tournament, folder, filename):
    source = os.path.join(TOURNAMENT_DIR, tournament, folder, filename)
    favorites = os.path.join(TOURNAMENT_DIR, tournament, "Favorites")

    if not os.path.exists(source):
        abort(404)

    copy_unique(source, favorites)

    return redirect(url_for(
        "photo_view",
        tournament=tournament,
        folder=folder,
        file=filename
    ))



@app.route("/review/<tournament>")
def review_queue(tournament):
    players_unknown = os.path.join(TOURNAMENT_DIR, tournament, "Players", "Unknown")

    items = []

    if os.path.exists(players_unknown):
        for file in sorted(os.listdir(players_unknown)):
            if file.lower().endswith(IMAGE_EXTENSIONS):
                items.append({
                    "folder": "Players/Unknown",
                    "file": file,
                    "reason": "Unknown player"
                })

    report_path = os.path.join(
        TOURNAMENT_DIR,
        tournament,
        "Reports",
        "diamondvision_report.csv"
    )

    if os.path.exists(report_path):
        import csv

        with open(report_path, newline="") as f:
            reader = csv.DictReader(f)

            for row in reader:
                try:
                    conf = float(row.get("OCR Confidence", 0) or 0)
                except Exception:
                    conf = 0

                player_path = row.get("Player Path", "")

                if player_path and conf > 0 and conf < 0.50:
                    rel = os.path.relpath(
                        player_path,
                        os.path.join(TOURNAMENT_DIR, tournament)
                    ).replace("\\", "/")

                    folder = "/".join(rel.split("/")[:-1])
                    file = rel.split("/")[-1]

                    already = any(
                        x["folder"] == folder and x["file"] == file
                        for x in items
                    )

                    if not already:
                        items.append({
                            "folder": folder,
                            "file": file,
                            "reason": f"Low OCR confidence: {conf:.2f}",
                            "ocr_number": row.get("OCR Number", "")
                        })

    players = []

    players_root = os.path.join(TOURNAMENT_DIR, tournament, "Players")

    if os.path.exists(players_root):
        for item in sorted(os.listdir(players_root)):
            full = os.path.join(players_root, item)
            if os.path.isdir(full):
                players.append(item)

    groups = {}

    for item in items:
        reason = item.get("reason", "Review")
        ocr_number = item.get("ocr_number", "")

        if ocr_number:
            key = f"Likely #{ocr_number}"
        elif "Low OCR confidence" in reason:
            key = "Low-confidence OCR"
        elif "Unknown" in reason:
            key = "Unknown player"
        else:
            key = reason

        groups.setdefault(key, []).append(item)

    return render_template(
        "review.html",
        tournament=tournament,
        items=items,
        groups=groups,
        players=players
    )


@app.route("/review-move/<tournament>/<path:folder>/<filename>", methods=["POST"])
def review_move(tournament, folder, filename):
    target_player = request.form.get("target_player", "").strip()

    if not target_player:
        return redirect(url_for("review_queue", tournament=tournament))

    source = os.path.join(TOURNAMENT_DIR, tournament, folder, filename)

    if not os.path.exists(source):
        abort(404)

    if "/Players/" in target_player:
        target_folder = os.path.join(
            TOURNAMENT_DIR,
            tournament,
            "Teams",
            *target_player.split("/")
        )
    else:
        target_folder = os.path.join(
            TOURNAMENT_DIR,
            tournament,
            "Players",
            safe_name(target_player)
        )

    os.makedirs(target_folder, exist_ok=True)

    dest = os.path.join(target_folder, filename)

    if os.path.exists(dest):
        name, ext = os.path.splitext(filename)
        stamp = datetime.now().strftime("%H%M%S%f")
        dest = os.path.join(target_folder, f"{name}_{stamp}{ext}")

    shutil.move(source, dest)

    return redirect(url_for("review_queue", tournament=tournament))




@app.route("/review-group-move/<tournament>", methods=["POST"])
def review_group_move(tournament):
    target_player = request.form.get("target_player", "").strip()
    files = request.form.getlist("files")

    if not target_player or not files:
        return redirect(url_for("review_queue", tournament=tournament))

    if "/Players/" in target_player:
        target_folder = os.path.join(
            TOURNAMENT_DIR,
            tournament,
            "Teams",
            *target_player.split("/")
        )
    else:
        target_folder = os.path.join(
            TOURNAMENT_DIR,
            tournament,
            "Players",
            safe_name(target_player)
        )

    os.makedirs(target_folder, exist_ok=True)

    for item in files:
        if "||" not in item:
            continue

        folder, filename = item.split("||", 1)
        source = os.path.join(TOURNAMENT_DIR, tournament, folder, filename)

        if not os.path.exists(source):
            continue

        dest = os.path.join(target_folder, filename)

        if os.path.exists(dest):
            name, ext = os.path.splitext(filename)
            stamp = datetime.now().strftime("%H%M%S%f")
            dest = os.path.join(target_folder, f"{name}_{stamp}{ext}")

        shutil.move(source, dest)

    return redirect(url_for("review_queue", tournament=tournament))



@app.route("/image/<tournament>/<path:folder>/<filename>")
def image(tournament, folder, filename):
    return send_from_directory(
        os.path.join(TOURNAMENT_DIR, tournament, folder),
        filename
    )



@app.route("/live/<tournament>", methods=["GET","POST"])
def live_upload(tournament):
    tpath=os.path.join(TOURNAMENT_DIR,tournament)
    if not os.path.exists(tpath):
        abort(404)

    live_dir=os.path.join(UPLOAD_DIR,"LIVE_"+tournament)
    os.makedirs(live_dir,exist_ok=True)

    log=os.path.join(tpath,"live_processed_files.txt")
    done=set()
    if os.path.exists(log):
        done=set(x.strip() for x in open(log,encoding="utf-8") if x.strip())

    if request.method=="POST":
        stamp=datetime.now().strftime("%Y-%m-%d-%H%M%S")
        batch=os.path.join(live_dir,stamp)
        os.makedirs(batch,exist_ok=True)

        saved=0
        skipped=0

        for f in request.files.getlist("photos"):
            if not f or not f.filename:
                continue
            name=secure_filename(f.filename)
            ext=os.path.splitext(name)[1].lower()
            if ext not in UPLOAD_EXTENSIONS:
                continue
            if name in done:
                skipped+=1
                continue
            f.save(os.path.join(batch,name))
            done.add(name)
            saved+=1

        with open(log,"w",encoding="utf-8") as out:
            for name in sorted(done):
                out.write(name+"\n")

        if saved>0 and PROCESSOR_AVAILABLE:
            roster=""
            rp=os.path.join(tpath,"mobile_roster.txt")
            if os.path.exists(rp):
                roster=open(rp,encoding="utf-8").read()

            job="LIVE_"+tournament+"_"+stamp
            JOB_STATUS[job]={"done":0,"total":saved,"percent":0,"message":"Live upload queued","complete":False,"error":""}

            thread=threading.Thread(
                target=run_processing_job,
                args=(job,batch,tpath,roster),
                daemon=True
            )
            thread.start()
            return redirect(url_for("processing",job_name=job))

        return redirect(url_for("live_upload", tournament=tournament))

    live_stats = {
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
        live_stats=live_stats
    )






@app.route("/more")
def more_menu():
    tournaments=[]
    if os.path.exists(TOURNAMENT_DIR):
        for d in sorted(os.listdir(TOURNAMENT_DIR), reverse=True):
            if os.path.isdir(os.path.join(TOURNAMENT_DIR,d)):
                tournaments.append(d)
    return render_template("more.html", tournaments=tournaments)


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=False
    )
