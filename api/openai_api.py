import openai
import json
import streamlit as st

def analyze_prompt(prompt: str, api_key: str) -> dict:
    """
    使用 OpenAI 分析和優化提示詞
    
    Args:
        prompt: 用戶輸入的提示詞
        api_key: OpenAI API 金鑰
    
    Returns:
        包含分析結果的字典
    """
    
    # ✅ 驗證 API 金鑰
    if not api_key or not api_key.strip():
        raise ValueError("❌ OpenAI API 金鑰未設定")
    
    api_key = api_key.strip()
    
    # ✅ 檢查金鑰格式
    if not api_key.startswith("sk-"):
        raise ValueError("❌ OpenAI API 金鑰格式錯誤，應該以 'sk-' 開頭")
    
    if not prompt or not prompt.strip():
        raise ValueError("❌ 提示詞不能為空")
    
    try:
        # ✅ 設定 OpenAI 客戶端
        client = openai.OpenAI(api_key=api_key)
        
        # ✅ 調用 GPT-4 或 GPT-3.5
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",  # 或使用 "gpt-4"
            messages=[
                {
                    "role": "system",
                    "content": "你是一個專業的影片製作提示詞優化助手。請優化用戶的提示詞，使其更適合 AI 影片生成。"
                },
                {
                    "role": "user",
                    "content": f"請優化以下提示詞用於 AI 影片生成：\n{prompt}\n\n請返回 JSON 格式的結果，包含 'video_prompt' 字段。"
                }
            ],
            temperature=0.7,
            max_tokens=500
        )
        
        # ✅ 解析回應
        content = response.choices[0].message.content
        
        # 嘗試解析 JSON
        try:
            result = json.loads(content)
        except json.JSONDecodeError:
            # 如果不是有效的 JSON，使用原始內容
            result = {"video_prompt": content}
        
        return result
    
    except openai.AuthenticationError as e:
        raise Exception(f"❌ OpenAI 認證失敗：API 金鑰無效或已過期\n詳情：{str(e)}")
    
    except openai.RateLimitError as e:
        raise Exception(f"❌ OpenAI 請求過於頻繁，請稍後再試\n詳情：{str(e)}")
    
    except openai.APIError as e:
        raise Exception(f"❌ OpenAI API 錯誤：{str(e)}")
    
    except Exception as e:
        raise Exception(f"❌ 分析失敗：{str(e)}")

def image_to_base64(uploaded_file) -> str:
    """將上傳的圖片轉換為 Base64"""
    if not uploaded_file:
        return None
    
    try:
        import base64
        image_data = uploaded_file.read()
        return base64.b64encode(image_data).decode('utf-8')
    except Exception as e:
        st.error(f"❌ 圖片轉換失敗：{str(e)}")
        return None
