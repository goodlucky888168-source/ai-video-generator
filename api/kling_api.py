import requests
import json
import time
import base64
import streamlit as st
from typing import Optional, Callable

class KlingAPIError(Exception):
    """Kling API 錯誤"""
    pass

def generate_video(
    prompt: str,
    access_key: str,
    secret_key: str,
    image_b64: Optional[str] = None,
    progress_callback: Optional[Callable] = None,
    duration: int = 5,
    aspect_ratio: str = "16:9"
) -> str:
    """
    使用 Kling AI 生成影片
    
    Args:
        prompt: 影片描述提示詞
        access_key: Kling Access Key
        secret_key: Kling Secret Key
        image_b64: Base64 編碼的參考圖片 (可選)
        progress_callback: 進度回調函數
        duration: 影片時長 (3-60 秒)
        aspect_ratio: 寬高比 ("16:9", "9:16", "1:1")
    
    Returns:
        影片 URL
    """
    
    # ✅ 驗證輸入
    if not access_key or not secret_key:
        raise KlingAPIError("❌ Kling API 金鑰未設定")
    
    if not prompt or not prompt.strip():
        raise KlingAPIError("❌ 提示詞不能為空")
    
    # ✅ 驗證參數
    if not (3 <= duration <= 60):
        duration = min(max(duration, 3), 60)
    
    valid_ratios = ["16:9", "9:16", "1:1"]
    if aspect_ratio not in valid_ratios:
        aspect_ratio = "16:9"
    
    try:
        # ✅ 準備請求
        access_key = access_key.strip()
        secret_key = secret_key.strip()
        prompt = prompt.strip()
        
        # ✅ 構建請求頭
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_key}",
        }
        
        # ✅ 構建請求體
        payload = {
            "model": "kling-v1",
            "prompt": prompt,
            "duration": duration,
            "aspect_ratio": aspect_ratio,
            "negative_prompt": "",
        }
        
        # ✅ 如果有參考圖片，添加到請求
        if image_b64:
            try:
                # 驗證 Base64 格式
                if not image_b64.startswith("data:image"):
                    # 如果沒有 data URI 前綴，添加一個
                    image_b64 = f"data:image/jpeg;base64,{image_b64}"
                
                payload["image"] = image_b64
                payload["mode"] = "image2video"  # 使用圖片到影片模式
            except Exception as e:
                st.warning(f"⚠️ 圖片處理失敗，將使用文字到影片模式：{str(e)}")
        
        st.write(f"🔧 調試信息：")
        st.write(f"- API 端點: https://api.klingai.com/v1/videos/image2video")
        st.write(f"- 模型: {payload.get('model')}")
        st.write(f"- 時長: {duration} 秒")
        st.write(f"- 寬高比: {aspect_ratio}")
        st.write(f"- 模式: {payload.get('mode', 'text2video')}")
        
        # ✅ 發送請求
        url = "https://api.klingai.com/v1/videos/image2video"
        
        response = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=60
        )
        
        # ✅ 詳細的錯誤處理
        if response.status_code == 400:
            error_detail = response.json().get("error", {}).get("message", "未知錯誤")
            raise KlingAPIError(f"❌ 請求格式錯誤：{error_detail}\n\n請檢查：\n- API 金鑰是否正確\n- 提示詞是否過長\n- 圖片格式是否正確")
        
        elif response.status_code == 401:
            raise KlingAPIError("❌ 認證失敗：API 金鑰無效或已過期")
        
        elif response.status_code == 403:
            raise KlingAPIError("❌ 無權限：帳戶可能已被禁用或額度已用完")
        
        elif response.status_code == 429:
            raise KlingAPIError("❌ 請求過於頻繁，請稍後再試")
        
        elif response.status_code >= 500:
            raise KlingAPIError(f"❌ Kling 服務器錯誤：{response.status_code}")
        
        response.raise_for_status()
        
        # ✅ 解析回應
        result = response.json()
        
        # 檢查是否包含影片 URL
        if "data" in result and "video_url" in result["data"]:
            return result["data"]["video_url"]
        elif "video_url" in result:
            return result["video_url"]
        elif "url" in result:
            return result["url"]
        else:
            raise KlingAPIError(f"❌ 回應格式錯誤：{json.dumps(result)}")
    
    except requests.exceptions.Timeout:
        raise KlingAPIError("❌ 請求超時，請檢查網路連接")
    
    except requests.exceptions.ConnectionError:
        raise KlingAPIError("❌ 無法連接到 Kling API，請檢查網路")
    
    except KlingAPIError:
        raise
    
    except Exception as e:
        raise KlingAPIError(f"❌ Kling API 錯誤：{str(e)}")
