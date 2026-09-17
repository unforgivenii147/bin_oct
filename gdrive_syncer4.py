#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
import pickle
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv
from requests.models import Response

env_path = Path.home() / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)


class GoogleDriveSync:
    def __init__(
        self, client_id=None, client_secret=None, token_file: str = "drive_token.pkl"
    ) -> None:
        self.client_id = client_id or os.getenv("GOOGLE_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("GOOGLE_CLIENT_SECRET")
        self.token_file = token_file
        self.access_token = None
        self.refresh_token = None
        if not self.client_id or not self.client_secret:
            raise ValueError(
                "Missing GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET in ~/.env"
            )
        self.load_or_auth()

    def load_or_auth(self) -> None:
        if os.path.exists(self.token_file):
            with open(self.token_file, "rb") as f:
                data = pickle.load(f)
                self.access_token = data.get("access_token")
                self.refresh_token = data.get("refresh_token")
                if self.access_token and not self.is_token_expired():
                    return
        self.authenticate()

    def is_token_expired(self) -> bool:
        return False

    def refresh_access_token(self) -> bool:
        if not self.refresh_token:
            return False
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
            "grant_type": "refresh_token",
        }
        response = requests.post("https://oauth2.googleapis.com/token", data=data)
        if response.status_code == 200:
            token_data = response.json()
            self.access_token = token_data.get("access_token")
            with open(self.token_file, "wb") as f:
                pickle.dump(
                    {
                        "access_token": self.access_token,
                        "refresh_token": self.refresh_token,
                    },
                    f,
                )
            return True
        return False

    def authenticate(self) -> None:
        print("\n" + "=" * 40)
        print("GOOGLE DRIVE AUTHENTICATION")
        print("-" * 40)
        auth_url = f"https://accounts.google.com/o/oauth2/auth?client_id={
            self.client_id
        }&redirect_uri=urn:ietf:wg:oauth:2.0:oob&response_type=code&scope=https://www.googleapis.com/auth/drive.readonly&access_type=offline"
        print("\n1. Open this URL in your browser:")
        print(f"\n{auth_url}\n")
        print("2. Sign in to your Google account")
        print("3. Grant access to Google Drive")
        print("4. Copy the authorization code")
        print("-" * 40)
        auth_code = input("\nEnter authorization code: ").strip()
        token_data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": auth_code,
            "grant_type": "authorization_code",
            "redirect_uri": "urn:ietf:wg:oauth:2.0:oob",
        }
        response = requests.post("https://oauth2.googleapis.com/token", data=token_data)
        if response.status_code != 200:
            raise Exception(f"Authentication failed: {response.text}")
        tokens = response.json()
        self.access_token = tokens.get("access_token")
        self.refresh_token = tokens.get("refresh_token")
        with open(self.token_file, "wb") as f:
            pickle.dump(
                {
                    "access_token": self.access_token,
                    "refresh_token": self.refresh_token,
                },
                f,
            )
        print("\n✓ Authentication successful!\n")

    def api_request(self, method: str, url: str, **kwargs) -> Response:
        headers = kwargs.get("headers", {})
        headers["Authorization"] = f"Bearer {self.access_token}"
        kwargs["headers"] = headers
        response = requests.request(method, url, **kwargs)
        if response.status_code == 401 and self.refresh_access_token():
            headers["Authorization"] = f"Bearer {self.access_token}"
            response = requests.request(method, url, **kwargs)
        return response

    def list_files(self, folder_id="root", page_token=None):
        url = "https://www.googleapis.com/drive/v3/files"
        params = {
            "q": f"'{folder_id}' in parents and trashed=false",
            "pageSize": 100,
            "fields": "nextPageToken, files(id, name, mimeType, size, modifiedTime)",
        }
        if page_token:
            params["pageToken"] = page_token
        response = self.api_request("GET", url, params=params)
        if response.status_code != 200:
            print(f"Error listing files: {response.text}")
            return None
        return response.json()

    def get_all_files_recursive(self, folder_id: str = "root"):
        all_items = []
        page_token = None
        while True:
            result = self.list_files(folder_id, page_token)
            if not result:
                break
            items = result.get("files", [])
            all_items.extend(items)
            page_token = result.get("nextPageToken")
            if not page_token:
                break
        return all_items

    def download_file(self, file_id, file_name, local_path) -> bool:
        url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"
        response = self.api_request("GET", url, stream=True)
        if response.status_code != 200:
            print(f"Failed to download {file_name}: {response.text}")
            return False
        total_size = int(response.headers.get("content-length", 0))
        downloaded = 0
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        percent = downloaded / total_size * 40
                        print(
                            f"\rDownloading {file_name}: {percent:.1f}%",
                            end="",
                            flush=True,
                        )
        print(f"\n✓ Downloaded: {file_name}")
        return True

    def get_file_metadata(self, file_id: str):
        url = f"https://www.googleapis.com/drive/v3/files/{file_id}"
        params = {"fields": "id, name, mimeType, size, modifiedTime"}
        response = self.api_request("GET", url, params=params)
        if response.status_code == 200:
            return response.json()
        return None

    def sync_folder(
        self,
        drive_folder_id: str,
        local_folder_path,
        folder_name: str = "root",
        depth=0,
    ) -> None:
        indent = "  " * depth
        print(f"{indent}📁 Syncing: {folder_name}")
        os.makedirs(local_folder_path, exist_ok=True)
        items = self.get_all_files_recursive(drive_folder_id)
        for item in items:
            item_name = item["name"]
            item_id = item["id"]
            item_mime = item.get("mimeType", "")
            local_path = os.path.join(
                local_folder_path, self.sanitize_filename(item_name)
            )
            if item_mime == "application/vnd.google-apps.folder":
                self.sync_folder(item_id, local_path, item_name, depth + 1)
            else:
                remote_modified = item.get("modifiedTime")
                should_download = True
                if os.path.exists(local_path):
                    local_mtime = os.path.getmtime(local_path)
                    if remote_modified:
                        remote_time = datetime.fromisoformat(
                            remote_modified
                        ).timestamp()
                        if local_mtime >= remote_time:
                            should_download = False
                            print(f"{indent}  ⏭ Up to date: {item_name}")
                if (
                    should_download
                    and self.download_file(item_id, item_name, local_path)
                    and remote_modified
                ):
                    mod_time = datetime.fromisoformat(remote_modified).timestamp()
                    os.utime(local_path, (mod_time, mod_time))

    def sanitize_filename(self, filename):
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            filename = filename.replace(char, "_")
        return filename

    def sync_all(self, local_base_path: str) -> None:
        print("\n" + "=" * 40)
        print("STARTING GOOGLE DRIVE SYNC")
        print("-" * 40)
        root_metadata = self.get_file_metadata("root")
        if root_metadata:
            print(f"Root folder: {root_metadata.get('name', 'My Drive')}")
        self.sync_folder("root", local_base_path, "My Drive")
        print("\n" + "=" * 40)
        print("✅ SYNC COMPLETED!")
        print("-" * 40)


def main() -> None:
    LOCAL_SYNC_PATH = "/sdcard/GoogleDriveBackup"
    try:
        syncer = GoogleDriveSync()
        syncer.sync_all(LOCAL_SYNC_PATH)
    except KeyboardInterrupt:
        print("\n\n⚠️ Sync interrupted by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        print("\nTroubleshooting:")
        print("1. Check your internet connection")
        print("2. Verify credentials in ~/.env")
        print("3. Run: termux-setup-storage (for Android storage access)")
        print("4. Check if ~/.env has correct format:")
        print("   GOOGLE_CLIENT_ID=your_id.apps.googleusercontent.com")
        print("   GOOGLE_CLIENT_SECRET=your_secret")


if __name__ == "__main__":
    raise SystemExit(main())
