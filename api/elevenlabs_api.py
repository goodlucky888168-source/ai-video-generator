import requests
import streamlit as st

def generate_voice(text: str, api_key: str, voice_id: str = None) -> bytes:
    """
    使用 ElevenLabs 生成語音
    
    Args:
        text: 要轉語音的文本
        api_key: ElevenLabs API 金鑰
        voice_id: 語音 ID (可選)
    
    Returns:
        音訊位元組
    """
    
    # ✅ 使用默認語音 ID
    if not voice_id or voice_id.strip() == "":
        voice_id = "21m00Tcm4TlvDq8ikWAM"
    
    # ✅ 清理輸入
    api_key = (api_key or "").strip()
    text = (text or "").strip()
    
    if not api_key:
        raise ValueError("❌ ElevenLabs API 金鑰未設定")
    
    if not text:
        raise ValueError("❌ 文本內容為空")
    
    # ✅ 正確的 API 端點
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json"
    }
    
    payload = {
        "text": text,
        "model_id": "eleven_monolingual_v1",
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75
        }
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        
        # ✅ 詳細的錯誤處理
        if response.status_code == 401:
            raise Exception("❌ API 金鑰無效或已過期")
        elif response.status_code == 404:
            raise Exception(f"❌ 語音 ID '{voice_id}' 不存在")
        elif response.status_code == 429:
            raise Exception("❌ 請求過於頻繁，請稍後再試")
        elif response.status_code >= 500:
            raise Exception(f"❌ ElevenLabs 服務器錯誤：{response.status_code}")
        
        response.raise_for_status()
        return response.content
    
    except requests.exceptions.Timeout:
        raise Exception("❌ 請求超時，請檢查網路")
    except requests.exceptions.ConnectionError:
        raise Exception("❌ 無法連接到 ElevenLabs")
    except Exception as e:
        raise Exception(f"❌ ElevenLabs 錯誤：{str(e)}")
