pp02"}
```python
import streamlit as st
import time
import uuid
import random
import requests
import concurrent.futures
from moviepy.editor import VideoFileClip, concatenate_videoclips

from config import get_api_keys
from api.openai_api import analyze_prompt, image_to_base64
from api.kling_api import generate_video

# ==================== 全域設定 ====================
MAX_WORKERS = 3

GLOBAL_STYLE = """
cinematic lighting,
soft warm color tone,
consistent color grading,
same lighting style,
high detail, realistic
"""

# ==================== Session ====================
if "tasks" not in st.session_state:
    st.session_state.tasks = {}

if "characters" not in st.session_state:
    st.session_state.characters = []

# ==================== 任務系統 ====================
def create_task():
    task_id = str(uuid.uuid4())
    st.session_state.tasks[task_id] = {
        "status": "pending",
        "progress": 0,
        "videos": []
    }
    return task_id

def update_task(task_id, progress=None, video=None, status=None):
    task = st.session_state.tasks[task_id]

    if progress is not None:
        task["progress"] = progress
    if video:
        task["videos"].append(video)
    if status:
        task["status"] = status

# ==================== 分鏡生成 ====================
def generate_storyboard(user_input, characters, openai_key):
    char_desc = ""
    for i, c in enumerate(characters):
        label = chr(65 + i)
        char_desc += f"Character {label}: {c['desc']}\n"

    prompt = f"""
    拆成3個分鏡，輸出JSON:
    {user_input}
    {char_desc}
    """

    result = analyze_prompt(prompt, openai_key)
    return result.get("storyboard", [])

# ==================== Prompt 建構 ====================
def build_scene_prompt(scene, characters):
    desc = ""

    for label in scene["characters"]:
        idx = ord(label) - 65
        c = characters[idx]
        desc += f"{c['name']}: {c['desc']}\n"

    return f"""
    {GLOBAL_STYLE}

    {desc}

    Scene:
    {scene['scene']}

    keep same character,
    no face change,
    no face mixing
    """

# ==================== 合併影片 ====================
def merge_videos(video_urls):
    clips = []

    for url in video_urls:
        r = requests.get(url)
        path = f"/tmp/{uuid.uuid4()}.mp4"
        with open(path, "wb") as f:
            f.write(r.content)

        clips.append(VideoFileClip(path))

    final = concatenate_videoclips(clips)
    output = f"/tmp/final_{uuid.uuid4()}.mp4"
    final.write_videofile(output, codec="libx264")

    return output

# ==================== 並行生成 ====================
def generate_all_scenes(task_id, storyboard, characters, keys):

    def worker(scene, idx, total):
        try:
            prompt = build_scene_prompt(scene, characters)
            ref = random.choice(characters)["images"][0]
            base64_img = image_to_base64(ref)

            video_url = generate_video(
                prompt,
                keys["kling_access"],
                keys["kling_secret"],
                base64_img,
                None,
                scene.get("duration", 5),
                "16:9"
            )

            update_task(task_id, progress=(idx+1)/total, video=video_url)

        except Exception as e:
            update_task(task_id, status=f"error: {e}")

    total = len(storyboard)

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = []
        for i, scene in enumerate(storyboard):
            futures.append(executor.submit(worker, scene, i, total))

        concurrent.futures.wait(futures)

    update_task(task_id, status="done")

# ==================== 主程式 ====================
def main():
    st.set_page_config(page_title="AI 導演系統", layout="wide")
    st.title("🎬 AI 多角色分鏡生成器（升級版）")

    keys = get_api_keys()

    # ==================== 角色建立 ====================
    st.subheader("🎭 角色")

    name = st.text_input("角色名稱")
    uploads = st.file_uploader("上傳角色圖", accept_multiple_files=True)

    if st.button("建立角色"):
        if uploads:
            desc = analyze_prompt("描述人物外觀", keys["openai"])
            st.session_state.characters.append({
                "name": name,
                "images": uploads,
                "desc": desc
            })
            st.success("角色建立完成")

    # ==================== 選角色 ====================
    selected_chars = []
    for i, c in enumerate(st.session_state.characters):
        if st.checkbox(c["name"], key=i):
            selected_chars.append(c)

    # ==================== 輸入 ====================
    user_input = st.text_area("輸入劇情")

    # ==================== 分鏡 ====================
    if st.button("生成分鏡"):
        storyboard = generate_storyboard(user_input, selected_chars, keys["openai"])
        st.session_state.storyboard = storyboard

    if "storyboard" in st.session_state:
        st.subheader("🎬 分鏡")
        for i, s in enumerate(st.session_state.storyboard):
            st.write(f"{i+1}. {s['scene']}")

    # ==================== 開始生成 ====================
    if st.button("🚀 生成影片（並行）"):
        task_id = create_task()

        with st.spinner("任務執行中..."):
            generate_all_scenes(
                task_id,
                st.session_state.storyboard,
                selected_chars,
                keys
            )

        task = st.session_state.tasks[task_id]

        st.success("✅ 生成完成")

        progress = st.progress(task["progress"])

        final_video = merge_videos(task["videos"])

        st.video(final_video)

# ====================
if name == "main":
    main
