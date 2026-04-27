import requests

def generate_voice(narration: str, elevenlabs_key: str, voice_id: str) -> bytes:
    """使用 ElevenLabs 生成語音"""
    headers = {
        "xi-api-key": elevenlabs_key,
        "Content-Type": "application/json"
    }
    payload = {
        "text": narration,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75
        }
    }
    res = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
        headers=headers,
        json=payload,
        timeout=30
    )

    if res.status_code != 200:
        raise Exception(f"ElevenLabs 錯誤：{res.status_code} - {res.text}")

    return res.content

