import streamlit as st
import time
import requests
import concurrent.futures
import json
import os
import jwt
from functools import wraps
from config import get_api_keys
from api.openai_api import analyze_prompt, image_to_base64
from api.kling_api import generate_video
from api.elevenlabs_api import generate_voice
from api.beatoven_api import generate_music
from api.gdrive_api import upload_to_drive, upload_video_from_url

# ==================== 全域設定 ====================
MAX_WORKERS  = 3
HISTORY_FILE = "history.json"

GLOBAL_STYLE = """
cinematic lighting,
soft warm color tone,
consistent color grading,
same lighting style,
high detail, realistic
"""

# ==================== 歷史記錄持久化 ====================
def load_history() -> list:
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_history(history: list):
    try:
        safe = []
        for r in history:
            safe.append({
                "timestamp":  r.get("timestamp", ""),
                "mode":       r.get("mode", ""),
                "narration":  r.get("narration", ""),
                "video_urls": r.get("video_urls", []),
                "errors":     r.get("errors", [])
            })
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(safe, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

# ==================== 重試裝飾器 ====================
def retry_api(max_retries=3, delay_base=2):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_retries - 1:
                        raise
                    time.sleep(delay_base ** attempt)
        return wrapper
    return decorator

@retry_api(max_retries=3)
def safe_generate_video(*args, **kwargs):
    return generate_video(*args, **kwargs)

@retry_api(max_retries=3)
def safe_generate_voice(*args, **kwargs):
    return generate_voice(*args, **kwargs)

@retry_api(max_retries=2)
def safe_generate_music(*args, **kwargs):
    return generate_music(*args, **kwargs)

# ==================== Kling JWT Token ====================
def generate_kling_token(access_key: str, secret_key: str) -> str:
    payload = {
        "iss": access_key,
        "exp": int(time.time()) + 1800,
        "nbf": int(time.time()) - 5
    }
    return jwt.encode(payload, secret_key, algorithm="HS256")

# ==================== 查詢資源包 ====================
def query_account_costs(access_key: str, secret_key: str) -> dict:
    token = generate_kling_token(access_key, secret_key)
    url   = "https://api.klingai.com/account/costs"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json"
    }
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    return response.json()

# ==================== Session 初始化 ====================
def init_session():
    defaults = {
        "tasks":            {},
        "characters":       [],
        "storyboard":       [],
        "storyboard_meta":  {},
        "script":           {},
        "script_photos":    {},
        "last_result":      {},
        "history":          load_history(),
        "authenticated":    False,
        "login_attempts":   0,
        "lockout_until":    0,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

# ==================== 清除角色 ====================
def clear_all_characters():
    st.session_state.characters      = []
    st.session_state.storyboard      = []
    st.session_state.storyboard_meta = {}
    st.session_state.last_result     = {}
    keys_to_del = [
        k for k in st.session_state.keys()
        if k.startswith(("edit_scene_", "edit_narr_", "sel_", "del_"))
    ]
    for k in keys_to_del:
        del st.session_state[k]
    st.rerun()

# ==================== 密碼驗證 ====================
def check_password() -> bool:
    if st.session_state.get("authenticated"):
        return True

    st.markdown("## 🔐 請登入")
    col1, _ = st.columns([1, 2])
    with col1:
        username = st.text_input("帳號", key="login_username")
        password = st.text_input("密碼", type="password", key="login_password")

        now = time.time()
        if now < st.session_state.lockout_until:
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
                    st.rerun()
    return False

# ==================== API 金鑰狀態面板 ====================
def render_api_settings(keys: dict):
    with st.expander("⚙️ API 金鑰設定狀態", expanded=False):
        st.caption(
            f"目前模式：{'🟢 主要 (main)' if keys['mode'] == 'main' else '🟡 備用 (backup)'}"
        )
        key_map = {
            "OpenAI":              keys["openai"],
            "Kling Access":        keys["kling_access"],
            "Kling Secret":        keys["kling_secret"],
            "ElevenLabs":          keys["elevenlabs"],
            "Beatoven":            keys["beatoven"],
            "Google Drive Folder": keys["gdrive_folder"],
        }
        for name, val in key_map.items():
            c1, c2 = st.columns(2)
            with c1:
                st.text(name)
            with c2:
                if val:
                    masked = val[:4] + "****" + val[-4:] if len(val) > 8 else "****"
                    st.success(f"✅ {masked}")
                else:
                    st.error("❌ 未設定")

        st.divider()
        # ✅ 資源包查詢
        render_account_costs(keys)

# ==================== 資源包查詢 UI ====================
def render_account_costs(keys: dict):
    st.markdown("**💰 帳號資源包狀態**")
    if st.button("🔄 查詢剩餘數量", key="query_costs"):
        if not keys.get("kling_access") or not keys.get("kling_secret"):
            st.error("❌ 缺少 Kling API 金鑰")
            return
        try:
            result = query_account_costs(
                keys["kling_access"],
                keys["kling_secret"]
            )
            if result.get("code") != 0:
                st.error(f"❌ API 回傳錯誤：{result.get('message','')}")
                return

            packs = (
                result
                .get("data", {})
                .get("resource_pack_subscribe_infos", [])
            )
            if not packs:
                st.info("目前沒有資源包")
            else:
                for pack in packs:
                    remaining = pack.get("remaining_quantity", 0)
                    total     = pack.get("total_quantity", 0)
                    name      = pack.get("resource_pack_name", "未知")
                    expire_ms = pack.get("expire_time", 0)
                    # ✅ 修正變數名稱 expire_dt（原本寫成 expire_date 是 bug）
                    expire_dt = time.strftime(
                        "%Y-%m-%d",
                        time.localtime(expire_ms / 1000)
                    ) if expire_ms else "未知"

                    ratio = remaining / total if total > 0 else 0
                    st.markdown(f"**{name}**")
                    st.progress(ratio)
                    st.caption(
                        f"剩餘：{remaining} / {total} ｜ "
                        f"到期：{expire_dt} ｜ "          # ✅ 修正：expire_dt
                        f"使用率：{(1 - ratio) * 100:.1f}%"
                    )
                    st.divider()

        except Exception as e:
            st.error(f"❌ 查詢失敗：{e}")

# ==================== API 金鑰提早檢查 ====================
def check_required_keys(keys: dict, require_voice: bool, require_music: bool) -> bool:
    missing = []
    if not keys["openai"]:       missing.append("OpenAI")
    if not keys["kling_access"]: missing.append("Kling Access Key")
    if not keys["kling_secret"]: missing.append("Kling Secret Key")
    if require_voice and not keys["elevenlabs"]:
        missing.append("ElevenLabs")
    if require_music and not keys["beatoven"]:
        missing.append("Beatoven")
    if missing:
        st.error(f"❌ 缺少必要 API 金鑰：{', '.join(missing)}")
        return False
    return True

# ==================== 分鏡生成（模式 B） ====================
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
    {{"scene": "英文場景描述", "characters": ["A"], "narration": "中文旁白"}},
    {{"scene": "英文場景描述", "characters": ["A","B"], "narration": "中文旁白"}},
    {{"scene": "英文場景描述", "characters": ["B"], "narration": "中文旁白"}}
  ],
  "music_mood": "calm",
  "music_genre": "cinematic",
  "narration": "整體旁白摘要（30字以內）"
}}

劇情：{user_input}
角色：
{char_desc}
"""
    return analyze_prompt(prompt, openai_key)

# ==================== 劇本生成（模式 C） ====================
def generate_script_from_idea(idea: str, ending_type: str, openai_key: str) -> dict:
    prompt = f"""
你是專業電影編劇。請將以下「一句話概念」擴展成完整腳本。

概念：{idea}
結局類型：{ending_type}

要求輸出 JSON 格式（不要加 markdown code block）：
{{
  "title": "影片標題",
  "logline": "一句話故事摘要",
  "characters": [
    {{
      "name": "角色名",
      "label": "A",
      "personality": "性格描述",
      "appearance": "外觀描述（英文，詳細描述髮型、服裝、臉部特徵）",
      "motivation": "動機"
    }}
  ],
  "storyboard": [
    {{
      "scene": "場景描述（英文，融入角色動作、表情、鏡頭建議、節奏）",
      "location": "地點",
      "characters": ["A"],
      "dialogue": "對話內容（中文）",
      "narration": "旁白（中文）",
      "camera": "特寫/中景/全景",
      "pacing": "慢/中/快",
      "is_climax": false
    }}
  ],
  "ending_description": "結局描述（中文）",
  "climax_point": 2,
  "music_mood": "romantic",
  "music_genre": "acoustic",
  "narration": "整體旁白摘要（30字以內）"
}}

注意：
- storyboard 請生成 4 個分鏡
- scene 欄位直接融入鏡頭建議和節奏
- 只回傳 JSON
"""
    return analyze_prompt(prompt, openai_key)

# ==================== Prompt 建構 ====================
def build_scene_prompt(scene: dict, characters: list) -> str:
    desc = ""
    for label in scene.get("characters", []):
        idx = ord(label) - 65
        if 0 <= idx < len(characters):
            c = characters[idx]
            appearance = c.get("appearance") or c.get("desc") or ""
            desc += f"{c['name']}: {appearance}\n"

    climax_style = ""
    if scene.get("is_climax"):
        climax_style = "dramatic lighting, intense atmosphere, emotional peak,"

    camera = scene.get("camera", "")
    pacing = scene.get("pacing", "")
    extra  = ""
    if camera:
        extra += f"{camera} shot, "
    if pacing:
        extra += f"{pacing} pacing, "

    return f"""{GLOBAL_STYLE}
{climax_style}
{extra}
Characters:
{desc}
Scene:
{scene['scene']}

keep same character appearance,
no face change, no face mixing,
consistent style throughout""".strip()

# ==================== 讀取編輯後的分鏡（模式 B） ====================
def get_edited_storyboard() -> list:
    result = []
    for i, s in enumerate(st.session_state.storyboard):
        edited = dict(s)
        edited["scene"]     = st.session_state.get(f"edit_scene_{i}", s.get("scene", ""))
        edited["narration"] = st.session_state.get(f"edit_narr_{i}",  s.get("narration", ""))
        result.append(edited)
    return result

# ==================== 下載影片按鈕 ====================
def render_download_button(url: str, label: str, filename: str):
    try:
        resp = requests.get(url, timeout=60)
        if resp.status_code == 200:
            st.download_button(
                label=label,
                data=resp.content,
                file_name=filename,
                mime="video/mp4",
                use_container_width=True
            )
        else:
            st.warning(f"⚠️ 無法下載（HTTP {resp.status_code}）")
            st.markdown(f"[🔗 直接開啟影片]({url})")
    except requests.Timeout:
        st.warning("⚠️ 下載逾時")
        st.markdown(f"[🔗 直接開啟影片]({url})")
    except Exception as e:
        st.warning(f"⚠️ 下載失敗：{e}")
        st.markdown(f"[🔗 直接開啟影片]({url})")

# ==================== 歷史記錄 ====================
def render_history():
    if not st.session_state.history:
        return
    with st.expander(
        f"📂 生成歷史（共 {len(st.session_state.history)} 筆）",
        expanded=False
    ):
        for i, record in enumerate(reversed(st.session_state.history)):
            idx = len(st.session_state.history) - i
            st.markdown(f"**#{idx} — {record['timestamp']}**")
            st.caption(f"模式：{record['mode']} ｜ 旁白：{record.get('narration','')[:30]}")

            if record.get("errors"):
                with st.expander(f"⚠️ 本次錯誤記錄（{len(record['errors'])} 筆）"):
                    for err in record["errors"]:
                        st.error(err)

            if record.get("video_urls"):
                cols = st.columns(min(len(record["video_urls"]), 3))
                for j, vurl in enumerate(record["video_urls"]):
                    with cols[j % 3]:
                        st.video(vurl)
                        render_download_button(
                            vurl,
                            f"⬇️ 下載",
                            f"history_{idx}_scene{j+1}.mp4"
                        )
            st.divider()

# ==================== 固定顯示最新結果 ====================
def render_last_result():
    result = st.session_state.get("last_result", {})
    if not result:
        return

    st.markdown("---")
    st.markdown("### 🎉 最新生成結果")

    col_title, col_clear = st.columns([4, 1])
    with col_title:
        st.caption(f"模式：{result.get('mode','')} ｜ {result.get('timestamp','')}")
    with col_clear:
        if st.button("🗑️ 清除結果", type="secondary", key="clear_last_result"):
            st.session_state.last_result = {}
            st.rerun()

    render_video_results(
        result.get("video_urls", []),
        result.get("audio_bytes"),
        result.get("music_bytes"),
        result.get("narration", "")
    )

    if result.get("errors"):
        with st.expander(
            f"⚠️ 本次錯誤記錄（{len(result['errors'])} 筆）",
            expanded=True
        ):
            for err in result["errors"]:
                st.error(err)

# ==================== 並行生成影片（共用） ====================
def run_parallel_video_generation(
    boards_snapshot: list,
    chars_snapshot: list,
    video_duration: int,
    aspect_ratio: str,
    keys: dict,
    scene_status: list,
    scene_progress: list
) -> dict:
    def generate_one(scene, idx):
        try:
            prompt      = build_scene_prompt(scene, chars_snapshot)
            ref_img_b64 = None

            char_labels = scene.get("characters", [])
            for lbl in char_labels:
                char_idx = ord(lbl) - 65
                if 0 <= char_idx < len(chars_snapshot):
                    imgs = chars_snapshot[char_idx].get("images_b64", [])
                    if imgs and ref_img_b64 is None:
                        ref_img_b64 = imgs[0]
                        break

            url = safe_generate_video(
                prompt,
                keys["kling_access"],
                keys["kling_secret"],
                ref_img_b64,
                lambda i, t, s: None,
                video_duration,
                aspect_ratio
            )
            return idx, url, None
        except Exception as e:
            return idx, None, str(e)

    collected = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_list = [
            executor.submit(generate_one, scene, i)
            for i, scene in enumerate(boards_snapshot)
        ]
        for f in concurrent.futures.as_completed(future_list):
            idx, url, err = f.result()
            collected[idx] = (url, err)
            if err:
                scene_status[idx].error(f"❌ 分鏡 {idx+1} 失敗")
                scene_progress[idx].progress(1.0)
            else:
                scene_status[idx].success(f"✅ 分鏡 {idx+1} 完成")
                scene_progress[idx].progress(1.0)

    return collected

# ==================== 並行生成語音+音樂（共用） ====================
def run_parallel_audio_generation(
    narration_text: str,
    music_mood: str,
    music_genre: str,
    enable_voice: bool,
    enable_music: bool,
    keys: dict
) -> tuple:
    col_a, col_m   = st.columns(2)
    audio_status   = col_a.empty()
    music_status   = col_m.empty()
    audio_progress = col_a.progress(0)
    music_progress = col_m.progress(0)

    audio_status.info("🎙️ 語音生成中..." if enable_voice else "🎙️ 已跳過")
    music_status.info("🎵 音樂生成中..." if enable_music else "🎵 已跳過")

    audio_bytes = None
    music_bytes = None
    errors      = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        voice_future = executor.submit(
            safe_generate_voice,
            narration_text,
            keys["elevenlabs"],
            keys.get("elevenlabs_voice", "")
        ) if enable_voice and narration_text else None

        music_future = executor.submit(
            safe_generate_music,
            music_mood,
            music_genre,
            keys["beatoven"],
            30,
            lambda i, t, s: None
        ) if enable_music else None

        if voice_future:
            try:
                audio_bytes = voice_future.result()
                audio_progress.progress(1.0)
                audio_status.success("✅ 語音完成")
            except Exception as e:
                err = f"🎙️ 語音生成失敗：{str(e)[:80]}"
                audio_status.error(err)
                errors.append(err)

        if music_future:
            try:
                music_bytes = music_future.result()
                music_progress.progress(1.0)
                music_status.success("✅ 音樂完成")
            except Exception as e:
                err = f"🎵 音樂生成失敗：{str(e)[:80]}"
                music_status.error(err)
                errors.append(err)

    return audio_bytes, music_bytes, errors

# ==================== Google Drive 上傳（共用） ====================
def run_gdrive_upload(
    video_urls: list,
    audio_bytes,
    music_bytes,
    keys: dict,
    prefix: str = "video"
) -> list:
    ts     = time.strftime("%Y%m%d_%H%M%S")
    errors = []

    if not keys.get("gdrive_folder"):
        err = "❌ Google Drive Folder ID 未設定，跳過上傳"
        st.warning(err)
        return [err]
    if not keys.get("gdrive_sa_json"):
        err = "❌ Google Drive Service Account JSON 未設定，跳過上傳"
        st.warning(err)
        return [err]

    for i, url in enumerate(video_urls):
        try:
            link = upload_video_from_url(
                video_url=url,
                filename=f"{prefix}_scene{i+1}_{ts}.mp4",
                folder_id=keys["gdrive_folder"],
                sa_json_str=keys["gdrive_sa_json"]
            )
            st.success(f"✅ 分鏡 {i+1} 已上傳：[點此開啟]({link})")
        except Exception as e:
            err = f"❌ 分鏡 {i+1} 上傳失敗：{str(e)[:60]}"
            st.error(err)
            errors.append(err)

    if audio_bytes:
        try:
            link = upload_to_drive(
                content=audio_bytes,
                filename=f"{prefix}_narration_{ts}.mp3",
                mimetype="audio/mpeg",
                folder_id=keys["gdrive_folder"],
                sa_json_str=keys["gdrive_sa_json"]
            )
            st.success(f"✅ 語音已上傳：[點此開啟]({link})")
        except Exception as e:
            err = f"❌ 語音上傳失敗：{str(e)[:60]}"
            st.error(err)
            errors.append(err)

    if music_bytes:
        try:
            link = upload_to_drive(
                content=music_bytes,
                filename=f"{prefix}_music_{ts}.mp3",
                mimetype="audio/mpeg",
                folder_id=keys["gdrive_folder"],
                sa_json_str=keys["gdrive_sa_json"]
            )
            st.success(f"✅ 音樂已上傳：[點此開啟]({link})")
        except Exception as e:
            err = f"❌ 音樂上傳失敗：{str(e)[:60]}"
            st.error(err)
            errors.append(err)

    return errors

# ==================== 顯示影片結果（共用） ====================
def render_video_results(
    video_urls: list,
    audio_bytes,
    music_bytes,
    narration_text: str = ""
):
    if not video_urls:
        st.warning("⚠️ 沒有可顯示的影片")
        return

    st.markdown("**🎬 各分鏡影片**")
    vid_cols = st.columns(min(len(video_urls), 4))
    for i, url in enumerate(video_urls):
        with vid_cols[i % 4]:
            st.markdown(f"**分鏡 {i+1}**")
            st.video(url)
            render_download_button(
                url,
                f"⬇️ 下載分鏡 {i+1}",
                f"scene{i+1}_{time.strftime('%Y%m%d_%H%M%S')}.mp4"
            )

    col_s1, col_s2 = st.columns(2)
    with col_s1:
        if audio_bytes:
            st.markdown("**🎙️ 語音旁白**")
            if narration_text:
                st.caption(narration_text)
            st.audio(audio_bytes, format="audio/mp3")
    with col_s2:
        if music_bytes:
            st.markdown("**🎵 背景音樂**")
            st.audio(music_bytes, format="audio/mp3")

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
    render_history()
    render_last_result()

    st.divider()

    mode = st.radio(
        "選擇生成模式",
        ["🎥 單場景模式", "🎭 多角色分鏡模式", "✍️ AI 劇本創作"],
        horizontal=True
    )

    st.divider()

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
                        "影片長度", [5, 10], key="single_dur_select"
                    )
                else:
                    video_duration = st.number_input(
                        "自訂秒數",
                        min_value=3, max_value=60,
                        value=5, step=1,
                        key="single_dur_custom"
                    )
            st.info(f"📐 比例：**{aspect_ratio}** ｜ ⏱️ 長度：**{video_duration} 秒**")

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

            st.markdown("**畫面比例預覽**")
            preview_styles = {
                "16:9": ("160px", "90px",  "🖥️ 16:9 橫式"),
                "9:16": ("90px",  "160px", "📱 9:16 直式"),
                "1:1":  ("120px", "120px", "⬛ 1:1 正方"),
            }
            w, h, plabel = preview_styles[aspect_ratio]
            st.markdown(
                f"<div style='background:#333;width:{w};height:{h};"
                f"border-radius:6px;display:flex;align-items:center;"
                f"justify-content:center;color:white;font-size:12px;"
                f"text-align:center'>{plabel}</div>",
                unsafe_allow_html=True
            )

        if st.button("🚀 開始生成", type="primary", use_container_width=True, key="single_gen"):
            if not user_input.strip():
                st.warning("⚠️ 請輸入影片描述")
                return
            if not check_required_keys(keys, enable_voice, enable_music):
                return

            image_base64 = None
            if uploaded_image:
                try:
                    uploaded_image.seek(0)
                    image_base64 = image_to_base64(uploaded_image)
                except Exception as e:
                    st.error(f"❌ 圖片處理失敗：{e}")
                    return

            all_errors = []
            results    = {}

            st.markdown("---")
            st.markdown("### 🤖 Step 1：AI 分析")
            with st.spinner("分析中..."):
                try:
                    result = analyze_prompt(user_input, keys["openai"], image_base64)
                    st.success("✅ 分析完成")
                    with st.expander("查看分析結果"):
                        st.json(result)
                    results["analysis"] = result
                except Exception as e:
                    st.error(f"❌ 分析失敗：{e}")
                    return

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

            narration = result.get("narration", "").strip()

            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                video_future = executor.submit(
                    safe_generate_video,
                    result["video_prompt"],
                    keys["kling_access"],
                    keys["kling_secret"],
                    image_base64,
                    lambda i, t, s: None,
                    video_duration,
                    aspect_ratio
                )
                voice_future = executor.submit(
                    safe_generate_voice,
                    narration,
                    keys["elevenlabs"],
                    keys.get("elevenlabs_voice", "")
                ) if enable_voice and narration else None

                music_future = executor.submit(
                    safe_generate_music,
                    result.get("music_mood", "calm"),
                    result.get("music_genre", "cinematic"),
                    keys["beatoven"],
                    30,
                    lambda i, t, s: None
                ) if enable_music else None

                try:
                    video_url = video_future.result()
                    video_progress.progress(1.0)
                    video_status.success("✅ 影片完成")
                    results["video_url"] = video_url
                except Exception as e:
                    err = f"❌ 影片生成失敗：{str(e)[:80]}"
                    video_status.error(err)
                    all_errors.append(err)

                if voice_future:
                    try:
                        results["audio"] = voice_future.result()
                        audio_progress.progress(1.0)
                        audio_status.success("✅ 語音完成")
                    except Exception as e:
                        err = f"🎙️ 語音生成失敗：{str(e)[:80]}"
                        audio_status.error(err)
                        all_errors.append(err)

                if music_future:
                    try:
                        results["music"] = music_future.result()
                        music_progress.progress(1.0)
                        music_status.success("✅ 音樂完成")
                    except Exception as e:
                        err = f"🎵 音樂生成失敗：{str(e)[:80]}"
                        music_status.error(err)
                        all_errors.append(err)

            if "video_url" not in results:
                st.error("❌ 影片生成失敗，無法繼續")
                return

            st.session_state.last_result = {
                "mode":        "單場景",
                "timestamp":   time.strftime("%Y-%m-%d %H:%M:%S"),
                "video_urls":  [results["video_url"]],
                "audio_bytes": results.get("audio"),
                "music_bytes": results.get("music"),
                "narration":   narration,
                "errors":      all_errors
            }

            record = {
                "timestamp":  time.strftime("%Y-%m-%d %H:%M:%S"),
                "mode":       "單場景",
                "narration":  narration,
                "video_urls": [results["video_url"]],
                "errors":     all_errors
            }
            st.session_state.history.append(record)
            save_history(st.session_state.history)

            if enable_gdrive:
                st.markdown("---")
                st.markdown("### ☁️ Step 3：儲存至 Google Drive")
                with st.spinner("上傳中..."):
                    gdrive_errors = run_gdrive_upload(
                        video_urls=[results["video_url"]],
                        audio_bytes=results.get("audio"),
                        music_bytes=results.get("music"),
                        keys=keys,
                        prefix="single"
                    )
                    all_errors.extend(gdrive_errors)

            st.rerun()

    # ==================================================
    # 模式 B：多角色分鏡模式
    # ==================================================
    elif mode == "🎭 多角色分鏡模式":

        st.subheader("🎭 Step 1：建立角色")

        with st.form("character_form"):
            char_name    = st.text_input("角色名稱", placeholder="例如：主角小明")
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
                            all_b64 = []
                            for f in char_uploads:
                                f.seek(0)
                                all_b64.append(image_to_base64(f))

                            desc_result = analyze_prompt(
                                "請詳細描述這個角色的外觀特徵，包含髮型、服裝、臉部特徵",
                                keys["openai"],
                                all_b64[0]
                            )
                            char_desc = (
                                desc_result.get("narration")
                                or desc_result.get("video_prompt")
                                or "角色外觀待描述"
                            )
                            st.session_state.characters.append({
                                "name":       char_name,
                                "images_b64": all_b64,
                                "desc":       char_desc
                            })
                            st.success(f"✅ 角色「{char_name}」建立完成")
                            st.caption(f"外觀描述：{char_desc[:60]}...")
                        except Exception as e:
                            st.error(f"❌ 角色建立失敗：{e}")

        if st.session_state.characters:
            col_title, col_clear = st.columns([3, 1])
            with col_title:
                st.markdown("**已建立角色：**")
            with col_clear:
                if st.button("🗑️ 清除全部角色", type="secondary", use_container_width=True):
                    clear_all_characters()

            for i, c in enumerate(st.session_state.characters):
                col1, col2, col3, col4 = st.columns([1, 1, 3, 1])
                with col1:
                    st.markdown(f"**{chr(65+i)}. {c['name']}**")
                with col2:
                    if c.get("images_b64"):
                        st.success("📸 有照片")
                    else:
                        st.info("🤖 AI 描述")
                with col3:
                    st.caption(c["desc"][:80] + "...")
                with col4:
                    if st.button("🗑️", key=f"del_{i}"):
                        st.session_state.characters.pop(i)
                        st.rerun()

        st.divider()

        st.subheader("🎬 Step 2：選擇出場角色")
        selected_chars = []
        if st.session_state.characters:
            cols = st.columns(min(len(st.session_state.characters), 4))
            for i, c in enumerate(st.session_state.characters):
                with cols[i % 4]:
                    if st.checkbox(
                        f"{chr(65+i)}. {c['name']}", value=True, key=f"sel_{i}"
                    ):
                        selected_chars.append(c)
        else:
            st.info("請先在上方建立角色")

        st.divider()

        st.subheader("📝 Step 3：輸入劇情與設定")
        user_input = st.text_area(
            "描述故事劇情",
            placeholder="例如：美女在公園遇見帥哥，兩人一起看夕陽，最後依依不捨地道別...",
            height=160,
            key="multi_input"
        )

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
                "秒數設定", ["快速選擇", "自訂秒數"], key="multi_dur_type"
            )
        with col_set3:
            if duration_type == "快速選擇":
                video_duration = st.selectbox(
                    "每個分鏡長度", [5, 10], key="multi_dur_select"
                )
            else:
                video_duration = st.number_input(
                    "自訂秒數（每個分鏡）",
                    min_value=3, max_value=60, value=5, step=1,
                    key="multi_dur_custom"
                )
        st.info(f"📐 比例：**{aspect_ratio}** ｜ ⏱️ 每個分鏡：**{video_duration} 秒**")

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
                        boards = storyboard_result.get("storyboard", [])
                        st.session_state.storyboard      = boards
                        st.session_state.storyboard_meta = storyboard_result
                        st.success(f"✅ 分鏡腳本生成完成，共 {len(boards)} 個分鏡")
                    except Exception as e:
                        st.error(f"❌ 分鏡生成失敗：{e}")

        if st.session_state.storyboard:
            st.subheader("📋 分鏡腳本預覽（可編輯）")
            for i, s in enumerate(st.session_state.storyboard):
                with st.expander(
                    f"分鏡 {i+1}｜角色：{', '.join(s.get('characters', []))}",
                    expanded=True
                ):
                    st.text_area(
                        "場景描述（英文）",
                        value=s.get("scene", ""),
                        key=f"edit_scene_{i}",
                        height=80
                    )
                    st.text_input(
                        "旁白（中文）",
                        value=s.get("narration", ""),
                        key=f"edit_narr_{i}"
                    )
                    scene_chars = s.get("characters", [])
                    photo_info  = []
                    for lbl in scene_chars:
                        cidx = ord(lbl) - 65
                        if 0 <= cidx < len(selected_chars):
                            c = selected_chars[cidx]
                            if c.get("images_b64"):
                                photo_info.append(f"角色 {lbl}（{c['name']}）📸")
                            else:
                                photo_info.append(f"角色 {lbl}（{c['name']}）🤖")
                    if photo_info:
                        st.caption(f"參考來源：{' ｜ '.join(photo_info)}")

        st.divider()

        if st.button(
            "🚀 開始生成所有分鏡影片",
            type="primary",
            use_container_width=True,
            key="multi_gen"
        ):
            if not st.session_state.storyboard:
                st.warning("⚠️ 請先點「🎬 生成分鏡腳本」按鈕")
                return
            if not selected_chars:
                st.warning("⚠️ 請在 Step 2 勾選出場角色")
                return
            if not check_required_keys(keys, enable_voice, enable_music):
                return

            all_errors      = []
            meta            = st.session_state.storyboard_meta
            chars_snapshot  = [dict(c) for c in selected_chars]
            boards_snapshot = get_edited_storyboard()
            total_scenes    = len(boards_snapshot)

            has_photo_count = sum(1 for c in chars_snapshot if c.get("images_b64"))
            st.info(
                f"📊 共 {total_scenes} 個分鏡 ｜ "
                f"📸 {has_photo_count} 個角色使用照片 ｜ "
                f"🤖 {len(chars_snapshot) - has_photo_count} 個角色使用 AI 描述"
            )

            st.markdown("---")
            st.markdown("### ⚡ 並行生成所有分鏡")

            scene_cols     = st.columns(min(total_scenes, 4))
            scene_status   = [col.empty()     for col in scene_cols]
            scene_progress = [col.progress(0) for col in scene_cols]

            for i in range(total_scenes):
                scene_status[i].info(f"🎬 分鏡 {i+1}\n等待中...")

            collected = run_parallel_video_generation(
                boards_snapshot, chars_snapshot,
                video_duration, aspect_ratio,
                keys, scene_status, scene_progress
            )

            video_urls = [
                collected[i][0]
                for i in range(total_scenes)
                if collected.get(i) and collected[i][0]
            ]
            video_errors = [
                f"❌ 分鏡 {i+1} 失敗：{collected[i][1]}"
                for i in range(total_scenes)
                if collected.get(i) and collected[i][1]
            ]
            all_errors.extend(video_errors)

            if not video_urls:
                st.error("❌ 所有分鏡都生成失敗，請檢查 Kling API 設定")
                return

            st.markdown("---")
            st.markdown("### 🎵 生成語音與音樂")
            narration_text = meta.get("narration", "").strip()
            audio_bytes, music_bytes, audio_errors = run_parallel_audio_generation(
                narration_text,
                meta.get("music_mood", "calm"),
                meta.get("music_genre", "cinematic"),
                enable_voice, enable_music, keys
            )
            all_errors.extend(audio_errors)

            st.session_state.last_result = {
                "mode":        "多角色分鏡",
                "timestamp":   time.strftime("%Y-%m-%d %H:%M:%S"),
                "video_urls":  video_urls,
                "audio_bytes": audio_bytes,
                "music_bytes": music_bytes,
                "narration":   narration_text,
                "errors":      all_errors
            }

            record = {
                "timestamp":  time.strftime("%Y-%m-%d %H:%M:%S"),
                "mode":       "多角色分鏡",
                "narration":  narration_text,
                "video_urls": video_urls,
                "errors":     all_errors
            }
            st.session_state.history.append(record)
            save_history(st.session_state.history)

            if enable_gdrive:
                st.markdown("---")
                st.markdown("### ☁️ 儲存至 Google Drive")
                with st.spinner("上傳中..."):
                    gdrive_errors = run_gdrive_upload(
                        video_urls, audio_bytes, music_bytes, keys, "multi"
                    )
                    all_errors.extend(gdrive_errors)

            st.rerun()

    # ==================================================
    # 模式 C：AI 劇本創作
    # ==================================================
    elif mode == "✍️ AI 劇本創作":

        st.subheader("✍️ AI 劇本創作")
        st.caption("輸入一句話，AI 自動生成完整劇本、角色、分鏡，並直接生成影片")

        col_idea, col_setting = st.columns([2, 1])

        with col_idea:
            idea = st.text_area(
                "💡 一句話概念",
                placeholder=(
                    "例如：一個外賣員愛上了客戶\n"
                    "例如：太空人在火星發現了一朵花\n"
                    "例如：老奶奶在咖啡廳等了一個人五十年"
                ),
                height=120,
                key="script_idea"
            )

            st.markdown("**📸 角色照片（選填）**")
            st.caption("上傳後 AI 會用你的照片生成影片，角色一致性更佳")
            photo_cols = st.columns(4)
            for i, label in enumerate(["A", "B", "C", "D"]):
                with photo_cols[i]:
                    f = st.file_uploader(
                        f"角色 {label}",
                        type=["jpg", "jpeg", "png"],
                        key=f"script_photo_{label}"
                    )
                    if f:
                        st.image(f, caption=f"角色 {label}", use_container_width=True)

        with col_setting:
            st.markdown("**🎬 影片設定**")
            ending_type = st.radio(
                "結局類型",
                ["喜劇 😊", "悲劇 😢", "懸疑 🔍", "開放式 🌀"],
                key="script_ending"
            )
            ending_map = {
                "喜劇 😊": "喜劇",
                "悲劇 😢": "悲劇",
                "懸疑 🔍": "懸疑",
                "開放式 🌀": "開放式"
            }
            ending_type_clean = ending_map[ending_type]

            orientation = st.radio(
                "畫面方向",
                ["🖥️ 橫式 16:9", "📱 直式 9:16"],
                key="script_orientation"
            )
            aspect_ratio_map = {
                "🖥️ 橫式 16:9": "16:9",
                "📱 直式 9:16": "9:16"
            }
            aspect_ratio = aspect_ratio_map[orientation]

            video_duration = st.selectbox(
                "每個分鏡長度", [5, 10], key="script_duration"
            )

        if st.button("🎬 生成劇本", use_container_width=True, key="script_gen"):
            if not idea.strip():
                st.warning("⚠️ 請輸入一句話概念")
            elif not keys["openai"]:
                st.error("❌ 缺少 OpenAI API 金鑰")
            else:
                photos = {}
                for label in ["A", "B", "C", "D"]:
                    f = st.session_state.get(f"script_photo_{label}")
                    if f:
                        try:
                            f.seek(0)
                            photos[label] = image_to_base64(f)
                        except Exception:
                            pass
                st.session_state.script_photos = photos

                with st.spinner("AI 正在創作劇本..."):
                    try:
                        script = generate_script_from_idea(
                            idea.strip(),
                            ending_type_clean,
                            keys["openai"]
                        )
                        st.session_state.script = script
                        st.success("✅ 劇本生成完成")

                        if photos:
                            matched = []
                            for i, c in enumerate(script.get("characters", [])):
                                lbl = c.get("label", chr(65+i))
                                if lbl in photos:
                                    matched.append(f"角色 {lbl}（{c.get('name','')}）")
                            if matched:
                                st.info(f"📸 已綁定照片的角色：{', '.join(matched)}")
                    except Exception as e:
                        st.error(f"❌ 劇本生成失敗：{e}")

        if st.session_state.get("script"):
            script      = st.session_state.script
            char_photos = st.session_state.get("script_photos", {})

            st.divider()

            col_info1, col_info2 = st.columns(2)
            with col_info1:
                st.markdown(f"### 🎬 {script.get('title', '未命名')}")
                st.info(f"📖 {script.get('logline', '')}")
                st.caption(
                    f"結局：{script.get('ending_description', '')} ｜ "
                    f"高潮：第 {script.get('climax_point', '?')} 個分鏡"
                )

            with col_info2:
                st.markdown("**🎭 角色**")
                for i, c in enumerate(script.get("characters", [])):
                    lbl       = c.get("label", chr(65+i))
                    has_photo = lbl in char_photos
                    with st.expander(
                        f"{'📸 ' if has_photo else '🤖 '}{lbl}. {c.get('name','?')}"
                        f"{'（已綁定照片）' if has_photo else '（AI 生成）'}"
                    ):
                        st.caption(f"性格：{c.get('personality','')}")
                        st.caption(f"動機：{c.get('motivation','')}")
                        st.caption(f"外觀：{c.get('appearance','')[:80]}...")
                        if has_photo:
                            st.success("✅ 將使用上傳照片生成影片")
                        else:
                            st.info("ℹ️ 將使用 AI 文字描述生成影片")

            st.divider()

            st.subheader("📋 分鏡腳本")
            storyboard = script.get("storyboard", [])
            climax_idx = script.get("climax_point", 0) - 1

            for i, s in enumerate(storyboard):
                is_climax = (i == climax_idx) or s.get("is_climax", False)
                label     = (
                    f"{'🔥 ' if is_climax else ''}"
                    f"分鏡 {i+1}｜{s.get('location','')}｜"
                    f"{s.get('camera','')}｜節奏：{s.get('pacing','')}"
                )
                with st.expander(label, expanded=True):
                    col_a, col_b = st.columns(2)
                    with col_a:
                        st.text_area(
                            "場景描述（英文）",
                            value=s.get("scene", ""),
                            key=f"script_scene_{i}",
                            height=80
                        )
                    with col_b:
                        st.text_input(
                            "旁白（中文）",
                            value=s.get("narration", ""),
                            key=f"script_narr_{i}"
                        )
                        st.text_input
