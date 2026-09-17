#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
import pickle

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import Resource, build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


class GoogleDriveSyncer:
    def __init__(
        self,
        credentials_file: str = "credentials.json",
        token_file: str = "token.pickle",
    ) -> None:
        self.credentials_file = credentials_file
        self.token_file = token_file
        self.service = self.authenticate()

    def authenticate(self) -> Resource:
        creds = None
        if os.path.exists(self.token_file):
            with open(self.token_file, "rb") as token:
                creds = pickle.load(token)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not os.path.exists(self.credentials_file):
                    raise FileNotFoundError(
                        f"Credentials file '{self.credentials_file}' not found. Download it from Google Cloud Console."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_file, SCOPES
                )
                creds = flow.run_local_server(port=0)
            with open(self.token_file, "wb") as token:
                pickle.dump(creds, token)
        return build("drive", "v3", credentials=creds)

    def get_all_files(self, folder_id: str = "root"):
        all_items = []
        page_token = None
        while True:
            try:
                results = (
                    self.service.files()
                    .list(
                        q=f"'{folder_id}' in parents and trashed=false",
                        pageSize=1000,
                        fields="nextPageToken, files(id, name, mimeType, size, modifiedTime)",
                        pageToken=page_token,
                    )
                    .execute()
                )
                items = results.get("files", [])
                all_items.extend(items)
                page_token = results.get("nextPageToken")
                if not page_token:
                    break
            except HttpError as error:
                print(f"An error occurred: {error}")
                break
        return all_items

    def download_file(self, file_id, file_name, local_path) -> bool:
        try:
            request = self.service.files().get_media(fileId=file_id)
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            with open(local_path, "wb") as f:
                downloader = MediaIoBaseDownload(f, request)
                done = False
                while not done:
                    status, done = downloader.next_chunk()
                    print(f"Downloading {file_name}: {int(status.progress() * 40)}%")
            print(f"✓ Downloaded: {file_name}")
            return True
        except HttpError as error:
            print(f"✗ Failed to download {file_name}: {error}")
            return False

    def sync_folder(
        self, drive_folder_id: str, local_folder_path, folder_name: str = "root"
    ) -> None:
        print(f"\n📁 Syncing folder: {folder_name}")
        os.makedirs(local_folder_path, exist_ok=True)
        items = self.get_all_files(drive_folder_id)
        for item in items:
            item_name = item["name"]
            item_id = item["id"]
            item_mime = item.get("mimeType", "")
            local_item_path = os.path.join(local_folder_path, item_name)
            if item_mime == "application/vnd.google-apps.folder":
                self.sync_folder(item_id, local_item_path, item_name)
            else:
                remote_modified = item.get("modifiedTime")
                should_download = True
                if os.path.exists(local_item_path):
                    local_mtime = os.path.getmtime(local_item_path)
                    from datetime import datetime

                    remote_time = datetime.fromisoformat(remote_modified).timestamp()
                    if local_mtime >= remote_time:
                        should_download = False
                        print(f"⏭ Skipping (up to date): {item_name}")
                if should_download:
                    self.download_file(item_id, item_name, local_item_path)
                    if remote_modified:
                        from datetime import datetime

                        mod_time = datetime.fromisoformat(remote_modified).timestamp()
                        os.utime(local_item_path, (mod_time, mod_time))

    def sync_by_folder_name(self, folder_name, local_base_path) -> None:
        print(f"Searching for folder: {folder_name}")
        items = self.get_all_files("root")
        target_folder = None
        for item in items:
            if (
                item["name"] == folder_name
                and item["mimeType"] == "application/vnd.google-apps.folder"
            ):
                target_folder = item
                break
        if target_folder:
            self.sync_folder(target_folder["id"], local_base_path, folder_name)
        else:
            print(f'Folder "{folder_name}" not found in root directory')

    def sync_all(self, local_base_path: str) -> None:
        print("Starting full Google Drive sync...")
        self.sync_folder("root", local_base_path, "My Drive")
        print("\n✅ Sync completed!")


def main() -> None:
    LOCAL_SYNC_PATH = "./google_drive_backup"
    CREDENTIALS_FILE = "credentials.json"
    try:
        syncer = GoogleDriveSyncer(credentials_file=CREDENTIALS_FILE)
        syncer.sync_all(LOCAL_SYNC_PATH)
    except Exception as e:
        print(f"Error: {e}")
        print("\nSetup instructions:")
        print("1. Go to Google Cloud Console (https://console.cloud.google.com)")
        print("2. Create a new project or select existing")
        print("3. Enable Google Drive API")
        print("4. Create OAuth 2.0 credentials (Desktop application)")
        print('5. Download credentials as "credentials.json"')
        print("6. Place credentials.json in the same directory as this script")


if __name__ == "__main__":
    raise SystemExit(main())
