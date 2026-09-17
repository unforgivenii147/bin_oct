#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import io
import os
import pickle

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import Resource, build
from googleapiclient.http import MediaIoBaseDownload

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


def authenticate() -> Resource:
    creds = None
    if os.path.exists("token.pickle"):
        with open("token.pickle", "rb") as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        with open("token.pickle", "wb") as token:
            pickle.dump(creds, token)
    return build("drive", "v3", credentials=creds)


def get_folder_id(service: Resource, folder_name: str):
    query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    items = results.get("files", [])
    if not items:
        raise Exception(f"Folder '{folder_name}' not found in Google Drive")
    return items[0]["id"]


def download_folder(service: Resource, folder_id, current_path: str) -> None:
    query = f"'{folder_id}' in parents and trashed=false"
    results = (
        service.files().list(q=query, fields="files(id, name, mimeType)").execute()
    )
    items = results.get("files", [])
    for item in items:
        item_path = os.path.join(current_path, item["name"])
        if item["mimeType"] == "application/vnd.google-apps.folder":
            os.makedirs(item_path, exist_ok=True)
            print(f"Creating folder: {item_path}")
            download_folder(service, item["id"], item_path)
        else:
            print(f"Downloading: {item_path}")
            request = service.files().get_media(fileId=item["id"])
            fh = io.FileIO(item_path, "wb")
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
                print(f"Download progress: {int(status.progress() * 40)}%")
            fh.close()


def main() -> None:
    folder_name = "notebooks"
    try:
        service = authenticate()
        folder_id = get_folder_id(service, folder_name)
        print(f"Found folder '{folder_name}' with ID: {folder_id}")
        current_folder = os.path.join(os.getcwd(), folder_name)
        os.makedirs(current_folder, exist_ok=True)
        download_folder(service, folder_id, current_folder)
        print(f"\nSuccessfully downloaded '{folder_name}' to {current_folder}")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    raise SystemExit(main())
