import streamlit as st
import time
import concurrent.futures
from config import get_api_keys
from api.openai_api import analyze_prompt, image_to_base64
from api.kling_api import generate_video
from api.elevenlabs_api import generate_voice
from api.beatoven_api import generate_music
from api.gdrive_api import upload_to_drive, upload_video_from_url

# ==================== 密碼驗證 ====================
def check_password() -> bool:
    if st.session_state.get("authenticated"):
        return True

    st.markdown("## 🔐 請登入")

    col1, col2 = st.columns([1, 2])
    with col1:
        username = st.text_input("帳號", key="login_username")
        password = st.text_input("密碼", type="password", key="login_password")

        # ✅ 防暴力破解：限制嘗試次數
        if "login_attempts" not in st.session_state:
            st.session_state.login_attempts = 0
        if "lockout_until" not in st.session_state:
            st.session_state.lockout_until = 0

        now = time.time()
        is_locked = now < st.session_state.lockout_until

        if is_locked:
            remaining = int(st.session_state.lockout_until - now)
            st.error(f"⛔ 嘗試次數過多，請等待 {remaining} 秒後再試")
            return False

        if st.button("登入", type="primary"):
            if (username == st.secrets.get("APP_USERNAME") and
                    password == st.secrets.get("APP_PASSWORD")):
                st.session_state.authenticated = True
                st.session_state.login_attempts = 0
                st.rerun()
            else:
                st.session_state.login_attempts += 1
                attempts = st.session_state.login_attempts
                st.error(f"帳號或密碼錯誤（第 {attempts} 次）")

                # 超過 5 次鎖定 60 秒
                if attempts >= 5:
                    st.session_state.lockout_until = now + 60
                    st.session_state.login_attempts = 0
                    st.rerun()

    return False


# ==================== API 金鑰設定面板 ====================
def render_api_settings(keys: dict):
    """欄位式 API 金鑰顯示（唯讀，方便確認）"""
    with st.expander("⚙️ API 金鑰設定狀態", expanded=False):
        st.caption(f"目前模式：{'🟢 主要 (main)' if keys['mode'] == 'main' else '🟡 備用 (backup)'}")
        st.caption("如需切換模式，請至 Streamlit Cloud → Secrets 修改 `API_MODE`")

        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**金鑰名稱**")
            key_names = ["OpenAI", "Kling Access", "Kling Secret",
                         "ElevenLabs", "Beatoven", "Google Drive Folder"]
        with col2:
            st.markdown("**狀態**")

        key_map = {
            "OpenAI":              keys["openai"],
            "Kling Access":        keys["kling_access"],
            "Kling Secret":        keys["kling_secret"],
            "ElevenLabs":          keys["elevenlabs"],
            "Beatoven":            keys["beatoven"],
            "Google Drive Folder": keys["gdrive_folder"],
        }

        for name, val in key_map.items():
            col1, col2 = st.columns(2)
            with col1:
                st.text(name)
            with col2:
                if val:
                    masked = val[:4] + "****" + val[-4:] if len(val) > 8 else "****"
                    st.success(f"✅ {masked}")
                else:
                    st.error("❌ 未設定")


# ==================== 主介面 ====================
def main():
    st.set_page_config(
        page_title="AI 影片生成器",
        page_icon="🎬",
        layout="wide"
    )

    if not check_password():
        return

    st.title("🎬 AI 影片生成器")
    st.caption("整合 OpenAI · Kling AI · ElevenLabs · Beatoven.ai · Google Drive")

    keys = get_api_keys()
    render_api_settings(keys)

    st.divider()

    # ==================== 輸入區 ====================
    col_input, col_image = st.columns([2, 1])

    with col_input:
        st.subheader("📝 影片描述")
        user_input = st.text_area(
            "描述你想要的影片內容",
            placeholder="例如：夕陽下的海邊，海浪輕拍岸邊，氣氛寧靜祥和...",
            height=160,
            key="user_input"
        )

        col_opt1, col_opt2 = st.columns(2)
        with col_opt1:
            video_duration = st.selectbox("影片長度", [5, 10], index=0, key="duration")
        with col_opt2:
            aspect_ratio = st.selectbox("畫面比例", ["16:9", "9:16", "1:1"], index=0)

    with col_image:
        st.subheader("📸 角色圖片（選填）")
        uploaded_image = st.file_uploader(
            "上傳角色照片",
            type=["jpg", "jpeg", "png"],
            help="上傳圖片後將使用 image2video API，角色一致性更佳"
        )
        if uploaded_image:
            st.image(uploaded_image, caption="已上傳角色圖片", use_container_width=True)
            st.info("✅ 將使用 image2video 模式，角色一致性更佳")

    # ==================== 功能選項 ====================
    st.subheader("🎛️ 生成選項")
    col_opt_a, col_opt_b, col_opt_c = st.columns(3)
    with col_opt_a:
        enable_voice   = st.checkbox("🎙️ 生成語音旁白", value=True)
    with col_opt_b:
        enable_music   = st.checkbox("🎵 生成背景音樂 (Beatoven)", value=True)
    with col_opt_c:
        enable_gdrive  = st.checkbox("☁️ 儲存至 Google Drive", value=True)

    st.divider()

    # ==================== 生成按鈕 ====================
    if st.button("🚀 開始生成", type="primary", use_container_width=True):
        if not user_input.strip():
            st.warning("⚠️ 請輸入影片描述")
            return

        # 轉換圖片
        image_base64 = None
        if uploaded_image:
            uploaded_image.seek(0)
            image_base64 = image_to_base64(uploaded_image)

        results = {}

        # ========== Step 1：AI 分析 ==========
        st.markdown("---")
        st.markdown("### 🤖 Step 1：AI 分析")
        with st.spinner("分析中..."):
            try:
                result = analyze_prompt(user_input, keys["openai"], image_base64)
                st.success("✅ 分析完成")

                col_r1, col_r2, col_r3, col_r4 = st.columns(4)
                with col_r1:
                    st.metric("影片提示詞", "已生成 ✅")
                with col_r2:
                    st.metric("中文旁白", "已生成 ✅")
                with col_r3:
                    st.metric("音樂情緒", result.get("music_mood", "-"))
                with col_r4:
                    st.metric("音樂風格", result.get("music_genre", "-"))

                with st.expander("查看詳細分析結果"):
                    st.json(result)

                results["analysis"] = result
            except Exception as e:
                st.error(f"❌ 分析失敗：{e}")
                return

        # ========== Step 2：並行生成影片 + 語音 + 音樂 ==========
        st.markdown("---")
        st.markdown("### ⚡ Step 2：並行生成（影片 + 語音 + 音樂）")

        col_v, col_a, col_m = st.columns(3)

        video_status  = col_v.empty()
        audio_status  = col_a.empty()
        music_status  = col_m.empty()

        video_progress = col_v.progress(0)
        audio_progress = col_a.progress(0)
        music_progress = col_m.progress(0)

        video_status.info("🎬 影片生成中...")
        audio_status.info("🎙️ 語音生成中..." if enable_voice else "🎙️ 已跳過")
        music_status.info("🎵 音樂生成中..." if enable_music else "🎵 已跳過")

        def video_progress_cb(i, total, status):
            video_progress.progress(i / total)
            video_status.info(f"🎬 影片生成中... {i*5}s / {total*5}s（{status}）")

        def music_progress_cb(i, total, status):
            music_progress.progress(i / total)
            music_status.info(f"🎵 音樂生成中... {i*5}s（{status}）")

        # ✅ 並行執行影片、語音、音樂
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:

            # 影片任務
            video_future = executor.submit(
                generate_video,
                result["video_prompt"],
                keys["kling_access"],
                keys["kling_secret"],
                image_base64,
                video_progress_cb
            )

            # 語音任務
            if enable_voice:
                voice_future = executor.submit(
                    generate_voice,
                    result["narration"],
                    keys["elevenlabs"],
                    keys["elevenlabs_voice"]
                )
            else:
                voice_future = None

            # 音樂任務
            if enable_music:
                music_future = executor.submit(
                    generate_music,
                    result["music_mood"],
                    result["music_genre"],
                    keys["beatoven"],
                    30,
                    music_progress_cb
                )
            else:
                music_future = None

            # 等待影片
            try:
                video_url = video_future.result()
                video_progress.progress(1.0)
                video_status.success("✅ 影片生成完成")
                results["video_url"] = video_url
            except Exception as e:
                video_status.error(f"❌ 影片失敗：{e}")
                return

            # 等待語音
            if voice_future:
                try:
                    audio_bytes = voice_future.result()
                    audio_progress.progress(1.0)
                    audio_status.success("✅ 語音生成完成")
                    results["audio"] = audio_bytes
                except Exception as e:
                    audio_status.error(f"❌ 語音失敗：{e}")

            # 等待音樂
            if music_future:
                try:
                    music_bytes = music_future.result()
                    music_progress.progress(1.0)
                    music_status.success("✅ 音樂生成完成")
                    results["music"] = music_bytes
                except Exception as e:
                    music_status.error(f"❌ 音樂失敗：{e}")

        # ========== Step 3：顯示結果 ==========
        st.markdown("---")
        st.markdown("### 🎉 Step 3：生成結果")

        col_show1, col_show2 = st.columns(2)

        with col_show1:
            if "video_url" in results:
                st.markdown("**🎬 影片**")
                st.video(results["video_url"])
                st.caption(f"旁白：{result['narration']}")

        with col_show2:
            if "audio" in results:
                st.markdown("**🎙️ 語音旁白**")
                st.audio(results["audio"], format="audio/mp3")

            if "music" in results:
                st.markdown("**🎵 背景音樂**")
                st.audio(results["music"], format="audio/mp3")

        # ========== Step 4：上傳 Google Drive ==========
        if enable_gdrive and "video_url" in results:
            st.markdown("---")
            st.markdown("### ☁️ Step 4：儲存至 Google Drive")

            timestamp = time.strftime("%Y%m%d_%H%M%S")

            with st.spinner("上傳中..."):
                try:
                    # 上傳影片
                    video_link = upload_video_from_url(
                        video_url=results["video_url"],
                        filename=f"video_{timestamp}.mp4",
                        folder_id=keys["gdrive_folder"],
                        sa_json_str=keys["gdrive_sa_json"]
                    )
                    st.success(f"✅ 影片已上傳：[點此開啟]({video_link})")

                    # 上傳語音
                    if "audio" in results:
                        audio_link = upload_to_drive(
                            content=results["audio"],
                            filename=f"narration_{timestamp}.mp3",
                            mimetype="audio/mpeg",
                            folder_id=keys["gdrive_folder"],
                            sa_json_str=keys["gdrive_sa_json"]
                        )
                        st.success(f"✅ 語音已上傳：[點此開啟]({audio_link})")

                    # 上傳音樂
                    if "music" in results:
                        music_link = upload_to_drive(
                            content=results["music"],
                            filename=f"music_{timestamp}.mp3",
                            mimetype="audio/mpeg",
                            folder_id=keys["gdrive_folder"],
                            sa_json_str=keys["gdrive_sa_json"]
                        )
                        st.success(f"✅ 音樂已上傳：[點此開啟]({music_link})")

                except Exception as e:
                    st.error(f"❌ Google Drive 上傳失敗：{e}")


if __name__ == "__main__":
    main()
