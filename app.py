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
from routes.main_routes import register_main_routes

try:
    from config import USE_SERVERLESS
except Exception:
    USE_SERVERLESS = False


if USE_SERVERLESS:
    PROCESSOR_AVAILABLE = True
    PROCESSOR_ERROR = ""

    def process_mobile_job(*args, **kwargs):
        raise RuntimeError("Local processor disabled because USE_SERVERLESS=True")

    def safe_name(text):
        text = str(text).strip() or "Unknown"
        for ch in '<>:"/\\|?*#':
            text = text.replace(ch, "_")
        return text.replace(" ", "_")

else:
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

@app.route("/envcheck")
def envcheck():
    import os
    return {
        "USE_SERVERLESS": os.environ.get("USE_SERVERLESS"),
        "RUNPOD_API_KEY": bool(os.environ.get("RUNPOD_API_KEY")),
        "RUNPOD_ENDPOINT_ID": os.environ.get("RUNPOD_ENDPOINT_ID"),
        "DROPBOX_APP_KEY": bool(os.environ.get("DROPBOX_APP_KEY")),
        "DROPBOX_REFRESH_TOKEN": bool(os.environ.get("DROPBOX_REFRESH_TOKEN")),
    }


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

if "process_mobile_job" not in globals():
    def process_mobile_job(*args, **kwargs):
        raise RuntimeError("Local processor disabled because USE_SERVERLESS=True")


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
register_main_routes(app, safe_name, build_tournament_info, build_cards, first_image, count_images, copy_unique, dropbox_zip_path, process_mobile_job)


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=False
    )
