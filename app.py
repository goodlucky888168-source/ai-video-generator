import streamlit as st
import requests
import time
import base64
import json
import hmac
import hashlib
from datetime import datetime

# ==================== 密碼保護 ====================
def check_password():
    def password_entered():
        if (st.session_state["username"] == st.secrets["APP_USERNAME"] and
                st.session_state["password"] == st.secrets["APP_PASSWORD"]):
            st.session_state["password_correct"] = True
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.text_input("帳號", key="username")
        st.text_input("密碼", type="password", key="password")
        st.button("登入", on_click=password_entered)
        return False
    elif not st.session_state["password_correct"]:
        st.text_input("帳號", key="username")
        st.text_input("密碼", type="password", key="password")
        st.button("登入", on_click=password_entered)
        st.error("帳號或密碼錯誤！")
        return False
    else:
        return True

if not check_password():
    st.stop()

# ==================== 主程式 ====================
st.title("🎬 AI 自動影片生成器")
st.write("輸入場景描述，自動生成影片、旁白與配樂")

# 輸入區
prompt = st.text_area("場景描述", placeholder="例如：一個女孩在雨中哭泣，背景是城市夜景")
duration = st.slider("影片長度（秒）", min_value=5, max_value=30, value=5)

if st.button("🚀 開始生成", type="primary"):
    if not prompt:
        st.error("請輸入場景描述！")
    else:
        # Step 1: OpenAI 分析場景
        with st.spinner("🤖 AI 分析場景中..."):
            try:
                openai_headers = {
                    "Authorization": f"Bearer {st.secrets['OPENAI_API_KEY']}",
                    "Content-Type": "application/json"
                }
                openai_body = {
                    "model": "gpt-4o-mini",
                    "messages": [
                        {
                            "role": "system",
                            "content": "你是一個影片製作助手。根據場景描述，用繁體中文回傳JSON格式：{\"video_prompt\": \"英文的影片生成提示\", \"narration\": \"旁白文字（繁體中文）\", \"music_mood\": \"音樂情緒（英文，例如：sad, happy, epic, calm）\"}"
                        },
                        {"role": "user", "content": prompt}
                    ]
                }
                openai_res = requests.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers=openai_headers,
                    json=openai_body
                )
                analysis = json.loads(openai_res.json()["choices"][0]["message"]["content"])
                st.success(f"✅ 場景分析完成")
                st.info(f"📝 旁白：{analysis['narration']}")
                st.info(f"🎵 音樂情緒：{analysis['music_mood']}")
            except Exception as e:
                st.error(f"OpenAI 錯誤：{e}")
                st.stop()

        # Step 2: Kling AI 生成影片
        with st.spinner("🎬 影片生成中（約需1-3分鐘）..."):
            try:
                def generate_kling_token(ak, sk):
                    header = base64.b64encode(json.dumps({"alg":"HS256","typ":"JWT"}).encode()).decode().rstrip("=")
                    payload = base64.b64encode(json.dumps({"iss":ak,"exp":int(time.time())+1800,"nbf":int(time.time())-5}).encode()).decode().rstrip("=")
                    sig = base64.b64encode(hmac.new(sk.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()).decode().rstrip("=")
                    return f"{header}.{payload}.{sig}"

                kling_token = generate_kling_token(
                    st.secrets["KLING_ACCESS_KEY"],
                    st.secrets["KLING_SECRET_KEY"]
                )
                kling_headers = {"Authorization": f"Bearer {kling_token}", "Content-Type": "application/json"}
                kling_body = {
                    "model": "kling-v1",
                    "prompt": analysis["video_prompt"],
                    "duration": str(duration),
                    "aspect_ratio": "16:9"
                }
                kling_res = requests.post(
                    "https://api.klingai.com/v1/videos/text2video",
                    headers=kling_headers,
                    json=kling_body
                )
                task_id = kling_res.json()["data"]["task_id"]

                # 等待影片完成
                video_url = None
                for i in range(60):
                    time.sleep(5)
                    check_res = requests.get(
                        f"https://api.klingai.com/v1/videos/text2video/{task_id}",
                        headers=kling_headers
                    )
                    status = check_res.json()["data"]["task_status"]
                    if status == "succeed":
                        video_url = check_res.json()["data"]["task_result"]["videos"][0]["url"]
                        break
                    elif status == "failed":
                        st.error("影片生成失敗")
                        st.stop()

                if video_url:
                    st.success("✅ 影片生成完成")
                    st.video(video_url)
            except Exception as e:
                st.error(f"Kling AI 錯誤：{e}")
                st.stop()

        # Step 3: ElevenLabs 生成旁白
        with st.spinner("🎙️ 旁白生成中..."):
            try:
                eleven_headers = {
                    "xi-api-key": st.secrets["ELEVENLABS_API_KEY"],
                    "Content-Type": "application/json"
                }
                eleven_body = {
                    "text": analysis["narration"],
                    "model_id": "eleven_multilingual_v2",
                    "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}
                }
                eleven_res = requests.post(
                    "https://api.elevenlabs.io/v1/text-to-speech/21m00Tcm4TlvDq8ikWAM",
                    headers=eleven_headers,
                    json=eleven_body
                )
                audio_bytes = eleven_res.content
                st.success("✅ 旁白生成完成")
                st.audio(audio_bytes, format="audio/mpeg")
            except Exception as e:
                st.error(f"ElevenLabs 錯誤：{e}")

        st.balloons()
        st.success("🎉 全部完成！")
