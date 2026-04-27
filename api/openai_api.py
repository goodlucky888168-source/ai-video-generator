import openai
import base64
import json
import re


def image_to_base64(image_input) -> str:
    """
    將圖片轉換為 base64 字串
    支援 Streamlit UploadedFile 或檔案路徑
    """
    if hasattr(image_input, "read"):
        # Streamlit UploadedFile
        image_input.seek(0)
        data = image_input.read()
    else:
        # 檔案路徑
        with open(image_input, "rb") as f:
            data = f.read()
    return base64.b64encode(data).decode("utf-8")


def analyze_prompt(user_input: str, openai_key: str, image_base64: str = None) -> dict:
    """
    使用 GPT 分析使用者輸入，回傳結構化 JSON

    回傳格式：
    {
        "video_prompt": "英文影片描述",
        "narration": "中文旁白",
        "music_mood": "calm",
        "music_genre": "ambient",
        "storyboard": [...]   ← 分鏡模式時才有
    }
    """
    client = openai.OpenAI(api_key=openai_key)

    messages = [
        {
            "role": "system",
            "content": (
                "你是專業的影片製作助理。"
                "請根據使用者的輸入，回傳 JSON 格式的影片製作指令。"
                "只回傳純 JSON，不要加 markdown code block，不要加任何說明文字。"
            )
        }
    ]

    # 組合使用者訊息
    if image_base64:
        messages.append({
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        f"{user_input}\n\n"
                        "請回傳以下 JSON 格式：\n"
                        "{\n"
                        '  "video_prompt": "英文影片描述（詳細場景、光線、氛圍）",\n'
                        '  "narration": "中文旁白（30字以內）",\n'
                        '  "music_mood": "calm 或 happy 或 sad 或 epic 或 romantic",\n'
                        '  "music_genre": "ambient 或 cinematic 或 pop 或 jazz"\n'
                        "}"
                    )
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{image_base64}"
                    }
                }
            ]
        })
    else:
        messages.append({
            "role": "user",
            "content": (
                f"{user_input}\n\n"
                "請回傳以下 JSON 格式：\n"
                "{\n"
                '  "video_prompt": "英文影片描述（詳細場景、光線、氛圍）",\n'
                '  "narration": "中文旁白（30字以內）",\n'
                '  "music_mood": "calm 或 happy 或 sad 或 epic 或 romantic",\n'
                '  "music_genre": "ambient 或 cinematic 或 pop 或 jazz",\n'
                '  "storyboard": [\n'
                "    {\n"
                '      "scene": "英文場景描述",\n'
                '      "characters": ["A"],\n'
                '      "duration": 5,\n'
                '      "narration": "中文旁白"\n'
                "    }\n"
                "  ]\n"
                "}"
            )
        })

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        max_tokens=1500,
        temperature=0.7
    )

    raw = response.choices[0].message.content.strip()

    # 清除可能的 markdown code block（更穩）
    raw = re.sub(r"^\s*```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```\s*$", "", raw)
    raw = raw.strip()

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        # 嘗試擷取 JSON 區塊
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            result = json.loads(match.group())
        else:
            # 回傳預設值避免崩潰
            result = {
                "video_prompt": user_input,
                "narration": "精彩的影片內容",
                "music_mood": "calm",
                "music_genre": "ambient",
                "storyboard": []
            }

    return result
