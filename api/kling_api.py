import requests
import json
import time
import hmac
import hashlib
import base64


def generate_kling_token(access_key: str, secret_key: str) -> str:
    """產生 Kling AI JWT Token"""
    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "HS256", "typ": "JWT"}).encode()
    ).rstrip(b"=").decode()

    payload = base64.urlsafe_b64encode(
        json.dumps({
            "iss": access_key,
            "exp": int(time.time()) + 1800,
            "nbf": int(time.time()) - 5
        }).encode()
    ).rstrip(b"=").decode()

    signature = base64.urlsafe_b64encode(
        hmac.new(
            secret_key.encode(),
            f"{header}.{payload}".encode(),
            hashlib.sha256
        ).digest()
    ).rstrip(b"=").decode()

    return f"{header}.{payload}.{signature}"


def generate_video(
    video_prompt: str,
    kling_access: str,
    kling_secret: str,
    image_base64: str = None,
    progress_callback=None,
    duration: int = 5,
    aspect_ratio: str = "16:9"
) -> str:
    """
    生成影片
    - 有圖片時使用 image2video
    - 無圖片時使用 text2video
    """
    token = generate_kling_token(kling_access, kling_secret)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    has_image = image_base64 is not None and str(image_base64).strip() != ""

    # ✅ 根據是否有圖片選擇不同 API
    if has_image:
        endpoint = "https://api.klingai.com/v1/videos/image2video"
        payload = {
            "model": "kling-v1",
            "image": image_base64,
            "prompt": video_prompt,
            "duration": duration,
            "aspect_ratio": aspect_ratio
        }
        api_type = "image2video"
    else:
        endpoint = "https://api.klingai.com/v1/videos/text2video"
        payload = {
            "model": "kling-v1",
            "prompt": video_prompt,
            "duration": duration,
            "aspect_ratio": aspect_ratio
        }
        api_type = "text2video"

    res = requests.post(endpoint, headers=headers, json=payload, timeout=30)
    res.raise_for_status()
    data = res.json()

    if "data" not in data:
        raise Exception(f"Kling API 回應異常：{data}")

    task_id = data["data"]["task_id"]

    # ✅ 輪詢等待結果
    max_polls = 60
    for i in range(max_polls):
        time.sleep(5)

        # 每次刷新 token 避免過期
        token = generate_kling_token(kling_access, kling_secret)
        headers["Authorization"] = f"Bearer {token}"

        poll = requests.get(
            f"https://api.klingai.com/v1/videos/{api_type}/{task_id}",
            headers=headers,
            timeout=30
        )
        poll.raise_for_status()
        poll_data = poll.json()

        if "data" not in poll_data:
            raise Exception(f"輪詢失敗：{poll_data}")

        status = poll_data["data"]["task_status"]

        if progress_callback:
            progress_callback(i + 1, max_polls, status)

        if status == "succeed":
            return poll_data["data"]["task_result"]["videos"][0]["url"]
        elif status == "failed":
            raise Exception(f"影片生成失敗：{poll_data}")

    raise Exception("影片生成超時（超過 5 分鐘）")
