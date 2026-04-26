import streamlit as st
import requests
import json
import time
import hmac
import hashlib
import base64
from PIL import Image
import io

# ==================== 密碼驗證 ====================
def check_password():
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if not st.session_state.authenticated:
        st.text_input("帳號", key="username")
        st.text_input("密碼", type="password", key="password")
        if st.button("登入"):
            if (st.session_state.username == st.secrets["APP_USERNAME"] and
                st.session_state.password == st.secrets["APP_PASSWORD"]):
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("帳號或密碼錯誤")
        return False
    return True

# ==================== API 金鑰切換 ====================
def get_api_keys():
    mode = st.secrets.get("API_MODE", "main")
    
    if mode == "backup":
        openai_key = st.secrets.get("OPENAI_API_KEY_BACKUP", st.secrets["OPENAI_API_KEY"])
        kling_access = st.secrets.get("KLING_ACCESS_KEY_BACKUP", st.secrets["KLING_ACCESS_KEY"])
        kling_secret = st.secrets.get("KLING_SECRET_KEY_BACKUP", st.secrets["KLING_SECRET_KEY"])
        elevenlabs_key = st.secrets.get("ELEVENLABS_API_KEY_BACKUP", st.secrets["ELEVENLABS_API_KEY"])
    else:
        openai_key = st.secrets["OPENAI_API_KEY"]
        kling_access = st.secrets["KLING_ACCESS_KEY"]
        kling_secret = st.secrets["KLING_SECRET_KEY"]
        elevenlabs_key = st.secrets["ELEVENLABS_API_KEY"]
    
    return openai_key, kling_access, kling_secret, elevenlabs_key

# ==================== 圖片轉 Base64 ====================
def image_to_base64(image_file):
    """將上傳的圖片轉換為 Base64"""
    img = Image.open(image_file)
    buffered = io.BytesIO()
    img.save(buffered, format="PNG")
    img_str = base64.b64encode(buffered.getvalue()).decode()
    return img_str

# ==================== OpenAI 分析（含圖片） ====================
def analyze_prompt(user_input, openai_key, image_base64=None):
    headers = {
        "Authorization": f"Bearer {openai_key}",
        "Content-Type": "application/json"
    }
    
    # 構建訊息內容
    if image_base64:
        content = [
            {
                "type": "text",
                "text": f"""你是影片製作助手。根據使用者描述和上傳的角色圖片，回傳JSON格式：
{{
  "video_prompt": "英文影片場景描述，包含圖片中角色的特徵",
  "narration": "中文旁白文字",
  "music_mood": "音樂情緒關鍵字"
}}

使用者描述：{user_input}

請根據圖片中的角色特徵（如外貌、服裝、風格等）融入影片提示詞中。"""
            },
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{image_base64}"
                }
            }
        ]
    else:
        content = f"""你是影片製作助手。根據使用者描述，回傳JSON格式：
{{
  "video_prompt": "英文影片場景描述",
  "narration": "中文旁白文字",
  "music_mood": "音樂情緒關鍵字"
}}"""
    
    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {
                "role": "system",
                "content": "你是專業的影片製作助手。"
            },
            {
                "role": "user",
                "content": content
            }
        ]
    }
    
    res = requests.post("https://api.openai.com/v1/chat/completions",
                        headers=headers, json=payload)
    response_data = res.json()
    
    if "error" in response_data:
        raise Exception(f"OpenAI 錯誤：{response_data['error']['message']}")
    
    content_response = response_data["choices"][0]["message"]["content"]
    content_response = content_response.strip().strip("```json").strip("```").strip()
    return json.loads(content_response)

# ==================== Kling JWT ====================
def generate_kling_token(access_key, secret_key):
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

# ==================== Kling 生成影片 ====================
def generate_video(video_prompt, kling_access, kling_secret):
    token = generate_kling_token(kling_access, kling_secret)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "kling-v1",
        "prompt": video_prompt,
        "duration": 5,
        "aspect_ratio": "16:9"
    }
    res = requests.post(
        "https://api.klingai.com/v1/videos/text2video",
        headers=headers, json=payload
    )
    
    # ✅ 檢查回應
    data = res.json()
    
    # ✅ 錯誤處理
    if "code" in data or "error" in data:
        raise Exception(f"Kling API 錯誤：{data}")
    
    if "data" not in data:
        raise Exception(f"Kling API 回應異常：{data}")
    
    task_id = data["data"]["task_id"]
    
    # 輪詢等待結果
    for i in range(60):
        time.sleep(5)
        token = generate_kling_token(kling_access, kling_secret)
        headers["Authorization"] = f"Bearer {token}"
        poll = requests.get(
            f"https://api.klingai.com/v1/videos/text2video/{task_id}",
            headers=headers
        )
        poll_data = poll.json()
        
        # ✅ 檢查輪詢回應
        if "data" not in poll_data:
            raise Exception(f"輪詢失敗：{poll_data}")
        
        status = poll_data["data"]["task_status"]
        if status == "succeed":
            return poll_data["data"]["task_result"]["videos"][0]["url"]
        elif status == "failed":
            raise Exception("影片生成失敗")
    
    raise Exception("影片生成超時")

# ==================== ElevenLabs 語音 ====================
def generate_voice(narration, elevenlabs_key):
    headers = {
        "xi-api-key": elevenlabs_key,
        "Content-Type": "application/json"
    }
    payload = {
        "text": narration,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}
    }
    res = requests.post(
        "https://api.elevenlabs.io/v1/text-to-speech/21m00Tcm4TlvDq8ikWAM",
        headers=headers, json=payload
    )
    return res.content

# ==================== 主介面 ====================
def main():
    st.set_page_config(page_title="AI 影片生成器", page_icon="🎬", layout="wide")
    
    if not check_password():
        return
    
    st.title("🎬 AI 影片生成器")
    
    # 顯示目前 API 模式
    mode = st.secrets.get("API_MODE", "main")
    st.caption(f"目前 API 模式：{'🟢 主要' if mode == 'main' else '🟡 備用'}")
    
    # 分為兩欄
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.subheader("📝 影片描述")
        user_input = st.text_area("描述你想要的影片內容", 
                                   placeholder="例如：夕陽下的海邊，海浪輕拍岸邊，氣氛寧靜祥和",
                                   height=150)
    
    with col2:
        st.subheader("📸 角色圖片（選填）")
        uploaded_image = st.file_uploader("上傳角色照片", 
                                         type=["jpg", "jpeg", "png"],
                                         help="上傳一張角色照片，AI 將把角色特徵融入影片中")
        
        if uploaded_image:
            st.image(uploaded_image, caption="已上傳的角色圖片", use_column_width=True)
    
    # 生成按鈕
    if st.button("🚀 開始生成", type="primary", use_container_width=True):
        if not user_input:
            st.warning("請輸入影片描述")
            return
        
        openai_key, kling_access, kling_secret, elevenlabs_key = get_api_keys()
        
        # 轉換圖片為 Base64
        image_base64 = None
        if uploaded_image:
            image_base64 = image_to_base64(uploaded_image)
        
        # 分析階段
        with st.spinner("🤖 AI 分析中..."):
            try:
                result = analyze_prompt(user_input, openai_key, image_base64)
                st.success("✅ 分析完成")
                st.json(result)
            except Exception as e:
                st.error(f"分析失敗：{e}")
                return
        
        # 影片生成階段
        with st.spinner("🎬 影片生成中（約需 2-3 分鐘）..."):
            try:
                video_url = generate_video(result["video_prompt"], kling_access, kling_secret)
                st.success("✅ 影片生成完成")
                st.video(video_url)
            except Exception as e:
                st.error(f"影片生成錯誤：{e}")
                return
        
        # 語音生成階段
        with st.spinner("🎙️ 語音生成中..."):
            try:
                audio = generate_voice(result["narration"], elevenlabs_key)
                st.success("✅ 語音生成完成")
                st.audio(audio, format="audio/mp3")
            except Exception as e:
                st.error(f"語音生成錯誤：{e}")

if __name__ == "__main__":
    main()
