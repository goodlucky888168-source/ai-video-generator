import streamlit as st

def get_api_keys():
    """根據 API_MODE 取得對應的 API 金鑰"""
    mode = st.secrets.get("API_MODE", "main")
    is_backup = (mode == "backup")

    def get_key(main_key, backup_key=None):
        if is_backup and backup_key:
            return st.secrets.get(backup_key, st.secrets.get(main_key, ""))
        return st.secrets.get(main_key, "")

    return {
        "mode": mode,
        "openai":           get_key("OPENAI_API_KEY",        "OPENAI_API_KEY_BACKUP"),
        "kling_access":     get_key("KLING_ACCESS_KEY",      "KLING_ACCESS_KEY_BACKUP"),
        "kling_secret":     get_key("KLING_SECRET_KEY",      "KLING_SECRET_KEY_BACKUP"),
        "elevenlabs":       get_key("ELEVENLABS_API_KEY",    "ELEVENLABS_API_KEY_BACKUP"),
        "elevenlabs_voice": get_key("ELEVENLABS_VOICE_ID"),
        "beatoven":         get_key("BEATOVEN_API_KEY",      "BEATOVEN_API_KEY_BACKUP"),
        "gdrive_folder":    get_key("GDRIVE_FOLDER_ID"),
        "gdrive_sa_json":   get_key("GDRIVE_SERVICE_ACCOUNT_JSON"),
    }

