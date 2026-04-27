import json
import re
import time
import concurrent.futures
import requests
import streamlit as st
from datetime import datetime
from config import get_api_keys
from api.openai_api import analyze_prompt, image_to_base64
from api.kling_api import generate_video
from api.elevenlabs_api import generate_voice
from api.beatoven_api import generate_music
from api.gdrive_api import upload_to_drive, upload_video_from_url

# ==================== 全域常數 ====================
MAX_WORKERS = 3

GLOBAL_STYLE = (
    "cinematic lighting, ultra-high detail, professional color grading, "
    "8k resolution, photorealistic, consistent environment"
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
    """初始化所有 Session State 變數"""
    defaults = {
        "tasks":              {},
        "characters":         [],
        "storyboard":         [],
        "storyboard_meta":    {},
        "script":             {},
        "authenticated":      False,
        "login_attempts":     0,
        "lockout_until":      0.0,
        "generated_videos":   [],
        "generated_audio":    None,
        "generated_music":    None,
        "history":            [],
        "confirm_clear_history": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

def add_to_history(record_type: str, title: str, data: dict, error_msg: str = None):
    """新增記錄到歷史"""
    record = {
        "id": len(st.session_state.history) + 1,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "type": record_type,
        "title": title,
        "videos": data.get("videos", []),
        "audio": data.get("audio"),
        "music": data.get("music"),
        "error": error_msg,
        "status": "❌ 失敗" if error_msg else "✅ 成功",
    }
    st.session_state.history.append(record)

def clear_all_characters():
    """清空所有角色和分鏡"""
    st.session_state.characters = []
    st.session_state.storyboard = []
    st.session_state.storyboard_meta = {}
    st.session_state.script = {}
    st.session_state.generated_videos = []
    st.session_state.generated_audio = None
    st.session_state.generated_music = None
    st.success("✅ 已清空所有內容")

def check_password() -> bool:
    """檢查登入狀態"""
    if st.session_state.get("authenticated"):
        return True
    
    st.markdown("## 🔐 請登入系統")
    col1, _ = st.columns([1, 2])
    with col1:
        username = st.text_input("帳號", key="login_username")
        password = st.text_input("密碼", type="password", key="login_password")
        now = time.time()
        
        if now < st.session_state.lockout_until:
            remaining = int(st.session_state.lockout_until - now)
            st.error(f"⛔ 嘗試次數過多，請等待 {remaining} 秒")
            return False
        
        if st.button("登入", type="primary"):
            if (username == st.secrets.get("APP_USERNAME") and
                    password == st.secrets.get("APP_PASSWORD")):
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.session_state.login_attempts += 1
                if st.session_state.login_attempts >= 5:
                    st.session_state.lockout_until = time.time() + 60
                st.error("帳號或密碼錯誤")
    return False

# ==================== Prompt 優化 ====================
def build_optimized_prompt(scene: dict, chars_data, use_label_dict=False) -> str:
    """將場景描述置於最前"""
    scene_text = scene.get("scene", "")
    char_labels = scene.get("characters", [])
    camera = scene.get("camera", "medium")
    pacing = scene.get("pacing", "normal")
    
    char_descs = []
    for label in char_labels:
        if not use_label_dict:
            idx = ord(label.upper()) - 65
            if 0 <= idx < len(chars_data):
                c = chars_data[idx]
                char_descs.append(f"{c['name']}: {c.get('appearance') or c.get('desc', '')}")
        else:
            c = chars_data.get(label.upper())
            if c:
                char_descs.append(f"{c['name']}: {c.get('appearance', '')}")

    all_chars_str = " and ".join(char_descs) if char_descs else ""
    climax_str = "dramatic peak, intense lighting, " if scene.get("is_climax") else ""
    
    prompt = (
        f"{GLOBAL_STYLE}, {climax_str}{camera} shot, {pacing} pacing. "
        f"SCENE: {scene_text}. "
    )
    if all_chars_str:
        prompt += f"CHARACTERS: {all_chars_str}. "
    prompt += "Maintain background consistency, high quality human features, natural interaction."
    
    return prompt.strip()

# ==================== 並行生成 ====================
def run_parallel_video_generation(
    boards: list, characters, video_duration: int, aspect_ratio: str,
    keys: dict, scene_status: list, scene_progress: list,
    use_label_dict: bool = False
) -> dict:
    """並行生成多個分鏡影片"""
    
    def generate_one(scene, idx):
        try:
            prompt = build_optimized_prompt(scene, characters, use_label_dict)
            ref_img = None
            labels = scene.get("characters", [])
            
            if len(labels) == 1 and not use_label_dict:
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

    collected = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        future_map = {ex.submit(generate_one, s, i): i for i, s in enumerate(boards)}
        for f in concurrent.futures.as_completed(future_map):
            idx, url, err = f.result()
            collected[idx] = (url, err)
            if err:
                scene_status[idx].error(f"❌ 分鏡 {idx+1} 失敗")
            else:
                scene_status[idx].success(f"✅ 分鏡 {idx+1} 完成")
            scene_progress[idx].progress(1.0)
    return collected

def run_parallel_audio_generation(narration, mood, genre, ev, em, keys):
    """並行生成語音和配樂"""
    audio_bytes = music_bytes = None
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        vf = None
        mf = None
        
        if ev and narration:
            try:
                if not keys.get("elevenlabs"):
                    st.warning("⚠️ ElevenLabs API 金鑰未設定，跳過語音生成")
                else:
                    vf = ex.submit(
                        safe_generate_voice, 
                        narration, 
                        keys["elevenlabs"], 
                        keys.get("elevenlabs_voice", "21m00Tcm4TlvDq8ikWAM")
                    )
            except Exception as e:
                st.error(f"❌ 語音生成錯誤：{str(e)}")
        
        if em and mood and genre:
            try:
                if not keys.get("beatoven"):
                    st.warning("⚠️ Beatoven API 金鑰未設定，跳過配樂生成")
                else:
                    mf = ex.submit(
                        safe_generate_music, 
                        mood, 
                        genre, 
                        keys["beatoven"], 
                        30, 
                        lambda *_: None
                    )
            except Exception as e:
                st.error(f"❌ 配樂生成錯誤：{str(e)}")
        
        if vf:
            try:
                audio_bytes = vf.result()
            except Exception as e:
                st.error(f"❌ 語音生成失敗：{str(e)}")
        
        if mf:
            try:
                music_bytes = mf.result()
            except Exception as e:
                st.error(f"❌ 配樂生成失敗：{str(e)}")
    
    return audio_bytes, music_bytes

# ==================== 輔助函數 ====================
def render_video_results(video_urls, audio, music, narration):
    """顯示生成結果"""
    st.markdown("### 🎬 生成結果")
    
    if video_urls:
        st.markdown("#### 📹 影片")
        cols = st.columns(min(len(video_urls), 4))
        for i, url in enumerate(video_urls):
            with cols[i % len(cols)]:
                st.video(url)
    
    if audio:
        st.markdown("#### 🎙️ 語音旁白")
        st.audio(audio, format="audio/mp3")
    
    if music:
        st.markdown("#### 🎵 背景音樂")
        st.audio(music, format="audio/mp3")

def download_video_from_url(url: str) -> bytes:
    """從 URL 下載影片"""
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return response.content
    except Exception as e:
        st.error(f"❌ 下載失敗: {str(e)}")
        return None

def _render_video_settings(prefix):
    """渲染影片設定選項"""
    c1, c2 = st.columns(2)
    with c1:
        ori = st.radio("方向", ["🖥️ 橫式 16:9", "📱 直式 9:16"], key=f"{prefix}_or")
    with c2:
        dur = st.number_input("秒數", min_value=3, max_value=60, value=5, key=f"{prefix}_dur")
    return ASPECT_RATIO_MAP[ori], dur

def _make_scene_ui(total):
    """建立分鏡進度 UI"""
    cols = st.columns(min(total, 4))
    status = [cols[i % 4].empty() for i in range(total)]
    prog = [cols[i % 4].progress(0) for i in range(total)]
    return status, prog

# ==================== 模式 A：單場景 ====================
def _render_mode_single(keys, ev, em, eg):
    """單場景生成模式"""
    st.subheader("🎥 單場景生成")
    
    col1, col2 = st.columns([2, 1])
    with col1:
        user_input = st.text_area("描述影片內容", placeholder="例如：在海邊散步...", height=150)
        aspect_ratio, duration = _render_video_settings("single")
    
    with col2:
        uploaded = st.file_uploader("角色圖片 (選填)", type=["jpg", "png"])
        if uploaded:
            st.image(uploaded)

    if st.button("🚀 開始生成", type="primary", use_container_width=True):
        if not user_input:
            st.warning("請輸入內容")
            return
        
        try:
            with st.spinner("分析提示詞中..."):
                res = analyze_prompt(user_input, keys["openai"])
                prompt = res.get("video_prompt", user_input)
            
            with st.spinner("生成影片中..."):
                img_b64 = image_to_base64(uploaded) if uploaded else None
                url = safe_generate_video(
                    prompt, keys["kling_access"], keys["kling_secret"],
                    img_b64, lambda *_: None, duration, aspect_ratio
                )
            
            st.session_state.generated_videos = [url]
            st.session_state.generated_audio = None
            st.session_state.generated_music = None
            
            add_to_history("single", user_input[:50], {
                "videos": [url],
                "audio": None,
                "music": None
            })
            
            st.success("✅ 影片生成完成！")
        
        except Exception as e:
            error_msg = str(e)
            st.error(f"❌ 生成失敗: {error_msg}")
            add_to_history("single", user_input[:50], {
                "videos": [], "audio": None, "music": None
            }, error_msg)

# ==================== 模式 B：多角色分鏡 ====================
def _render_mode_multi(keys, ev, em, eg):
    """多角色分鏡模式"""
    st.subheader("🎭 多角色分鏡")
    
    with st.expander("👥 角色設定", expanded=len(st.session_state.characters) == 0):
        col1, col2 = st.columns([3, 1])
        with col1:
            char_name = st.text_input("角色名稱", key="char_name_input")
            char_desc = st.text_area("角色描述", key="char_desc_input", height=80)
        with col2:
            char_img = st.file_uploader("角色圖片", type=["jpg", "png"], key="char_img_input")
        
        if st.button("➕ 新增角色"):
            if char_name and char_desc:
                img_b64 = image_to_base64(char_img) if char_img else None
                new_char = {
                    "name": char_name,
                    "desc": char_desc,
                    "appearance": char_desc,
                    "images_b64": [img_b64] if img_b64 else []
                }
                st.session_state.characters.append(new_char)
                st.success(f"✅ 已新增角色: {char_name}")
                st.rerun()
            else:
                st.warning("請填寫角色名稱和描述")
    
    if st.session_state.characters:
        st.info(f"已新增 {len(st.session_state.characters)} 個角色")
        for i, char in enumerate(st.session_state.characters):
            col1, col2 = st.columns([3, 1])
            with col1:
                st.write(f"**{chr(65+i)}. {char['name']}**: {char['desc'][:50]}...")
            with col2:
                if st.button("🗑️", key=f"del_char_{i}"):
                    st.session_state.characters.pop(i)
                    st.rerun()
    
    user_input = st.text_area("故事劇情", placeholder="兩人一起在海邊看夕陽...", height=100)
    aspect_ratio, duration = _render_video_settings("multi")

    if st.button("🎬 生成分鏡腳本", use_container_width=True):
        if not st.session_state.characters:
            st.warning("請先新增至少一個角色")
            return
        
        if not user_input:
            st.warning("請輸入故事劇情")
            return
        
        try:
            with st.spinner("AI 生成分鏡中..."):
                prompt = f"根據故事 '{user_input}' 和角色 {[c['name'] for c in st.session_state.characters]}，生成3個分鏡 JSON 格式"
                res = analyze_prompt(prompt, keys["openai"])
                st.session_state.storyboard = res.get("storyboard", [])
                st.session_state.storyboard_meta = res
                st.success("✅ 分鏡腳本生成完成")
        except Exception as e:
            st.error(f"❌ 生成失敗: {str(e)}")

    if st.session_state.storyboard:
        st.info("💡 多人分鏡將自動切換為文字模式")
        
        for i, board in enumerate(st.session_state.storyboard):
            with st.expander(f"分鏡 {i+1}: {board.get('scene', '')[:50]}..."):
                col1, col2 = st.columns(2)
                with col1:
                    st.session_state.storyboard[i]["scene"] = st.text_area(
                        "場景描述", value=board.get("scene", ""), key=f"scene_{i}"
                    )
                with col2:
                    st.session_state.storyboard[i]["camera"] = st.selectbox(
                        "鏡頭", ["wide", "medium", "close-up"],
                        index=["wide", "medium", "close-up"].index(board.get("camera", "medium")),
                        key=f"camera_{i}"
                    )
        
        if st.button("🚀 生成所有分鏡影片", type="primary", use_container_width=True):
            try:
                scene_status, scene_progress = _make_scene_ui(len(st.session_state.storyboard))
                collected = run_parallel_video_generation(
                    st.session_state.storyboard, st.session_state.characters,
                    duration, aspect_ratio, keys, scene_status, scene_progress
                )
                
                st.session_state.generated_videos = [
                    collected[i][0] for i in range(len(collected)) if collected[i][0]
                ]
                st.session_state.generated_audio = None
                st.session_state.generated_music = None
                
                add_to_history("multi", f"多角色分鏡 ({len(st.session_state.characters)} 人)", {
                    "videos": st.session_state.generated_videos,
                    "audio": None,
                    "music": None
                })
                
                st.success("✅ 所有分鏡生成完成")
            except Exception as e:
                error_msg = str(e)
                st.error(f"❌ 生成失敗: {error_msg}")
                add_to_history("multi", f"多角色分鏡", {
                    "videos": [], "audio": None, "music": None
                }, error_msg)

# ==================== 模式 C：AI 劇本創作 ====================
def _render_mode_script(keys, ev, em, eg):
    """AI 劇本全自動創作模式"""
    st.subheader("✍️ AI 劇本全自動創作")
    
    col_idea, col_set = st.columns([2, 1])
    with col_idea:
        idea = st.text_area("💡 故事點子", placeholder="例如：外星人在地球的海邊第一次看到冰淇淋", height=120)
    
    with col_set:
        ending = st.radio("結局類型", list(ENDING_MAP.keys()))
        orientation = st.radio("畫面方向", ["🖥️ 橫式 16:9", "📱 直式 9:16"])
        video_duration = st.number_input("每個分鏡秒數", min_value=3, max_value=60, value=5)

    if st.button("🎬 製作完整影片", type="primary", use_container_width=True):
        if not idea:
            st.warning("請輸入點子")
            return
        
        try:
            with st.spinner("AI 編劇中..."):
                prompt_script = f"將概念 '{idea}' 擴展成4個分鏡 JSON，結局為 {ENDING_MAP[ending]}。"
                script = analyze_prompt(prompt_script, keys["openai"])
                st.session_state.script = script
            
            if script:
                st.success(f"✅ 劇本：{script.get('title', '未命名')}")
                boards = script.get("storyboard", [])
                chars_dict = {c['label'].upper(): c for c in script.get("characters", [])}
                
                scene_status, scene_progress = _make_scene_ui(len(boards))
                
                with st.spinner("生成分鏡影片中..."):
                    collected = run_parallel_video_generation(
                        boards, chars_dict, video_duration, ASPECT_RATIO_MAP[orientation],
                        keys, scene_status, scene_progress, use_label_dict=True
                    )
                
                st.session_state.generated_videos = [
                    collected[i][0] for i in range(len(collected)) if collected[i][0]
                ]
                
                with st.spinner("生成語音和配樂中..."):
                    audio, music = run_parallel_audio_generation(
                        script.get("narration", ""), script.get("music_mood", "calm"),
                        script.get("music_genre", "cinematic"), ev, em, keys
                    )
                
                st.session_state.generated_audio = audio
                st.session_state.generated_music = music
                
                add_to_history("script", script.get('title', '未命名劇本'), {
                    "videos": st.session_state.generated_videos,
                    "audio": audio,
                    "music": music
                })
                
                st.success("✅ 完整影片製作完成！")
        
        except Exception as e:
            error_msg = str(e)
            st.error(f"❌ 製作失敗: {error_msg}")
            add_to_history("script", idea[:50], {
                "videos": [], "audio": None, "music": None
            }, error_msg)

# ==================== 結果顯示 ====================
def _render_results_section():
    """顯示當前生成的結果和下載選項"""
    if not st.session_state.generated_videos:
        return
    
    st.markdown("---")
    st.markdown("### 📥 下載成品")
    
    render_video_results(
        st.session_state.generated_videos,
        st.session_state.generated_audio,
        st.session_state.generated_music,
        st.session_state.script.get("narration", "") if st.session_state.script else ""
    )
    
    st.markdown("#### 📥 下載選項")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown("**影片**")
        for i, url in enumerate(st.session_state.generated_videos):
            video_data = download_video_from_url(url)
            if video_data:
                st.download_button(
                    label=f"分鏡 {i+1}",
                    data=video_data,
                    file_name=f"scene_{i+1}.mp4",
                    mime="video/mp4",
                    key=f"dl_video_{i}"
                )
    
    with col2:
        if st.session_state.generated_audio:
            st.markdown("**語音旁白**")
            st.download_button(
                label="下載語音",
                data=st.session_state.generated_audio,
                file_name="narration.mp3",
                mime="audio/mp3",
                key="dl_audio"
            )
    
    with col3:
        if st.session_state.generated_music:
            st.markdown("**背景音樂**")
            st.download_button(
                label="下載音樂",
                data=st.session_state.generated_music,
                file_name="music.mp3",
                mime="audio/mp3",
                key="dl_music"
            )

# ==================== 歷史記錄 ====================
def _render_history_page():
    """顯示歷史記錄"""
    st.subheader("📜 歷史記錄")
    
    if not st.session_state.history:
        st.info("暫無歷史記錄")
        return
    
    col1, col2, col3 = st.columns([2, 1, 1])
    with col3:
        if st.button("🗑️ 清除所有歷史", type="secondary"):
            if st.session_state.get("confirm_clear_history"):
                st.session_state.history = []
                st.session_state.confirm_clear_history = False
                st.success("✅ 已清除所有歷史記錄")
                st.rerun()
            else:
                st.session_state.confirm_clear_history = True
                st.warning("⚠️ 確定要清除所有歷史記錄嗎？再點一次確認。")
    
    for record in reversed(st.session_state.history):
        with st.expander(
            f"{record['status']} | {record['type'].upper()} | {record['title']} | {record['timestamp']}"
        ):
            col1, col2 = st.columns([3, 1])
            
            with col1:
                st.markdown(f"**記錄 ID**: {record['id']}")
                st.markdown(f"**類型**: {record['type']}")
                st.markdown(f"**時間**: {record['timestamp']}")
                st.markdown(f"**狀態**: {record['status']}")
                
                if record['error']:
                    st.error(f"**錯誤訊息**: {record['error']}")
                
                if record['videos']:
                    st.markdown("**影片連結**:")
                    for i, url in enumerate(record['videos']):
                        st.markdown(f"- [分鏡 {i+1}]({url})")
                        video_data = download_video_from_url(url)
                        if video_data:
                            st.download_button(
                                label=f"📥 下載分鏡 {i+1}",
                                data=video_data,
                                file_name=f"history_{record['id']}_scene_{i+1}.mp4",
                                mime="video/mp4",
                                key=f"history_video_{record['id']}_{i}"
                            )
                
                if record['audio']:
                    st.markdown("**語音旁白**: ✅ 已生成")
                    st.download_button(
                        label="📥 下載語音",
                        data=record['audio'],
                        file_name=f"history_{record['id']}_narration.mp3",
                        mime="audio/mp3",
                        key=f"history_audio_{record['id']}"
                    )
                
                if record['music']:
                    st.markdown("**背景音樂**: ✅ 已生成")
                    st.download_button(
                        label="📥 下載音樂",
                        data=record['music'],
                        file_name=f"history_{record['id']}_music.mp3",
                        mime="audio/mp3",
                        key=f"history_music_{record['id']}"
                    )
            
            with col2:
                if st.button("🗑️ 刪除", key=f"del_history_{record['id']}", type="secondary"):
                    st.session_state.history = [
                        h for h in st.session_state.history if h['id'] != record['id']
                    ]
                    st.success("✅ 已刪除記錄")
                    st.rerun()

# ==================== 主程式 ====================
def main():
    """主程式"""
    st.set_page_config(
        page_title="AI 專業影片製作器",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    init_session()
    
    if not check_password():
        return
    
    with st.sidebar:
        st.markdown("# ⚙️ 設定")
        st.divider()
        
        mode = st.radio(
            "選擇模式",
            ["🎥 單場景", "🎭 多角色分鏡", "✍️ AI 劇本創作", "📜 歷史記錄"]
        )
        
        st.divider()
        
        st.markdown("### 🎛️ 功能選項")
        ev = st.checkbox("🎙️ 語音旁白", value=True)
        em = st.checkbox("🎵 配樂", value=True)
        eg = st.checkbox("☁️ 雲端上傳", value=False)
        
        st.divider()
        
        st.markdown("### 🛠️ 工具")
        if st.button("🗑️ 清空所有內容", type="secondary", use_container_width=True):
            clear_all_characters()
        
        if st.button("🚪 登出", type="secondary", use_container_width=True):
            st.session_state.authenticated = False
            st.rerun()
    
    st.markdown("# 🎬 AI 專業影片製作器")
    
    keys = get_api_keys()
    
    if mode == "🎥 單場景":
        _render_mode_single(keys, ev, em, eg)
    elif mode == "🎭 多角色分鏡":
        _render_mode_multi(keys, ev, em, eg)
    elif mode == "✍️ AI 劇本創作":
        _render_mode_script(keys, ev, em, eg)
    elif mode == "📜 歷史記錄":
        _render_history_page()
        return
    
    _render_results_section()

if __name__ == "__main__":
    main()
