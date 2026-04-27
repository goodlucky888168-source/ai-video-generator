import json
import re
import time
import concurrent.futures

import requests
import streamlit as st

from config import get_api_keys
from api.openai_api import analyze_prompt, image_to_base64
from api.kling_api import generate_video
from api.elevenlabs_api import generate_voice
from api.beatoven_api import generate_music
from api.gdrive_api import upload_to_drive, upload_video_from_url

# ==================== 全域常數 ====================
MAX_WORKERS = 3

GLOBAL_STYLE = (
    "cinematic lighting, soft warm color tone, consistent color grading, "
    "same lighting style, high detail, realistic"
)

ASPECT_RATIO_MAP = {
    "🖥️ 橫式 16:9": "16:9",
    "📱 直式 9:16": "9:16",
    "⬛ 正方 1:1":  "1:1",
}

ENDING_MAP = {
    "喜劇 😊": "喜劇",
    "悲劇 😢": "悲劇",
    "懸疑 🔍": "懸疑",
    "開放式 🌀": "開放式",
}

# ==================== 重試裝飾器 ====================
def retry_api(max_retries: int = 3, delay_base: float = 2.0):
    def decorator(func):
        from functools import wraps
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exc = e
                    if attempt < max_retries - 1:
                        time.sleep(delay_base * (attempt + 1))
            raise last_exc
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

# ==================== Session 初始化 ====================
def init_session():
    defaults = {
        "tasks":           {},
        "characters":      [],
        "storyboard":      [],
        "storyboard_meta": {},
        "script":          {},
        "history":         [],
        "authenticated":   False,
        "login_attempts":  0,
        "lockout_until":   0.0,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

# ==================== 清除角色 ====================
def clear_all_characters():
    st.session_state.characters      = []
    st.session_state.storyboard      = []
    st.session_state.storyboard_meta = {}
    st.session_state.script          = {}
    prefixes = ("edit_scene_", "edit_narr_", "sel_", "del_",
                "script_scene_", "script_narr_", "script_dial_")
    for k in [k for k in list(st.session_state.keys()) if k.startswith(prefixes)]:
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
            st.error(f"⛔ 嘗試次數過多，請等待 {int(st.session_state.lockout_until - now)} 秒後再試")
            return False
        if st.button("登入", type="primary"):
            if (username == st.secrets.get("APP_USERNAME") and
                    password == st.secrets.get("APP_PASSWORD")):
                st.session_state.authenticated  = True
                st.session_state.login_attempts = 0
                st.rerun()
            else:
                st.session_state.login_attempts += 1
                st.error(f"帳號或密碼錯誤（第 {st.session_state.login_attempts} 次）")
                if st.session_state.login_attempts >= 5:
                    st.session_state.lockout_until = now + 60
                    st.rerun()
    return False

# ==================== 共用 UI 元件 ====================
def render_api_settings(keys: dict):
    with st.expander("⚙️ API 金鑰設定狀態", expanded=False):
        st.caption(f"目前模式：{'🟢 主要 (main)' if keys.get('mode') == 'main' else '🟡 備用 (backup)'}")
        for name, val in {
            "OpenAI":              keys.get("openai", ""),
            "Kling Access":        keys.get("kling_access", ""),
            "Kling Secret":        keys.get("kling_secret", ""),
            "ElevenLabs":          keys.get("elevenlabs", ""),
            "Beatoven":            keys.get("beatoven", ""),
            "Google Drive Folder": keys.get("gdrive_folder", ""),
        }.items():
            c1, c2 = st.columns(2)
            c1.text(name)
            if val:
                c2.success(f"✅ {val[:4]}****{val[-4:] if len(val) > 8 else ''}")
            else:
                c2.error("❌ 未設定")


def check_required_keys(keys: dict, require_voice: bool, require_music: bool) -> bool:
    missing = []
    if not keys.get("openai"):       missing.append("OpenAI")
    if not keys.get("kling_access"): missing.append("Kling Access Key")
    if not keys.get("kling_secret"): missing.append("Kling Secret Key")
    if require_voice and not keys.get("elevenlabs"): missing.append("ElevenLabs")
    if require_music and not keys.get("beatoven"):   missing.append("Beatoven")
    if missing:
        st.error(f"❌ 缺少必要 API 金鑰：{', '.join(missing)}")
        return False
    return True


def render_history():
    if not st.session_state.history:
        return
    with st.expander(f"📂 生成歷史（共 {len(st.session_state.history)} 筆）", expanded=False):
        for i, rec in enumerate(reversed(st.session_state.history)):
            idx = len(st.session_state.history) - i
            st.markdown(f"**#{idx} — {rec.get('timestamp','')}**")
            st.caption(f"模式：{rec.get('mode','')} ｜ 旁白：{rec.get('narration','')[:30]}")
            urls = rec.get("video_urls", [])
            if urls:
                cols = st.columns(min(len(urls), 3))
                for j, u in enumerate(urls):
                    cols[j % 3].video(u)
            st.divider()


def render_download_button(url: str, label: str, filename: str):
    try:
        with requests.get(url, timeout=120, stream=True) as resp:
            if resp.status_code == 200:
                data = b"".join(c for c in resp.iter_content(1024 * 1024) if c)
                st.download_button(label=label, data=data, file_name=filename,
                                   mime="video/mp4", use_container_width=True)
            else:
                st.caption(f"⚠️ 無法下載（HTTP {resp.status_code}）[直接開啟]({url})")
    except requests.Timeout:
        st.caption(f"⚠️ 下載逾時，[直接開啟]({url})")
    except Exception as e:
        st.caption(f"⚠️ 下載失敗（{e}），[直接開啟]({url})")


def render_video_results(video_urls: list, audio_bytes, music_bytes, narration_text: str = ""):
    if not video_urls:
        st.warning("⚠️ 沒有可顯示的影片")
        return
    st.markdown("**🎬 各分鏡影片**")
    cols = st.columns(min(len(video_urls), 4))
    for i, url in enumerate(video_urls):
        with cols[i % len(cols)]:
            st.markdown(f"**分鏡 {i+1}**")
            st.video(url)
            render_download_button(url, f"⬇️ 下載分鏡 {i+1}",
                                   f"scene{i+1}_{time.strftime('%Y%m%d_%H%M%S')}.mp4")
    c1, c2 = st.columns(2)
    with c1:
        if audio_bytes:
            st.markdown("**🎙️ 語音旁白**")
            if narration_text:
                st.caption(narration_text)
            st.audio(audio_bytes, format="audio/mp3")
    with c2:
        if music_bytes:
            st.markdown("**🎵 背景音樂**")
            st.audio(music_bytes, format="audio/mp3")


def _render_video_settings(key_prefix: str, show_square: bool = True) -> tuple[str, int]:
    """共用影片設定 UI，回傳 (aspect_ratio, video_duration)"""
    options = ["🖥️ 橫式 16:9", "📱 直式 9:16"]
    if show_square:
        options.append("⬛ 正方 1:1")

    c1, c2, c3 = st.columns(3)
    with c1:
        orientation = st.radio("畫面方向", options, key=f"{key_prefix}_orientation")
    with c2:
        dur_type = st.radio("秒數設定", ["快速選擇", "自訂秒數"], key=f"{key_prefix}_dur_type")
    with c3:
        if dur_type == "快速選擇":
            duration = st.selectbox("影片長度", [5, 10], key=f"{key_prefix}_dur_select")
        else:
            duration = st.number_input("自訂秒數", min_value=3, max_value=60,
                                       value=5, step=1, key=f"{key_prefix}_dur_custom")

    aspect_ratio = ASPECT_RATIO_MAP[orientation]
    st.info(f"📐 比例：**{aspect_ratio}** ｜ ⏱️ 長度：**{duration} 秒**")
    return aspect_ratio, duration


def _make_scene_ui(total: int) -> tuple[list, list]:
    """建立分鏡狀態列與進度條，長度保證 == total"""
    cols           = st.columns(min(total, 4))
    scene_status   = [cols[i % len(cols)].empty()     for i in range(total)]
    scene_progress = [cols[i % len(cols)].progress(0) for i in range(total)]
    for i in range(total):
        scene_status[i].info(f"🎬 分鏡 {i+1}\n等待中...")
    return scene_status, scene_progress

# ==================== Prompt 建構 ====================
def build_scene_prompt(scene: dict, characters: list) -> str:
    desc = ""
    for label in scene.get("characters", []):
        idx = ord(label.upper()) - 65
        if 0 <= idx < len(characters):
            c = characters[idx]
            desc += f"{c['name']}: {c.get('appearance') or c.get('desc') or ''}\n"

    climax = "dramatic lighting, intense atmosphere, emotional peak," if scene.get("is_climax") else ""
    extra  = ""
    if scene.get("camera"): extra += f"{scene['camera']} shot, "
    if scene.get("pacing"): extra += f"{scene['pacing']} pacing, "

    return (f"{GLOBAL_STYLE}\n{climax}\n{extra}\n"
            f"Characters:\n{desc}\nScene:\n{scene['scene']}\n\n"
            "keep same character appearance,\n"
            "no face change, no face mixing,\n"
            "consistent style throughout").strip()


def build_scene_prompt_by_label(scene: dict, chars_by_label: dict) -> str:
    desc = ""
    for label in scene.get("characters", []):
        c = chars_by_label.get(label.upper())
        if c:
            desc += f"{c['name']}: {c.get('appearance') or c.get('desc') or ''}\n"

    climax = "dramatic lighting, intense atmosphere, emotional peak," if scene.get("is_climax") else ""
    extra  = ""
    if scene.get("camera"): extra += f"{scene['camera']} shot, "
    if scene.get("pacing"): extra += f"{scene['pacing']} pacing, "

    return (f"{GLOBAL_STYLE}\n{climax}\n{extra}\n"
            f"Characters:\n{desc}\nScene:\n{scene['scene']}\n\n"
            "keep same character appearance,\n"
            "no face change, no face mixing,\n"
            "consistent style throughout").strip()

# ==================== AI 分析 ====================
def generate_storyboard(user_input: str, characters: list, openai_key: str) -> dict:
    char_desc = "\n".join(
        f"Character {chr(65+i)} ({c['name']}): {c.get('appearance') or c.get('desc') or ''}"
        for i, c in enumerate(characters)
    )
    prompt = f"""你是專業電影導演，請根據以下劇情和角色，拆成3個分鏡。
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
{char_desc}"""
    return analyze_prompt(prompt, openai_key)


def safe_parse_json(raw: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return json.loads(cleaned.strip())


def generate_script_from_idea(idea: str, ending_type: str, openai_key: str) -> dict:
    prompt = f"""你是專業電影編劇。請將以下「一句話概念」擴展成完整腳本。
概念：{idea}
結局類型：{ending_type}

要求輸出 JSON 格式（不要加 markdown code block）：
{{
  "title": "影片標題",
  "logline": "一句話故事摘要",
  "characters": [
    {{"name":"角色名","label":"A","personality":"性格","appearance":"外觀（英文）","motivation":"動機"}}
  ],
  "storyboard": [
    {{"scene":"場景（英文）","location":"地點","characters":["A"],
      "dialogue":"對話（中文）","narration":"旁白（中文）",
      "camera":"特寫/中景/全景","pacing":"慢/中/快","is_climax":false}}
  ],
  "ending_description": "結局（中文）",
  "climax_point": 2,
  "music_mood": "romantic",
  "music_genre": "acoustic",
  "narration": "整體旁白摘要（30字以內）"
}}
注意：storyboard 請生成 4 個分鏡，climax_point 必須是 1~4 的整數，只回傳 JSON。"""
    result = analyze_prompt(prompt, openai_key)
    if isinstance(result, str):
        result = safe_parse_json(result)
    return result

# ==================== 並行生成 ====================
def run_parallel_video_generation(
    boards: list, characters, video_duration: int, aspect_ratio: str,
    keys: dict, scene_status: list, scene_progress: list,
    use_label_dict: bool = False
) -> dict:
    """
    characters：
      - use_label_dict=False → list（模式 A/B）
      - use_label_dict=True  → dict {label: char}（模式 C）
    """
    def generate_one(scene, idx):
        try:
            prompt = (build_scene_prompt_by_label(scene, characters)
                      if use_label_dict
                      else build_scene_prompt(scene, characters))

            ref_img = None
            if not use_label_dict:
                labels = scene.get("characters", [])
                if labels:
                    ci = ord(labels[0].upper()) - 65
                    if 0 <= ci < len(characters):
                        imgs = characters[ci].get("images_b64", [])
                        if imgs:
                            ref_img = imgs[0]

            url = safe_generate_video(
                prompt, keys["kling_access"], keys["kling_secret"],
                ref_img, lambda *_: None, video_duration, aspect_ratio
            )
            return idx, url, None
        except Exception as e:
            return idx, None, str(e)

    collected: dict[int, tuple] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        future_map = {ex.submit(generate_one, s, i): i for i, s in enumerate(boards)}
        for f in concurrent.futures.as_completed(future_map):
            try:
                idx, url, err = f.result()
            except Exception as e:
                idx, url, err = future_map[f], None, str(e)
            collected[idx] = (url, err)
            if err:
                scene_status[idx].error(f"❌ 分鏡 {idx+1} 失敗\n{err[:60]}")
            else:
                scene_status[idx].success(f"✅ 分鏡 {idx+1} 完成")
            scene_progress[idx].progress(1.0)
    return collected


def run_parallel_audio_generation(
    narration_text: str, music_mood: str, music_genre: str,
    enable_voice: bool, enable_music: bool, keys: dict
) -> tuple:
    can_voice = enable_voice and bool(narration_text) and bool(keys.get("elevenlabs"))
    can_music = enable_music and bool(keys.get("beatoven"))

    c1, c2 = st.columns(2)
    v_status = c1.empty(); v_prog = c1.progress(0)
    m_status = c2.empty(); m_prog = c2.progress(0)
    v_status.info("🎙️ 語音生成中..." if can_voice else "🎙️ 已跳過")
    m_status.info("🎵 音樂生成中..." if can_music else "🎵 已跳過")

    audio_bytes = music_bytes = None
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        vf = ex.submit(safe_generate_voice, narration_text,
                       keys["elevenlabs"], keys.get("elevenlabs_voice", "")) if can_voice else None
        mf = ex.submit(safe_generate_music, music_mood, music_genre,
                       keys["beatoven"], 30, lambda *_: None)         if can_music else None

        for future, status, prog, name, key in [
            (vf, v_status, v_prog, "語音", "audio_bytes"),
            (mf, m_status, m_prog, "音樂", "music_bytes"),
        ]:
            if future:
                try:
                    val = future.result()
                    prog.progress(1.0)
                    status.success(f"✅ {name}完成")
                    if name == "語音": audio_bytes = val
                    else:             music_bytes = val
                except Exception as e:
                    status.error(f"❌ {name}失敗：{str(e)[:60]}")
                    prog.progress(1.0)
    return audio_bytes, music_bytes


def run_gdrive_upload(video_urls: list, audio_bytes, music_bytes, keys: dict, prefix: str = "video"):
    if not keys.get("gdrive_folder") or not keys.get("gdrive_sa_json"):
        st.warning("⚠️ 缺少 Google Drive 設定")
        return
    ts          = time.strftime("%Y%m%d_%H%M%S")
    safe_prefix = re.sub(r"[^\w\-]", "", prefix)[:20]
    try:
        for i, url in enumerate(video_urls):
            if not url: continue
            link = upload_video_from_url(
                video_url=url, filename=f"{safe_prefix}_scene{i+1}_{ts}.mp4",
                folder_id=keys["gdrive_folder"], sa_json_str=keys["gdrive_sa_json"])
            st.success(f"✅ 分鏡 {i+1} 已上傳：[點此開啟]({link})")
        for content, name, mime in [
            (audio_bytes, "narration", "audio/mpeg"),
            (music_bytes, "music",     "audio/mpeg"),
        ]:
            if content:
                link = upload_to_drive(
                    content=content, filename=f"{safe_prefix}_{name}_{ts}.mp3",
                    mimetype=mime, folder_id=keys["gdrive_folder"],
                    sa_json_str=keys["gdrive_sa_json"])
                st.success(f"✅ {name} 已上傳：[點此開啟]({link})")
    except Exception as e:
        st.error(f"❌ Google Drive 上傳失敗：{e}")

# ==================== 模式 A ====================
def _render_mode_single(keys, enable_voice, enable_music, enable_gdrive):
    col_input, col_image = st.columns([2, 1])
    with col_input:
        st.subheader("📝 影片描述")
        user_input = st.text_area("描述你想要的影片內容",
            placeholder="例如：夕陽下的海邊，海浪輕拍岸邊，氣氛寧靜祥和...",
            height=160, key="single_input")
        st.markdown("**🎬 影片設定**")
        aspect_ratio, video_duration = _render_video_settings("single", show_square=True)

    with col_image:
        st.subheader("📸 角色圖片（選填）")
        uploaded = st.file_uploader("上傳角色照片", type=["jpg","jpeg","png"],
                                    help="上傳後使用 image2video，角色一致性更佳")
        if uploaded:
            st.image(uploaded, caption="已上傳角色圖片", use_container_width=True)
            st.info("✅ 將使用 image2video 模式")
        st.markdown("**畫面比例預覽**")
        w, h, lbl = {"16:9":("160px","90px","🖥️ 16:9"),
                     "9:16":("90px","160px","📱 9:16"),
                     "1:1": ("120px","120px","⬛ 1:1")}[aspect_ratio]
        st.markdown(
            f"<div style='background:#333;width:{w};height:{h};border-radius:6px;"
            f"display:flex;align-items:center;justify-content:center;"
            f"color:white;font-size:12px;text-align:center'>{lbl}</div>",
            unsafe_allow_html=True)

    if not st.button("🚀 開始生成", type="primary", use_container_width=True, key="single_gen"):
        return
    if not user_input.strip():
        st.warning("⚠️ 請輸入影片描述"); return
    if not check_required_keys(keys, enable_voice, enable_music):
        return

    image_b64 = None
    if uploaded:
        try:
            uploaded.seek(0); image_b64 = image_to_base64(uploaded)
        except Exception as e:
            st.error(f"❌ 圖片處理失敗：{e}"); return

    st.markdown("---")
    st.markdown("### 🤖 Step 1：AI 分析")
    with st.spinner("分析中..."):
        try:
            result = analyze_prompt(user_input, keys["openai"], image_b64)
            st.success("✅ 分析完成")
            with st.expander("查看分析結果"): st.json(result)
        except Exception as e:
            st.error(f"❌ 分析失敗：{e}"); return

    st.markdown("---")
    st.markdown("### ⚡ Step 2：並行生成")
    cv, ca, cm = st.columns(3)
    v_st = cv.empty(); v_pr = cv.progress(0)
    a_st = ca.empty(); a_pr = ca.progress(0)
    m_st = cm.empty(); m_pr = cm.progress(0)
    v_st.info("🎬 影片生成中...")
    a_st.info("🎙️ 語音生成中..." if enable_voice else "🎙️ 已跳過")
    m_st.info("🎵 音樂生成中..." if enable_music else "🎵 已跳過")

    narration = result.get("narration", "").strip()
    can_voice = enable_voice and bool(narration) and bool(keys.get("elevenlabs"))
    can_music = enable_music and bool(keys.get("beatoven"))
    results   = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        vf = ex.submit(safe_generate_video, result["video_prompt"],
                       keys["kling_access"], keys["kling_secret"],
                       image_b64, lambda *_: None, video_duration, aspect_ratio)
        af = ex.submit(safe_generate_voice, narration,
                       keys["elevenlabs"], keys.get("elevenlabs_voice","")) if can_voice else None
        mf = ex.submit(safe_generate_music, result.get("music_mood","calm"),
                       result.get("music_genre","cinematic"),
                       keys["beatoven"], 30, lambda *_: None)              if can_music else None

        try:
            results["video_url"] = vf.result()
            v_pr.progress(1.0); v_st.success("✅ 影片完成")
        except Exception as e:
            v_st.error(f"❌ 影片失敗：{e}"); v_pr.progress(1.0); return

        for f, st_w, pr_w, key, label in [
            (af, a_st, a_pr, "audio", "語音"),
            (mf, m_st, m_pr, "music", "音樂"),
        ]:
            if f:
                try:
                    results[key] = f.result()
                    pr_w.progress(1.0); st_w.success(f"✅ {label}完成")
                except Exception as e:
                    st_w.error(f"❌ {label}失敗：{str(e)[:60]}"); pr_w.progress(1.0)

    st.markdown("---")
    st.markdown("### 🎉 Step 3：生成結果")
    c1, c2 = st.columns(2)
    with c1:
        if "video_url" in results:
            st.markdown("**🎬 影片**")
            st.video(results["video_url"])
            st.caption(f"旁白：{narration}")
            render_download_button(results["video_url"], "⬇️ 下載影片",
                                   f"video_{time.strftime('%Y%m%d_%H%M%S')}.mp4")
    with c2:
        if "audio" in results:
            st.markdown("**🎙️ 語音旁白**"); st.audio(results["audio"], format="audio/mp3")
        if "music" in results:
            st.markdown("**🎵 背景音樂**"); st.audio(results["music"], format="audio/mp3")

    st.session_state.history.append({
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"), "mode": "單場景",
        "narration": narration,
        "video_urls": [results["video_url"]] if "video_url" in results else [],
    })

    if enable_gdrive and "video_url" in results:
        st.markdown("---"); st.markdown("### ☁️ Step 4：儲存至 Google Drive")
        with st.spinner("上傳中..."):
            run_gdrive_upload([results["video_url"]], results.get("audio"),
                              results.get("music"), keys, "single")

# ==================== 模式 B ====================
def _render_mode_multi(keys, enable_voice, enable_music, enable_gdrive):
    st.subheader("🎭 Step 1：建立角色")
    with st.form("character_form"):
        char_name    = st.text_input("角色名稱", placeholder="例如：主角小明")
        char_uploads = st.file_uploader("上傳角色參考圖（可多張）",
                                        type=["jpg","jpeg","png"], accept_multiple_files=True)
        if st.form_submit_button("➕ 新增角色"):
            if not char_name:
                st.warning("請輸入角色名稱")
            elif not char_uploads:
                st.warning("請上傳至少一張角色圖片")
            else:
                with st.spinner("分析角色外觀中..."):
                    try:
                        all_b64 = []
                        for f in char_uploads:
                            f.seek(0); all_b64.append(image_to_base64(f))
                        res = analyze_prompt(
                            "請詳細描述這個角色的外觀特徵，包含髮型、服裝、臉部特徵",
                            keys["openai"], all_b64[0])
                        desc = res.get("narration") or res.get("video_prompt") or "角色外觀待描述"
                        st.session_state.characters.append({
                            "name": char_name, "images_b64": all_b64,
                            "desc": desc, "appearance": desc,
                        })
                        st.success(f"✅ 角色「{char_name}」建立完成")
                        st.caption(f"外觀描述：{desc[:60]}...")
                    except Exception as e:
                        st.error(f"❌ 角色建立失敗：{e}")

    if st.session_state.characters:
        c1, c2 = st.columns([3, 1])
        c1.markdown("**已建立角色：**")
        if c2.button("🗑️ 清除全部", type="secondary", use_container_width=True):
            clear_all_characters()
        for i, c in enumerate(st.session_state.characters):
            ca, cb, cc = st.columns([1, 3, 1])
            ca.markdown(f"**{chr(65+i)}. {c['name']}**")
            cb.caption(c.get("desc","")[:80] + "...")
            if cc.button("🗑️", key=f"del_{i}"):
                st.session_state.characters.pop(i); st.rerun()

    st.divider()
    st.subheader("🎬 Step 2：選擇出場角色")
    selected_chars = []
    if st.session_state.characters:
        cols = st.columns(min(len(st.session_state.characters), 4))
        for i, c in enumerate(st.session_state.characters):
            if cols[i % 4].checkbox(f"{chr(65+i)}. {c['name']}", value=True, key=f"sel_{i}"):
                selected_chars.append(c)
    else:
        st.info("請先在上方建立角色")

    st.divider()
    st.subheader("📝 Step 3：輸入劇情與設定")
    user_input = st.text_area("描述故事劇情",
        placeholder="例如：美女在公園遇見帥哥，兩人一起看夕陽，最後依依不捨地道別...",
        height=160, key="multi_input")
    st.markdown("**🎬 影片設定**")
    aspect_ratio, video_duration = _render_video_settings("multi", show_square=True)

    if st.button("🎬 生成分鏡腳本", use_container_width=True):
        if not user_input.strip():
            st.warning("⚠️ 請輸入劇情")
        elif not selected_chars:
            st.warning("⚠️ 請在 Step 2 勾選至少一個角色")
        else:
            with st.spinner("AI 正在拆解分鏡..."):
                try:
                    res = generate_storyboard(user_input, selected_chars, keys["openai"])
                    st.session_state.storyboard      = res.get("storyboard", [])
                    st.session_state.storyboard_meta = res
                    st.success(f"✅ 分鏡腳本生成完成，共 {len(st.session_state.storyboard)} 個分鏡")
                except Exception as e:
                    st.error(f"❌ 分鏡生成失敗：{e}")

    if st.session_state.storyboard:
        st.subheader("📋 分鏡腳本預覽（可編輯）")
        for i, s in enumerate(st.session_state.storyboard):
            with st.expander(f"分鏡 {i+1}｜角色：{', '.join(s.get('characters',[]))}", expanded=True):
                st.text_area("場景描述（英文）", value=s.get("scene",""),
                             key=f"edit_scene_{i}", height=80)
                st.text_input("旁白（中文）", value=s.get("narration",""), key=f"edit_narr_{i}")

    st.divider()
    if not st.button("🚀 開始生成所有分鏡影片", type="primary",
                     use_container_width=True, key="multi_gen"):
        return
    if not st.session_state.storyboard:
        st.warning("⚠️ 請先點「🎬 生成分鏡腳本」按鈕"); return
    if not selected_chars:
        st.warning("⚠️ 請在 Step 2 勾選出場角色"); return
    if not check_required_keys(keys, enable_voice, enable_music):
        return

    meta   = st.session_state.storyboard_meta
    boards = [dict(s) | {"scene": st.session_state.get(f"edit_scene_{i}", s.get("scene","")),
                          "narration": st.session_state.get(f"edit_narr_{i}", s.get("narration",""))}
              for i, s in enumerate(st.session_state.storyboard)]
    chars  = [dict(c) for c in selected_chars]

    st.markdown("---"); st.markdown("### ⚡ 並行生成所有分鏡")
    scene_status, scene_progress = _make_scene_ui(len(boards))
    collected  = run_parallel_video_generation(boards, chars, video_duration, aspect_ratio,
                                               keys, scene_status, scene_progress)
    video_urls = [collected[i][0] for i in range(len(boards))
                  if collected.get(i) and collected[i][0]]
    if not video_urls:
        st.error("❌ 所有分鏡都生成失敗，請檢查 Kling API 設定"); return

    st.markdown("---"); st.markdown("### 🎵 生成語音與音樂")
    narration_text = meta.get("narration","").strip()
    audio_bytes, music_bytes = run_parallel_audio_generation(
        narration_text, meta.get("music_mood","calm"), meta.get("music_genre","cinematic"),
        enable_voice, enable_music, keys)

    st.markdown("---"); st.markdown("### 🎉 生成結果")
    render_video_results(video_urls, audio_bytes, music_bytes, narration_text)
    st.session_state.history.append({
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"), "mode": "多角色分鏡",
        "narration": narration_text, "video_urls": video_urls,
    })
    if enable_gdrive:
        st.markdown("---"); st.markdown("### ☁️ 儲存至 Google Drive")
        with st.spinner("上傳中..."):
            run_gdrive_upload(video_urls, audio_bytes, music_bytes, keys, "multi")

# ==================== 模式 C ====================
def _render_mode_script(keys, enable_voice, enable_music, enable_gdrive):
    st.subheader("✍️ AI 劇本創作")
    st.caption("輸入一句話，AI 自動生成完整劇本、角色、分鏡，並直接生成影片")

    col_idea, col_set = st.columns([2, 1])
    with col_idea:
        idea = st.text_area("💡 一句話概念",
            placeholder="例如：一個外賣員愛上了客戶\n例如：太空人在火星發現了一朵花",
            height=120, key="script_idea")
    with col_set:
        st.markdown("**🎬 影片設定**")
        ending_type       = st.radio("結局類型", list(ENDING_MAP.keys()), key="script_ending")
        ending_type_clean = ENDING_MAP[ending_type]
        orientation       = st.radio("畫面方向", ["🖥️ 橫式 16:9","📱 直式 9:16"], key="script_orientation")
        aspect_ratio      = ASPECT_RATIO_MAP[orientation]
        video_duration    = st.selectbox("每個分鏡長度", [5, 10], key="script_duration")

    if st.button("🎬 生成劇本", use_container_width=True, key="script_gen"):
        if not idea.strip():
            st.warning("⚠️ 請輸入一句話概念")
        elif not keys.get("openai"):
            st.error("❌ 缺少 OpenAI API 金鑰")
        else:
            with st.spinner("AI 正在創作劇本..."):
                try:
                    script = generate_script_from_idea(idea.strip(), ending_type_clean, keys["openai"])
                    if "storyboard" not in script or "characters" not in script:
                        st.error("❌ AI 回傳格式不正確，請重試")
                    else:
                        st.session_state.script = script
                        st.success("✅ 劇本生成完成")
                except json.JSONDecodeError as e:
                    st.error(f"❌ JSON 解析失敗：{e}")
                except Exception as e:
                    st.error(f"❌ 劇本生成失敗：{e}")

    if not st.session_state.get("script"):
        return

    script     = st.session_state.script
    storyboard = script.get("storyboard", [])
    total      = len(storyboard)
    climax_idx = max(0, min(int(script.get("climax_point", 1)) - 1, total - 1)) if total else 0

    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"### 🎬 {script.get('title','未命名')}")
        st.info(f"📖 {script.get('logline','')}")
        st.caption(f"結局：{script.get('ending_description','')} ｜ 高潮：第 {script.get('climax_point','?')} 個分鏡")
    with c2:
        st.markdown("**🎭 角色**")
        for c in script.get("characters", []):
            with st.expander(f"{c.get('label','?')}. {c.get('name','?')}"):
                st.caption(f"性格：{c.get('personality','')}"); st.caption(f"動機：{c.get('motivation','')}")
                st.caption(f"外觀：{c.get('appearance','')[:80]}...")

    st.divider()
    st.subheader("📋 分鏡腳本")
    for i, s in enumerate(storyboard):
        is_climax = (i == climax_idx) or s.get("is_climax", False)
        label = (f"{'🔥 ' if is_climax else ''}分鏡 {i+1}｜"
                 f"{s.get('location','')}｜{s.get('camera','')}｜節奏：{s.get('pacing','')}")
        with st.expander(label, expanded=True):
            ca, cb = st.columns(2)
            with ca:
                st.text_area("場景描述（英文）", value=s.get("scene",""),
                             key=f"script_scene_{i}", height=80)
            with cb:
                st.text_input("旁白（中文）", value=s.get("narration",""), key=f"script_narr_{i}")
                st.text_input("對話（中文）", value=s.get("dialogue",""), key=f"script_dial_{i}")

    st.divider()
    if not st.button("🚀 開始生成所有分鏡影片", type="primary",
                     use_container_width=True, key="script_video_gen"):
        return
    if not check_required_keys(keys, enable_voice, enable_music):
        return

    boards = [dict(s) | {
        "scene":     st.session_state.get(f"script_scene_{i}", s.get("scene","")),
        "narration": st.session_state.get(f"script_narr_{i}",  s.get("narration","")),
        "dialogue":  st.session_state.get(f"script_dial_{i}",  s.get("dialogue","")),
    } for i, s in enumerate(storyboard)]

    chars_by_label = {
        c.get("label", chr(65+i)).upper(): {
            "name": c.get("name",""), "appearance": c.get("appearance",""),
            "desc": c.get("appearance",""), "images_b64": [],
        }
        for i, c in enumerate(script.get("characters", []))
    }

    st.markdown("---"); st.markdown("### ⚡ 並行生成所有分鏡")
    scene_status, scene_progress = _make_scene_ui(len(boards))
    collected  = run_parallel_video_generation(
        boards, chars_by_label, video_duration, aspect_ratio,
        keys, scene_status, scene_progress, use_label_dict=True)
    video_urls = [collected[i][0] for i in range(len(boards))
                  if collected.get(i) and collected[i][0]]
    if not video_urls:
        st.error("❌ 所有分鏡都生成失敗，請檢查 Kling API 設定"); return

    st.markdown("---"); st.markdown("### 🎵 生成語音與音樂")
    narration_text = script.get("narration","").strip()
    audio_bytes, music_bytes = run_parallel_audio_generation(
        narration_text, script.get("music_mood","calm"), script.get("music_genre","cinematic"),
        enable_voice, enable_music, keys)

    st.markdown("---"); st.markdown("### 🎉 生成結果")
    render_video_results(video_urls, audio_bytes, music_bytes, narration_text)
    st.session_state.history.append({
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": f"AI劇本（{ending_type_clean}）",
        "narration": narration_text, "video_urls": video_urls,
    })
    if enable_gdrive:
        st.markdown("---"); st.markdown("### ☁️ 儲存至 Google Drive")
        with st.spinner("上傳中..."):
            run_gdrive_upload(video_urls, audio_bytes, music_bytes,
                              keys, prefix=f"script_{script.get('title','')[:10]}")

# ==================== 主程式 ====================
def main():
    st.set_page_config(page_title="AI 影片生成器", page_icon="🎬", layout="wide")
    init_session()
    if not check_password():
        return

    st.title("🎬 AI 影片生成器")
    st.caption("整合 OpenAI · Kling AI · ElevenLabs · Beatoven.ai · Google Drive")

    keys = get_api_keys()
    render_api_settings(keys)
    render_history()
    st.divider()

    mode = st.radio("選擇生成模式",
                    ["🎥 單場景模式", "🎭 多角色分鏡模式", "✍️ AI 劇本創作"],
                    horizontal=True)
    st.divider()

    st.subheader("🎛️ 生成選項")
    c1, c2, c3 = st.columns(3)
    enable_voice  = c1.checkbox("🎙️ 生成語音旁白", value=True)
    enable_music  = c2.checkbox("🎵 生成背景音樂", value=True)
    enable_gdrive = c3.checkbox("☁️ 儲存至 Google Drive", value=True)
    st.divider()

    dispatch = {
        "🎥 單場景模式":    _render_mode_single,
        "🎭 多角色分鏡模式": _render_mode_multi,
        "✍️ AI 劇本創作":  _render_mode_script,
    }
    dispatch[mode](keys, enable_voice, enable_music, enable_gdrive)


if __name__ == "__main__":
    main()
