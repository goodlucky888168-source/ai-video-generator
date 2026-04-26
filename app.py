import streamlit as st
import requests
import json
import time
import hmac
import hashlib
import base64

# ==================== 密碼驗證 ====================
def check_password():
    if "authenticated" not in st.session_state:
