import json
import io
import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

SCOPES = ["https://www.googleapis.com/auth/drive.file"]

def get_drive_service(sa_json_str: str):
    """從 JSON 字串建立 Google Drive 服務"""
    sa_info = json.loads(sa_json_str)
    credentials = service_account.Credentials.from_service_account_info(
        sa_info, scopes=SCOPES
    )
    return build("drive", "v3", credentials=credentials)


def upload_to_drive(
    content: bytes,
    filename: str,
    mimetype: str,
    folder_id: str,
    sa_json_str: str
) -> str:
    """
    上傳檔案至 Google Drive 指定資料夾
    回傳可分享的檔案連結
    """
    service = get_drive_service(sa_json_str)

    file_metadata = {
        "name": filename,
        "parents": [folder_id]
    }

    media = MediaIoBaseUpload(
        io.BytesIO(content),
        mimetype=mimetype,
        resumable=True
    )

    file = service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id, webViewLink"
    ).execute()

    # 設定公開讀取權限
    service.permissions().create(
        fileId=file["id"],
        body={"type": "anyone", "role": "reader"}
    ).execute()

    return file.get("webViewLink", "")


def upload_video_from_url(
    video_url: str,
    filename: str,
    folder_id: str,
    sa_json_str: str
) -> str:
    """從 URL 下載影片後上傳至 Google Drive"""
    res = requests.get(video_url, timeout=120)
    if res.status_code != 200:
        raise Exception(f"影片下載失敗：{res.status_code}")

    return upload_to_drive(
        content=res.content,
        filename=filename,
        mimetype="video/mp4",
        folder_id=folder_id,
        sa_json_str=sa_json_str
    )

