import os
import zipfile
import dropbox


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


def upload_file(local_path, dropbox_path, access_token):
    dbx = dropbox.Dropbox(access_token.strip())

    with open(local_path, "rb") as f:
        dbx.files_upload(
            f.read(),
            dropbox_path,
            mode=dropbox.files.WriteMode.overwrite
        )

    return dropbox_path


def download_file(dropbox_path, local_path, access_token):
    os.makedirs(os.path.dirname(local_path), exist_ok=True)

    dbx = dropbox.Dropbox(access_token.strip())
    _, res = dbx.files_download(dropbox_path)

    with open(local_path, "wb") as f:
        f.write(res.content)

    return local_path
