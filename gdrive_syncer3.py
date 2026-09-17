#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
import pickle
from urllib.parse import urlencode

import requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import Resource, build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


class GoogleDriveSyncer:
    def __init__(
        self, client_id=None, client_secret=None, token_file: str = "token.pickle"
    ) -> None:
        self.client_id = client_id or os.getenv("GOOGLE_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("GOOGLE_CLIENT_SECRET")
        if not self.client_id or not self.client_secret:
            raise ValueError("Missing credentials in environment")
        self.token_file = token_file
        self.service = self.authenticate()

    def authenticate(self) -> Resource:
        creds = None
        if os.path.exists(self.token_file):
            with open(self.token_file, "rb") as token:
                creds = pickle.load(token)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                refresh_data = {
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": creds.refresh_token,
                    "grant_type": "refresh_token",
                }
                response = requests.post(
                    "https://oauth2.googleapis.com/token", data=refresh_data
                )
                if response.status_code == 200:
                    token_data = response.json()
                    creds = Credentials(
                        token=token_data["access_token"],
                        refresh_token=creds.refresh_token,
                        token_uri="https://oauth2.googleapis.com/token",
                        client_id=self.client_id,
                        client_secret=self.client_secret,
                    )
                    with open(self.token_file, "wb") as token:
                        pickle.dump(creds, token)
            else:
                creds = self.manual_oauth_flow()
        return build("drive", "v3", credentials=creds)

    def manual_oauth_flow(self) -> Credentials:
        auth_params = {
            "client_id": self.client_id,
            "redirect_uri": "urn:ietf:wg:oauth:2.0:oob",
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",
        }
        auth_url = f"https://accounts.google.com/o/oauth2/auth?{urlencode(auth_params)}"
        print("\n" + "=" * 40)
        print("MANUAL AUTHENTICATION REQUIRED")
        print("-" * 40)
        print(f"1. Open this URL in your browser:\n{auth_url}")
        print("\n2. Log in to your Google account")
        print("3. Grant permissions when prompted")
        print("4. Copy the authorization code")
        print("-" * 40)
        auth_code = input("\nEnter authorization code: ").strip()
        token_params = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": auth_code,
            "grant_type": "authorization_code",
            "redirect_uri": "urn:ietf:wg:oauth:2.0:oob",
        }
        response = requests.post(
            "https://oauth2.googleapis.com/token", data=token_params
        )
        if response.status_code != 200:
            raise Exception(f"Token exchange failed: {response.text}")
        token_data = response.json()
        credentials = Credentials(
            token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=self.client_id,
            client_secret=self.client_secret,
        )
        with open(self.token_file, "wb") as token:
            pickle.dump(credentials, token)
        return credentials

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

    def sync_all(self, local_base_path: str) -> None:
        print("Starting full Google Drive sync...")
        self.sync_folder("root", local_base_path, "My Drive")
        print("\n✅ Sync completed!")


def install_minimal_packages() -> None:
    import subprocess
    import sys

    packages = ["google-api-python-client", "google-auth-oauthlib", "requests"]
    for package in packages:
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])
            print(f"✓ Installed {package}")
        except:
            print(f"✗ Failed to install {package}")


def main() -> None:
    from pathlib import Path

    from dotenv import load_dotenv

    env_path = Path.home() / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
    LOCAL_SYNC_PATH = "/sdcard/GoogleDriveBackup"
    try:
        syncer = GoogleDriveSyncer()
        syncer.sync_all(LOCAL_SYNC_PATH)
    except Exception as e:
        print(f"Error: {e}")
        print("\nTroubleshooting:")
        print("1. Ensure your ~/.env file has correct credentials")
        print("2. Check internet connection")
        print(
            "3. On Android, ensure Termux has storage permission: termux-setup-storage"
        )


if __name__ == "__main__":
    raise SystemExit(main())
