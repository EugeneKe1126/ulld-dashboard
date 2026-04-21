"""密碼驗證：觀看密碼（全站）+ 上傳密碼（匯入頁）"""
import streamlit as st


def require_view_password():
    """全站觀看密碼鎖。放在每個 page 最上面即可。"""
    if st.session_state.get("view_auth"):
        return

    st.markdown("## 🔐 請輸入觀看密碼")
    st.caption("ULLD 資料庫儀表板（內部使用）")

    pwd = st.text_input(
        "觀看密碼", type="password", key="view_pwd_input",
        label_visibility="collapsed",
    )
    if st.button("登入", type="primary") or pwd:
        expected = st.secrets.get("VIEW_PASSWORD", "")
        if pwd and pwd == expected:
            st.session_state["view_auth"] = True
            st.rerun()
        elif pwd:
            st.error("密碼錯誤")
    st.stop()


def check_upload_password(key: str = "upload_auth") -> bool:
    """上傳頁專用密碼。通過才回傳 True。"""
    if st.session_state.get(key):
        return True

    st.warning("上傳功能需要額外密碼")
    pwd = st.text_input("請輸入上傳密碼", type="password", key=f"{key}_input")
    if st.button("登入", key=f"{key}_btn"):
        expected = st.secrets.get("UPLOAD_PASSWORD", "")
        if pwd == expected and expected:
            st.session_state[key] = True
            st.rerun()
        else:
            st.error("密碼錯誤")
    return False


# 保留舊名稱給 page 3 用
def check_password(key: str = "upload_auth") -> bool:
    return check_upload_password(key)
