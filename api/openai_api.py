import requests
import json
from PIL import Image
import io
import base64

def image_to_base64(image_file) -> str:
    """將上傳的圖片安全轉換為 Base64"""
    with Image.open(image_file) as img:
        # 統一轉為 RGB 避免 RGBA PNG 問題
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        buffered = io.BytesIO()
        img.save(buffered, format="JPEG", quality=85)
        return base64.b64encode(buffered.getvalue()).decode()

def analyze_prompt(user_input: str, openai_key: str, image_base64: str = None) -> dict:
    """
    使用 GPT-4o-mini 分析使用者描述，回傳結構化 JSON
    包含：video_prompt, narration, music_mood, music_genre
    """
    headers = {
        "Authorization": f"Bearer {openai_key}",
        "Content-Type": "application/json"
    }

    system_prompt = "你是專業的影片製作助手，只回傳 JSON，不加任何說明文字。"

    if image_base64:
        user_content = [
            {
                "type": "text",
                "text": f"""根據使用者描述和上傳的角色圖片，回傳以下 JSON 格式（不要加 markdown code block）：
{{
  "video_prompt": "詳細英文影片場景描述，包含圖片中角色的外貌、服裝、風格特徵",
  "narration": "中文旁白文字（適合朗讀，約50字）",
  "music_mood": "英文情緒描述，例如：calm, energetic, mysterious",
  "music_genre": "英文音樂風格，例如：ambient, cinematic, jazz"
}}

使用者描述：{user_input}

請仔細觀察圖片中角色特徵並融入 video_prompt。"""
            },
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{image_base64}"
                }
            }
        ]
    else:
        user_content = f"""根據使用者描述，回傳以下 JSON 格式（不要加 markdown code block）：
{{
  "video_prompt": "詳細英文影片場景描述",
  "narration": "中文旁白文字（適合朗讀，約50字）",
  "music_mood": "英文情緒描述，例如：calm, energetic, mysterious",
  "music_genre": "英文音樂風格，例如：ambient, cinematic, jazz"
}}

使用者描述：{user_input}"""

    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_content}
        ],
        "temperature": 0.7
    }

    res = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers=headers,
        json=payload,
        timeout=30
    )
    data = res.json()

    if "error" in data:
        raise Exception(f"OpenAI 錯誤：{data['error']['message']}")

    raw = data["choices"][0]["message"]["content"].strip()
    # 清除可能的 markdown code block
    raw = raw.replace("```json", "").replace("```", "").strip()

    return json.loads(raw)

