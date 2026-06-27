from flask import Flask, render_template, request, redirect, url_for, send_from_directory, abort, jsonify
import os
import shutil
import threading
import zipfile
from datetime import datetime
from werkzeug.utils import secure_filename

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


def update_job_status(job_name, done, total, message):
    percent = 0

    if total > 0:
        percent = int((done / total) * 100)

    JOB_STATUS[job_name] = {
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

        JOB_STATUS[job_name]["summary"] = summary
        JOB_STATUS[job_name]["complete"] = True
        JOB_STATUS[job_name]["percent"] = 100
        JOB_STATUS[job_name]["message"] = "Processing complete"

    except Exception as e:
        JOB_STATUS[job_name] = {
            "done": 0,
            "total": 0,
            "percent": 0,
            "message": "Error",
            "complete": True,
            "error": str(e)
        }


def dropbox_zip_path(tournament):
    zip_name = f"{safe_name(tournament)}_Dropbox_Player_Gallery.zip"
    return os.path.join(DROPBOX_EXPORT_DIR, zip_name)


@app.route("/")
def index():
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


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "processor_available": PROCESSOR_AVAILABLE,
        "processor_error": PROCESSOR_ERROR
    })


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

        upload_path = os.path.join(UPLOAD_DIR, job_name)
        output_path = os.path.join(TOURNAMENT_DIR, job_name)

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

            if ext not in UPLOAD_EXTENSIONS:
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

        if PROCESSOR_AVAILABLE:
            JOB_STATUS[job_name] = {
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
        processor_available=PROCESSOR_AVAILABLE
    )


@app.route("/processing/<job_name>")
def processing(job_name):
    return render_template(
        "processing.html",
        job_name=job_name
    )


@app.route("/api/status/<job_name>")
def api_status(job_name):
    status = JOB_STATUS.get(job_name, {
        "done": 0,
        "total": 0,
        "percent": 0,
        "message": "Waiting...",
        "complete": False,
        "error": ""
    })

    return jsonify(status)


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


@app.route("/export-dropbox/<tournament>", methods=["POST"])
def export_dropbox(tournament):
    tournament_path = os.path.join(TOURNAMENT_DIR, tournament)
    players_path = os.path.join(tournament_path, "Players")

    if not os.path.exists(players_path):
        abort(404)

    zip_path = dropbox_zip_path(tournament)

    if os.path.exists(zip_path):
        os.remove(zip_path)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(players_path):
            for file in files:
                if file.lower().endswith(IMAGE_EXTENSIONS):
                    full_path = os.path.join(root, file)
                    rel_path = os.path.relpath(full_path, players_path)
                    z.write(full_path, rel_path)

    return redirect(url_for("tournament", name=tournament))


@app.route("/download-dropbox/<tournament>")
def download_dropbox(tournament):
    zip_path = dropbox_zip_path(tournament)

    if not os.path.exists(zip_path):
        abort(404)

    filename = os.path.basename(zip_path)

    return send_from_directory(
        DROPBOX_EXPORT_DIR,
        filename,
        as_attachment=True
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
                            "reason": f"Low OCR confidence: {conf:.2f}"
                        })

    players = []

    players_root = os.path.join(TOURNAMENT_DIR, tournament, "Players")

    if os.path.exists(players_root):
        for item in sorted(os.listdir(players_root)):
            full = os.path.join(players_root, item)
            if os.path.isdir(full):
                players.append(item)

    return render_template(
        "review.html",
        tournament=tournament,
        items=items,
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

        return render_template("live.html",tournament=tournament,message=f"Saved {saved}, skipped {skipped}",cards=build_cards(tournament))

    return render_template("live.html",tournament=tournament,message="Add new photos to this same tournament.",cards=build_cards(tournament))




@app.route("/admin")
def admin():
    tournaments=[]
    if os.path.exists(TOURNAMENT_DIR):
        for d in sorted(os.listdir(TOURNAMENT_DIR), reverse=True):
            if os.path.isdir(os.path.join(TOURNAMENT_DIR,d)):
                tournaments.append(d)
    return render_template(
        "admin.html",
        tournaments=tournaments,
        processor_available=PROCESSOR_AVAILABLE,
        processor_error=PROCESSOR_ERROR
    )


@app.route("/manifest.json")
def manifest():
    return send_from_directory("static", "manifest.json")


@app.route("/service-worker.js")
def service_worker():
    return send_from_directory("static", "service-worker.js")


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=False
    )
