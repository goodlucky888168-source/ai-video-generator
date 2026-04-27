import streamlit as st

def get_api_keys():
    """獲取所有 API 金鑰"""
    return {
        "openai": st.secrets.get("OPENAI_API_KEY", ""),
        "kling_access": st.secrets.get("KLING_ACCESS_KEY", ""),
        "kling_secret": st.secrets.get("KLING_SECRET_KEY", ""),
        "elevenlabs": st.secrets.get("ELEVENLABS_API_KEY", ""),
        "elevenlabs_voice": st.secrets.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM"),
        "beatoven": st.secrets.get("BEATOVEN_API_KEY", ""),
        "gdrive": st.secrets.get("GDRIVE_CREDENTIALS", ""),
    }
