def _render_kling_key_validator():
    """Kling API 金鑰驗證工具"""
    with st.expander("🔐 Kling API 金鑰驗證", expanded=False):
        st.markdown("### 驗證 Kling API 金鑰")
        
        keys = get_api_keys()
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("**Access Key**")
            access_key = st.text_input(
                "輸入或貼上 Access Key",
                value=keys.get("kling_access", ""),
                type="password",
                key="kling_access_input"
            )
        
        with col2:
            st.markdown("**Secret Key**")
            secret_key = st.text_input(
                "輸入或貼上 Secret Key",
                value=keys.get("kling_secret", ""),
                type="password",
                key="kling_secret_input"
            )
        
        st.markdown("---")
        
        if st.button("✅ 驗證金鑰格式", key="validate_kling_keys"):
            st.markdown("### 🔍 驗證結果")
            
            # 檢查 Access Key
            if not access_key:
                st.error("❌ Access Key 為空")
            elif len(access_key) < 10:
                st.error(f"❌ Access Key 過短（{len(access_key)} 字符，應該 > 20）")
            elif " " in access_key or "\n" in access_key:
                st.error("❌ Access Key 包含空格或換行符")
            else:
                st.success(f"✅ Access Key 格式正確（{len(access_key)} 字符）")
                st.write(f"- 前 20 字符: {access_key[:20]}...")
            
            st.divider()
            
            # 檢查 Secret Key
            if not secret_key:
                st.error("❌ Secret Key 為空")
            elif len(secret_key) < 10:
                st.error(f"❌ Secret Key 過短（{len(secret_key)} 字符，應該 > 20）")
            elif " " in secret_key or "\n" in secret_key:
                st.error("❌ Secret Key 包含空格或換行符")
            else:
                st.success(f"✅ Secret Key 格式正確（{len(secret_key)} 字符）")
                st.write(f"- 前 20 字符: {secret_key[:20]}...")
            
            st.divider()
            
            # 建議
            st.markdown("### 💡 建議")
            st.info(
                "✅ 如果上述檢查都通過，但仍然收到 401 錯誤，請：\n\n"
                "1. 進入 [Kling AI 儀表板](https://klingai.com)\n"
                "2. 檢查帳戶是否有效\n"
                "3. 重新生成 API 金鑰\n"
                "4. 複製新金鑰到 Streamlit Secrets\n"
                "5. 等待 1-2 分鐘後重試"
            )

# 在 _render_api_check_panel 中添加
def _render_api_check_panel():
    """API 金鑰檢查面板"""
    with st.expander("🔧 API 金鑰檢查", expanded=False):
        st.markdown("### 🔐 API 金鑰狀態")
        
        keys = get_api_keys()
        
        # ... 其他檢查代碼 ...
        
        st.divider()
        
        # 添加 Kling 金鑰驗證
        _render_kling_key_validator()
