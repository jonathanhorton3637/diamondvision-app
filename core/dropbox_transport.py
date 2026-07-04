import os
import zipfile
import dropbox


def get_client():
    from config import (
        DROPBOX_APP_KEY,
        DROPBOX_APP_SECRET,
        DROPBOX_REFRESH_TOKEN,
        DROPBOX_ACCESS_TOKEN,
    )

    if DROPBOX_REFRESH_TOKEN and DROPBOX_APP_KEY and DROPBOX_APP_SECRET:
        return dropbox.Dropbox(
            oauth2_refresh_token=DROPBOX_REFRESH_TOKEN.strip(),
            app_key=DROPBOX_APP_KEY.strip(),
            app_secret=DROPBOX_APP_SECRET.strip(),
        )

    if DROPBOX_ACCESS_TOKEN:
        return dropbox.Dropbox(DROPBOX_ACCESS_TOKEN.strip())

    raise RuntimeError("Dropbox credentials are missing")


def zip_folder(source_folder, zip_path):
    os.makedirs(os.path.dirname(zip_path), exist_ok=True)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(source_folder):
            for file in files:
                full = os.path.join(root, file)
                rel = os.path.relpath(full, source_folder)
                z.write(full, rel)

    return zip_path


def unzip_file(zip_path, output_folder):
    os.makedirs(output_folder, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(output_folder)


def upload_file(local_path, dropbox_path, access_token=None):
    dbx = get_client()

    with open(local_path, "rb") as f:
        dbx.files_upload(
            f.read(),
            dropbox_path,
            mode=dropbox.files.WriteMode.overwrite
        )

    return dropbox_path


def download_file(dropbox_path, local_path, access_token=None):
    os.makedirs(os.path.dirname(local_path), exist_ok=True)

    dbx = get_client()
    _, res = dbx.files_download(dropbox_path)

    with open(local_path, "wb") as f:
        f.write(res.content)

    return local_path
