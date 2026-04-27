import requests
import time

def generate_music(
    music_mood: str,
    music_genre: str,
    beatoven_key: str,
    duration: int = 30,
    progress_callback=None
) -> bytes:
    """
    使用 Beatoven.ai 生成背景音樂
    回傳音樂的 bytes 內容
    """
    headers = {
        "Authorization": f"Bearer {beatoven_key}",
        "Content-Type": "application/json"
    }

    # Step 1：建立音樂任務
    payload = {
        "title":    f"AI Generated - {music_mood}",
        "duration": duration * 1000,  # Beatoven 使用毫秒
        "genre":    music_genre,
        "mood":     music_mood,
        "tempo":    "medium"
    }

    res = requests.post(
        "https://public-api.beatoven.ai/api/v1/tracks",
        headers=headers,
        json=payload,
        timeout=30
    )

    if res.status_code not in (200, 201):
        raise Exception(f"Beatoven 建立任務失敗：{res.status_code} - {res.text}")

    track_data = res.json()
    track_id = track_data.get("id") or track_data.get("track_id")

    if not track_id:
        raise Exception(f"Beatoven 回應無 track_id：{track_data}")

    # Step 2：觸發生成
    compose_res = requests.post(
        f"https://public-api.beatoven.ai/api/v1/tracks/{track_id}/compose",
        headers=headers,
        timeout=30
    )

    if compose_res.status_code not in (200, 201, 202):
        raise Exception(f"Beatoven 生成觸發失敗：{compose_res.text}")

    # Step 3：輪詢等待完成
    max_polls = 40
    for i in range(max_polls):
        time.sleep(5)

        status_res = requests.get(
            f"https://public-api.beatoven.ai/api/v1/tracks/{track_id}",
            headers=headers,
            timeout=30
        )
        status_data = status_res.json()
        status = status_data.get("status", "")

        if progress_callback:
            progress_callback(i + 1, max_polls, status)

        if status == "composed":
            # Step 4：下載音樂
            download_url = status_data.get("download_url") or status_data.get("url")
            if not download_url:
                raise Exception("Beatoven 無下載連結")

            music_res = requests.get(download_url, timeout=60)
            return music_res.content

        elif status in ("failed", "error"):
            raise Exception(f"Beatoven 音樂生成失敗：{status_data}")

    raise Exception("Beatoven 音樂生成超時")

