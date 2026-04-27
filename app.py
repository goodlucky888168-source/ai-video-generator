import streamlit as st
import time
import uuid
import random
import requests
import concurrent.futures
from config import get_api_keys
from api.openai_api import analyze_prompt, image_to_base64
from api.kling_api import generate_video
from api.elevenlabs_api import generate_voice
from api.beatoven_api import generate_music
from api.gdrive_api import upload_to_drive, upload_video_from_url

# ==================== 全域設定 ====================
MAX_WORKERS = 3

GLOBAL_STYLE = """
cinematic lighting,
soft warm color tone,
consistent color grading,
same lighting style,
high detail, realistic
"""

# ==================== Session 初始化 ====================
def init_session():
    if "tasks" not in st.session_state:
        st.session_state.tasks = {}
    if "characters" not in st.session_state:
        st.session_state.characters = []
    if "storyboard" not in st.session_state:
        st.session_state.storyboard = []
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    if "login_attempts" not in st.session_state:
        st.session_state.login_attempts = 0
    if "lockout_until" not in st.session_state:
        st.session_state.lockout_until = 0

# ==================== 密碼驗證 ====================
def check_password() -> bool:
    if st.session_state.get("authenticated"):
        return True

    st.markdown("## 🔐 請登入")

    col1, col2 = st.columns([1, 2])
    with col1:
        username = st.text_input("帳號", key="login_username")
        password = st.text_input("密碼", type="password", key="login_password")

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
                if attempts >= 5:
                    st.session_state.lockout_until = now + 60
                    st.session_state.login_attempts = 0
                    st.rerun()

    return False

# ==================== API 金鑰狀態面板 ====================
def render_api_settings(keys: dict):
    with st.expander("⚙️ API 金鑰設定狀態", expanded=False):
        st.caption(f"目前模式：{'🟢 主要 (main)' if keys['mode'] == 'main' else '🟡 備用 (backup)'}")
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

# ==================== 分鏡生成 ====================
def generate_storyboard(user_input: str, characters: list, openai_key: str) -> dict:
    char_desc = ""
    for i, c in enumerate(characters):
        label = chr(65 + i)
        char_desc += f"Character {label} ({c['name']}): {c['desc']}\n"

    prompt = f"""
你是專業電影導演，請根據以下劇情和角色，拆成3個分鏡。
只回傳 JSON，格式如下（不要加 markdown code block）：
{{
  "storyboard": [
    {{
      "scene": "英文場景描述",
      "characters": ["A"],
      "duration": 5,
      "narration": "中文旁白"
    }},
    {{
      "scene": "英文場景描述",
      "characters": ["A", "B"],
      "duration": 5,
      "narration": "中文旁白"
    }},
    {{
      "scene": "英文場景描述",
      "characters": ["B"],
      "duration": 5,
      "narration": "中文旁白"
    }}
  ],
  "music_mood": "calm",
  "music_genre": "cinematic",
  "narration": "整體旁白摘要"
}}

劇情：{user_input}

角色：
{char_desc}
"""
    result = analyze_prompt(prompt, openai_key)
    return result

# ==================== Prompt 建構 ====================
def build_scene_prompt(scene: dict, characters: list) -> str:
    desc = ""
    for label in scene.get("characters", []):
        idx = ord(label) - 65
        if idx < len(characters):
            c = characters[idx]
            desc += f"{c['name']}: {c['desc']}\n"

    return f"""
{GLOBAL_STYLE}

Characters:
{desc}

Scene:
{scene['scene']}

keep same character appearance,
no face change,
no face mixing,
consistent style throughout
""".strip()

# ==================== 主程式 ====================
def main():
    st.set_page_config(
        page_title="AI 影片生成器",
        page_icon="🎬",
        layout="wide"
    )

    init_session()

    if not check_password():
        return

    st.title("🎬 AI 影片生成器")
    st.caption("整合 OpenAI · Kling AI · ElevenLabs · Beatoven.ai · Google Drive")

    keys = get_api_keys()
    render_api_settings(keys)

    st.divider()

    # ==================== 模式選擇 ====================
    mode = st.radio(
        "選擇生成模式",
        ["🎥 單場景模式", "🎭 多角色分鏡模式"],
        horizontal=True
    )

    st.divider()

    # ==================== 功能選項（共用） ====================
    st.subheader("🎛️ 生成選項")
    col_opt_a, col_opt_b, col_opt_c = st.columns(3)
    with col_opt_a:
        enable_voice  = st.checkbox("🎙️ 生成語音旁白", value=True)
    with col_opt_b:
        enable_music  = st.checkbox("🎵 生成背景音樂", value=True)
    with col_opt_c:
        enable_gdrive = st.checkbox("☁️ 儲存至 Google Drive", value=True)

    st.divider()

    # ==================================================
    # 模式 A：單場景模式
    # ==================================================
    if mode == "🎥 單場景模式":

        col_input, col_image = st.columns([2, 1])

        with col_input:
            st.subheader("📝 影片描述")
            user_input = st.text_area(
                "描述你想要的影片內容",
                placeholder="例如：夕陽下的海邊，海浪輕拍岸邊，氣氛寧靜祥和...",
                height=160,
                key="single_input"
            )

            # ---- 影片設定 ----
            st.markdown("**🎬 影片設定**")
            col_s1, col_s2, col_s3 = st.columns(3)

            with col_s1:
                orientation = st.radio(
                    "畫面方向",
                    ["🖥️ 橫式 16:9", "📱 直式 9:16", "⬛ 正方 1:1"],
                    key="single_orientation"
                )
                aspect_ratio_map = {
                    "🖥️ 橫式 16:9": "16:9",
                    "📱 直式 9:16": "9:16",
                    "⬛ 正方 1:1":  "1:1"
                }
                aspect_ratio = aspect_ratio_map[orientation]

            with col_s2:
                duration_type = st.radio(
                    "秒數設定",
                    ["快速選擇", "自訂秒數"],
                    key="single_dur_type"
                )

            with col_s3:
                if duration_type == "快速選擇":
                    video_duration = st.selectbox(
                        "影片長度",
                        [5, 10],
                        key="single_dur_select"
                    )
                else:
                    video_duration = st.number_input(
                        "自訂秒數",
                        min_value=3,
                        max_value=60,
                        value=5,
                        step=1,
                        key="single_dur_custom"
                    )

        with col_image:
            st.subheader("📸 角色圖片（選填）")
            uploaded_image = st.file_uploader(
                "上傳角色照片",
                type=["jpg", "jpeg", "png"],
                help="上傳後使用 image2video，角色一致性更佳"
            )
            if uploaded_image:
                st.image(uploaded_image, caption="已上傳角色圖片", use_container_width=True)
                st.info("✅ 將使用 image2video 模式")

            # 預覽比例示意
            st.markdown("**畫面比例預覽**")
            if aspect_ratio == "16:9":
                st.markdown("""
                <div style='background:#333;width:160px;height:90px;
                border-radius:6px;display:flex;align-items:center;
                justify-content:center;color:white;font-size:12px'>
                🖥️ 16:9 橫式</div>
                """, unsafe_allow_html=True)
            elif aspect_ratio == "9:16":
                st.markdown("""
                <div style='background:#333;width:90px;height:160px;
                border-radius:6px;display:flex;align-items:center;
                justify-content:center;color:white;font-size:12px;
                text-align:center'>
                📱 9:16<br>直式</div>
                """, unsafe_allow_html=True)
            else:
                st.markdown("""
                <div style='background:#333;width:120px;height:120px;
                border-radius:6px;display:flex;align-items:center;
                justify-content:center;color:white;font-size:12px'>
                ⬛ 1:1</div>
                """, unsafe_allow_html=True)

        st.info(f"📐 比例：**{aspect_ratio}** ｜ ⏱️ 長度：**{video_duration} 秒**")

        if st.button("🚀 開始生成", type="primary", use_container_width=True, key="single_gen"):
            if not user_input.strip():
                st.warning("⚠️ 請輸入影片描述")
                return

            image_base64 = None
            if uploaded_image:
                try:
                    image_base64 = image_to_base64(uploaded_image)
                    st.caption(f"✅ 圖片已處理，Base64 長度：{len(image_base64)} 字元")
                except Exception as e:
                    st.error(f"❌ 圖片處理失敗：{e}")
                    return

            results = {}

            # Step 1：AI 分析
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

            # Step 2：並行生成
            st.markdown("---")
            st.markdown("### ⚡ Step 2：並行生成")

            col_v, col_a, col_m = st.columns(3)
            video_status   = col_v.empty()
            audio_status   = col_a.empty()
            music_status   = col_m.empty()
            video_progress = col_v.progress(0)
            audio_progress = col_a.progress(0)
            music_progress = col_m.progress(0)

            video_status.info("🎬 影片生成中...")
            audio_status.info("🎙️ 語音生成中..." if enable_voice else "🎙️ 已跳過")
            music_status.info("🎵 音樂生成中..." if enable_music else "🎵 已跳過")

            def video_progress_cb(i, total, status):
                video_progress.progress(i / total)
                video_status.info(f"🎬 {i*5}s / {total*5}s（{status}）")

            def music_progress_cb(i, total, status):
                music_progress.progress(i / total)
                music_status.info(f"🎵 {i*5}s（{status}）")

            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                video_future = executor.submit(
                    generate_video,
                    result["video_prompt"],
                    keys["kling_access"],
                    keys["kling_secret"],
                    image_base64,
                    video_progress_cb,
                    video_duration,
                    aspect_ratio
                )
                voice_future = executor.submit(
                    generate_voice,
                    result["narration"],
                    keys["elevenlabs"],
                    keys["elevenlabs_voice"]
                ) if enable_voice else None

                music_future = executor.submit(
                    generate_music,
                    result["music_mood"],
                    result["music_genre"],
                    keys["beatoven"],
                    30,
                    music_progress_cb
                ) if enable_music else None

                try:
                    video_url = video_future.result()
                    video_progress.progress(1.0)
                    video_status.success("✅ 影片完成")
                    results["video_url"] = video_url
                except Exception as e:
                    video_status.error(f"❌ 影片失敗：{e}")
                    return

                if voice_future:
                    try:
                        results["audio"] = voice_future.result()
                        audio_progress.progress(1.0)
                        audio_status.success("✅ 語音完成")
                    except Exception as e:
                        audio_status.error(f"❌ 語音失敗：{e}")

                if music_future:
                    try:
                        results["music"] = music_future.result()
                        music_progress.progress(1.0)
                        music_status.success("✅ 音樂完成")
                    except Exception as e:
                        music_status.error(f"❌ 音樂失敗：{e}")

            # Step 3：顯示結果
            st.markdown("---")
            st.markdown("### 🎉 Step 3：生成結果")
            col_s1, col_s2 = st.columns(2)
            with col_s1:
                if "video_url" in results:
                    st.markdown("**🎬 影片**")
                    st.video(results["video_url"])
                    st.caption(f"旁白：{result['narration']}")
            with col_s2:
                if "audio" in results:
                    st.markdown("**🎙️ 語音旁白**")
                    st.audio(results["audio"], format="audio/mp3")
                if "music" in results:
                    st.markdown("**🎵 背景音樂**")
                    st.audio(results["music"], format="audio/mp3")

            # Step 4：Google Drive
            if enable_gdrive and "video_url" in results:
                st.markdown("---")
                st.markdown("### ☁️ Step 4：儲存至 Google Drive")
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                with st.spinner("上傳中..."):
                    try:
                        video_link = upload_video_from_url(
                            video_url=results["video_url"],
                            filename=f"video_{timestamp}.mp4",
                            folder_id=keys["gdrive_folder"],
                            sa_json_str=keys["gdrive_sa_json"]
                        )
                        st.success(f"✅ 影片已上傳：[點此開啟]({video_link})")
                        if "audio" in results:
                            audio_link = upload_to_drive(
                                content=results["audio"],
                                filename=f"narration_{timestamp}.mp3",
                                mimetype="audio/mpeg",
                                folder_id=keys["gdrive_folder"],
                                sa_json_str=keys["gdrive_sa_json"]
                            )
                            st.success(f"✅ 語音已上傳：[點此開啟]({audio_link})")
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

    # ==================================================
    # 模式 B：多角色分鏡模式
    # ==================================================
    elif mode == "🎭 多角色分鏡模式":

        # -------- 角色建立 --------
        st.subheader("🎭 Step 1：建立角色")

        with st.form("character_form"):
            char_name = st.text_input("角色名稱", placeholder="例如：主角小明")
            char_uploads = st.file_uploader(
                "上傳角色參考圖（可多張）",
                type=["jpg", "jpeg", "png"],
                accept_multiple_files=True
            )
            submitted = st.form_submit_button("➕ 新增角色")

            if submitted:
                if not char_name:
                    st.warning("請輸入角色名稱")
                elif not char_uploads:
                    st.warning("請上傳至少一張角色圖片")
                else:
                    with st.spinner("分析角色外觀中..."):
                        try:
                            img_b64 = image_to_base64(char_uploads[0])
                            desc_result = analyze_prompt(
                                "請詳細描述這個角色的外觀特徵，包含髮型、服裝、臉部特徵",
                                keys["openai"],
                                img_b64
                            )
                            char_desc = (
                                desc_result.get("narration")
                                or desc_result.get("video_prompt")
                                or "角色外觀待描述"
                            )
                            st.session_state.characters.append({
                                "name": char_name,
                                "images": char_uploads,
                                "desc": char_desc
                            })
                            st.success(f"✅ 角色「{char_name}」建立完成")
                        except Exception as e:
                            st.error(f"❌ 角色建立失敗：{e}")

        # 顯示已建立角色
        if st.session_state.characters:
            st.markdown("**已建立角色：**")
            for i, c in enumerate(st.session_state.characters):
                col1, col2, col3 = st.columns([1, 3, 1])
                with col1:
                    st.markdown(f"**{chr(65+i)}. {c['name']}**")
                with col2:
                    st.caption(c["desc"][:80] + "...")
                with col3:
                    if st.button("🗑️", key=f"del_{i}"):
                        st.session_state.characters.pop(i)
                        st.rerun()

        st.divider()

        # -------- 選角色 --------
        st.subheader("🎬 Step 2：選擇出場角色")
        selected_chars = []
        if st.session_state.characters:
            cols = st.columns(min(len(st.session_state.characters), 4))
            for i, c in enumerate(st.session_state.characters):
                with cols[i % 4]:
                    if st.checkbox(f"{chr(65+i)}. {c['name']}", key=f"sel_{i}"):
                        selected_chars.append(c)
        else:
            st.info("請先在上方建立角色")

        st.divider()

        # -------- 劇情輸入 --------
        st.subheader("📝 Step 3：輸入劇情與設定")
        user_input = st.text_area(
            "描述故事劇情",
            placeholder="例如：美女在公園遇見帥哥，兩人一起看夕陽，最後依依不捨地道別...",
            height=160,
            key="multi_input"
        )

        # ---- 影片設定 ----
        st.markdown("**🎬 影片設定**")
        col_set1, col_set2, col_set3 = st.columns(3)

        with col_set1:
            orientation = st.radio(
                "畫面方向",
                ["🖥️ 橫式 16:9", "📱 直式 9:16", "⬛ 正方 1:1"],
                key="multi_orientation"
            )
            aspect_ratio_map = {
                "🖥️ 橫式 16:9": "16:9",
                "📱 直式 9:16": "9:16",
                "⬛ 正方 1:1":  "1:1"
            }
            aspect_ratio = aspect_ratio_map[orientation]

        with col_set2:
            duration_type = st.radio(
                "秒數設定",
                ["快速選擇", "自訂秒數"],
                key="multi_dur_type"
            )

        with col_set3:
            if duration_type == "快速選擇":
                video_duration = st.selectbox(
                    "每個分鏡長度",
                    [5, 10],
                    key="multi_dur_select"
                )
            else:
                video_duration = st.number_input(
                    "自訂秒數（每個分鏡）",
                    min_value=3,
                    max_value=60,
                    value=5,
                    step=1,
                    key="multi_dur_custom"
                )

        st.info(f"📐 比例：**{aspect_ratio}** ｜ ⏱️ 每個分鏡：**{video_duration} 秒**")

        # -------- 生成分鏡 --------
        if st.button("🎬 生成分鏡腳本", use_container_width=True):
            if not user_input.strip():
                st.warning("⚠️ 請輸入劇情")
            elif not selected_chars:
                st.warning("⚠️ 請在 Step 2 勾選至少一個角色")
            else:
                with st.spinner("AI 正在拆解分鏡..."):
                    try:
                        storyboard_result = generate_storyboard(
                            user_input, selected_chars, keys["openai"]
                        )
                        st.session_state.storyboard = storyboard_result.get("storyboard", [])
                        st.session_state.storyboard_meta = storyboard_result
                        st.success(f"✅ 分鏡腳本生成完成，共 {len(st.session_state.storyboard)} 個分鏡")
                    except Exception as e:
                        st.error(f"❌ 分鏡生成失敗：{e}")

        # 顯示分鏡
        if st.session_state.storyboard:
            st.subheader("📋 分鏡腳本預覽")
            for i, s in enumerate(st.session_state.storyboard):
                with st.expander(f"分鏡 {i+1}｜角色：{', '.join(s.get('characters', []))}｜{s.get('duration', video_duration)} 秒"):
                    st.write(f"**場景：** {s.get('scene', '')}")
                    st.write(f"**旁白：** {s.get('narration', '')}")
                    st.write(f"**時長：** {s.get('duration', video_duration)} 秒")

        st.divider()

        # -------- 開始生成影片 --------
        if st.button("🚀 開始生成所有分鏡影片", type="primary", use_container_width=True, key="multi_gen"):
            if not st.session_state.storyboard:
                st.warning("⚠️ 請先點「生成分鏡腳本」按鈕")
                return
            if not selected_chars:
                st.warning("⚠️ 請在 Step 2 勾選出場角色")
                return

            meta = st.session_state.get("storyboard_meta", {})
            total_scenes = len(st.session_state.storyboard)
            video_urls = []

            st.markdown("---")
            st.markdown("### ⚡ 並行生成所有分鏡")

            scene_cols = st.columns(total_scenes)
            scene_status   = [col.empty() for col in scene_cols]
            scene_progress = [col.progress(0) for col in scene_cols]

            for i in range(total_scenes):
                scene_status[i].info(f"🎬 分鏡 {i+1}\n等待中...")

            def generate_scene(scene, idx):
                try:
                    scene_status[idx].info(f"🎬 分鏡 {idx+1}\n生成中...")
                    prompt = build_scene_prompt(scene, selected_chars)

                    char_labels = scene.get("characters", [])
                    ref_img_b64 = None
                    if char_labels:
                        char_idx = ord(char_labels[0]) - 65
                        if char_idx < len(selected_chars):
                            ref_img = selected_chars[char_idx]["images"][0]
                            ref_img_b64 = image_to_base64(ref_img)

                    def progress_cb(i, total, status):
                        scene_progress[idx].progress(i / total)

                    # 使用分鏡自訂秒數，若無則用全域設定
                    scene_duration = scene.get("duration", video_duration)

                    url = generate_video(
                        prompt,
                        keys["kling_access"],
                        keys["kling_secret"],
                        ref_img_b64,
                        progress_cb,
                        scene_duration,
                        aspect_ratio
                    )
                    scene_progress[idx].progress(1.0)
                    scene_status[idx].success(f"✅ 分鏡 {idx+1}\n完成")
                    return idx, url

                except Exception as e:
                    scene_status[idx].error(f"❌ 分鏡 {idx+1}\n失敗：{e}")
                    return idx, None

            with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                futures = [
                    executor.submit(generate_scene, scene, i)
                    for i, scene in enumerate(st.session_state.storyboard)
                ]
                scene_results = [f.result() for f in concurrent.futures.as_completed(futures)]

            scene_results.sort(key=lambda x: x[0])
            video_urls = [url for _, url in scene_results if url]

            if not video_urls:
                st.error("❌ 所有分鏡都生成失敗")
                return

            # 語音 + 音樂
            st.markdown("---")
            st.markdown("### 🎵 生成語音與音樂")

            col_a, col_m = st.columns(2)
            audio_status   = col_a.empty()
            music_status   = col_m.empty()
            audio_progress = col_a.progress(0)
            music_progress = col_m.progress(0)

            audio_status.info("🎙️ 語音生成中..." if enable_voice else "🎙️ 已跳過")
            music_status.info("🎵 音樂生成中..." if enable_music else "🎵 已跳過")

            def music_progress_cb(i, total, status):
                music_progress.progress(i / total)

            audio_bytes = None
            music_bytes = None

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                voice_future = executor.submit(
                    generate_voice,
                    meta.get("narration", ""),
                    keys["elevenlabs"],
                    keys["elevenlabs_voice"]
                ) if enable_voice and meta.get("narration") else None

                music_future = executor.submit(
                    generate_music,
                    meta.get("music_mood", "calm"),
                    meta.get("music_genre", "cinematic"),
                    keys["beatoven"],
                    30,
                    music_progress_cb
                ) if enable_music else None

                if voice_future:
                    try:
                        audio_bytes = voice_future.result()
                        audio_progress.progress(1.0)
                        audio_status.success("✅ 語音完成")
                    except Exception as e:
                        audio_status.error(f"❌ 語音失敗：{e}")

                if music_future:
                    try:
                        music_bytes = music_future.result()
                        music_progress.progress(1.0)
                        music_status.success("✅ 音樂完成")
                    except Exception as e:
                        music_status.error(f"❌ 音樂失敗：{e}")

            # 顯示結果
            st.markdown("---")
            st.markdown("### 🎉 生成結果")

            st.markdown("**🎬 各分鏡影片**")
            vid_cols = st.columns(len(video_urls))
            for i, url in enumerate(video_urls):
                with vid_cols[i]:
                    st.markdown(f"**分鏡 {i+1}**")
                    st.video(url)

            col_s1, col_s2 = st.columns(2)
            with col_s1:
                if audio_bytes:
                    st.markdown("**🎙️ 語音旁白**")
                    st.audio(audio_bytes, format="audio/mp3")
            with col_s2:
                if music_bytes:
                    st.markdown("**🎵 背景音樂**")
                    st.audio(music_bytes, format="audio/mp3")

            # Google Drive
            if enable_gdrive:
                st.markdown("---")
                st.markdown("### ☁️ 儲存至 Google Drive")
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                with st.spinner("上傳中..."):
                    try:
                        for i, url in enumerate(video_urls):
                            link = upload_video_from_url(
                                video_url=url,
                                filename=f"scene{i+1}_{timestamp}.mp4",
                                folder_id=keys["gdrive_folder"],
                                sa_json_str=keys["gdrive_sa_json"]
                            )
                            st.success(f"✅ 分鏡 {i+1} 已上傳：[點此開啟]({link})")

                        if audio_bytes:
                            link = upload_to_drive(
                                content=audio_bytes,
                                filename=f"narration_{timestamp}.mp3",
                                mimetype="audio/mpeg",
                                folder_id=keys["gdrive_folder"],
                                sa_json_str=keys["gdrive_sa_json"]
                            )
                            st.success(f"✅ 語音已上傳：[點此開啟]({link})")

                        if music_bytes:
                            link = upload_to_drive(
                                content=music_bytes,
                                filename=f"music_{timestamp}.mp3",
                                mimetype="audio/mpeg",
                                folder_id=keys["gdrive_folder"],
                                sa_json_str=keys["gdrive_sa_json"]
                            )
                            st.success(f"✅ 音樂已上傳：[點此開啟]({link})")

                    except Exception as e:
                        st.error(f"❌ Google Drive 上傳失敗：{e}")


if __name__ == "__main__":
    main()
