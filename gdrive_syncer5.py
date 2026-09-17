#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
import pickle
import time
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
            try:
                with open(self.token_file, "rb") as f:
                    data = pickle.load(f)
                    self.access_token = data.get("access_token")
                    self.refresh_token = data.get("refresh_token")
                    if self.access_token:
                        return
            except:
                pass
        self.authenticate()

    def refresh_access_token(self) -> bool:
        if not self.refresh_token:
            return False
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
            "grant_type": "refresh_token",
        }
        try:
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
        except Exception as e:
            print(f"Token refresh error: {e}")
        return False

    def authenticate_device_flow(self) -> None:
        print("\n" + "=" * 40)
        print("GOOGLE DRIVE AUTHENTICATION (Device Flow)")
        print("-" * 40)
        device_data = {
            "client_id": self.client_id,
            "scope": "https://www.googleapis.com/auth/drive.readonly",
        }
        try:
            response = requests.post(
                "https://oauth2.googleapis.com/device/code",
                data=device_data,
                timeout=10,
            )
            if response.status_code != 200:
                raise Exception(f"Failed to get device code: {response.text}")
            device_info = response.json()
            print(f"\n1. Open this URL: {device_info['verification_url']}")
            print(f"2. Enter this code: {device_info['user_code']}")
            print("\nWaiting for you to authorize...")
            print("(This may take up to 5 minutes)")
            poll_data = {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "device_code": device_info["device_code"],
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            }
            interval = device_info.get("interval", 5)
            max_attempts = 60
            for attempt in range(max_attempts):
                time.sleep(interval)
                try:
                    token_response = requests.post(
                        "https://oauth2.googleapis.com/token",
                        data=poll_data,
                        timeout=10,
                    )
                    if token_response.status_code == 200:
                        token_data = token_response.json()
                        self.access_token = token_data.get("access_token")
                        self.refresh_token = token_data.get("refresh_token")
                        with open(self.token_file, "wb") as f:
                            pickle.dump(
                                {
                                    "access_token": self.access_token,
                                    "refresh_token": self.refresh_token,
                                },
                                f,
                            )
                        print("\n✓ Authentication successful!\n")
                        return
                    error_data = token_response.json()
                    error = error_data.get("error")
                    if error == "authorization_pending":
                        if attempt % 5 == 0:
                            print("Still waiting for authorization...")
                        continue
                    elif error == "slow_down":
                        interval += 1
                        continue
                    elif error == "expired_token":
                        raise Exception("Device code expired. Please try again.")
                    else:
                        raise Exception(f"Authentication error: {error}")
                except Exception as e:
                    if "expired" in str(e).lower():
                        raise
                    print(f"Polling error (will retry): {e}")
                    continue
            raise Exception("Timeout waiting for authorization")
        except Exception as e:
            raise Exception(f"Device flow authentication failed: {e}")

    def authenticate_manual_flow(self) -> None:
        print("\n" + "=" * 40)
        print("GOOGLE DRIVE AUTHENTICATION (Manual Flow)")
        print("-" * 40)
        redirect_uri = "http://localhost:8080"
        auth_url = f"https://accounts.google.com/o/oauth2/auth?client_id={
            self.client_id
        }&redirect_uri={
            redirect_uri
        }&response_type=code&scope=https://www.googleapis.com/auth/drive.readonly&access_type=offline&prompt=consent"
        print("\n" + "=" * 40)
        print("OPTION 1 (Recommended): Localhost Redirect")
        print("-" * 40)
        print("\nOpen this URL in your browser on this device:")
        print(f"\n{auth_url}\n")
        print("After authorization, you'll be redirected to localhost:8080")
        print("Copy the ENTIRE URL from the address bar (it will show an error page)")
        print("\n" + "=" * 40)
        print("OPTION 2: Manual Code Entry")
        print("-" * 40)
        print("If Option 1 doesn't work, try this URL instead:")
        print(f"\n{altauth_url}\n")
        input("\nPress Enter after you have the authorization code or redirect URL...")
        auth_input = input("\nEnter the full redirect URL or auth code: ").strip()
        if "code=" in auth_input:
            code_start = auth_input.find("code=") + 5
            code_end = auth_input.find("&", code_start)
            if code_end == -1:
                auth_code = auth_input[code_start:]
            else:
                auth_code = auth_input[code_start:code_end]
        else:
            auth_code = auth_input
        token_data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": auth_code,
            "grant_type": "authorization_code",
            "redirect_uri": "http://localhost:8080",
        }
        response = requests.post("https://oauth2.googleapis.com/token", data=token_data)
        if response.status_code != 200:
            token_data["redirect_uri"] = "urn:ietf:wg:oauth:2.0:oob"
            response = requests.post(
                "https://oauth2.googleapis.com/token", data=token_data
            )
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

    def authenticate(self) -> None:
        try:
            self.authenticate_device_flow()
        except Exception as e:
            print(f"\nDevice flow failed: {e}")
            print("Falling back to manual authentication...")
            try:
                self.authenticate_manual_flow()
            except Exception as e2:
                raise Exception(
                    f"All authentication methods failed. Device: {e}, Manual: {e2}"
                )

    def api_request(self, method: str, url: str, **kwargs) -> Response:
        headers = kwargs.get("headers", {})
        headers["Authorization"] = f"Bearer {self.access_token}"
        kwargs["headers"] = headers
        response = requests.request(method, url, **kwargs)
        if response.status_code == 401 and self.refresh_access_token():
            headers["Authorization"] = f"Bearer {self.access_token}"
            kwargs["headers"] = headers
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
        os.makedirs(
            os.path.dirname(local_path) if os.path.dirname(local_path) else ".",
            exist_ok=True,
        )
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

    def sync_folder_by_name(self, folder_name, local_base_path) -> None:
        print(f"\nSearching for folder: {folder_name}")
        items = self.get_all_files_recursive("root")
        target_folder = None
        for item in items:
            if (
                item["name"] == folder_name
                and item["mimeType"] == "application/vnd.google-apps.folder"
            ):
                target_folder = item
                break
        if target_folder:
            local_path = os.path.join(local_base_path, folder_name)
            self.sync_folder(target_folder["id"], local_path, folder_name)
        else:
            print(f"❌ Folder '{folder_name}' not found in root directory")


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
        print("3. Delete drive_token.pkl and try again")
        print("4. Make sure you enabled the Drive API in Google Cloud Console")
        print("5. Check if ~/.env has correct format:")
        print("   GOOGLE_CLIENT_ID=your_id.apps.googleusercontent.com")
        print("   GOOGLE_CLIENT_SECRET=your_secret")


if __name__ == "__main__":
    raise SystemExit(main())
