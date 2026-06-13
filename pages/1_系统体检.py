"""System health and required configuration."""

import pandas as pd
import streamlit as st

from utils.system_health import get_db_diagnostics, run_health_checks, send_test_email


st.set_page_config(page_title="系统体检 | EETOON CRM", page_icon="🩺", layout="wide")

if not st.session_state.get("authenticated"):
    st.warning("请先登录")
    st.stop()

st.markdown("## 系统体检")
st.caption("用于确认数据库、邮件发送、邮件读取、自动化配置是否具备真实运行条件。")

if st.button("重新检查", type="primary"):
    st.cache_data.clear()

rows = run_health_checks()
st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

with st.expander("数据库连接诊断（不显示密码）", expanded=True):
    st.json(get_db_diagnostics())

st.markdown("### SMTP 测试")
col_email, col_btn = st.columns([2, 1])
with col_email:
    test_to = st.text_input("测试收件邮箱", placeholder="yourname@gmail.com")
with col_btn:
    st.write("")
    st.write("")
    if st.button("发送测试邮件", use_container_width=True):
        ok, msg = send_test_email(test_to)
        if ok:
            st.success("测试邮件已发送。请检查收件箱和垃圾箱。")
        else:
            st.error(f"发送失败：{msg}")

st.markdown("### Streamlit Cloud Secrets 需要填写")
st.code(
    """
[auth]
password = "你的CRM登录密码"

[supabase]
db_host = "db.xxxxx.supabase.co"
db_port = 5432
db_name = "postgres"
db_user = "postgres"
db_password = "你的Supabase数据库密码"

[smtp]
host = "smtp.qiye.163.com"
port = 465
user = "你的企业邮箱账号"
password = "你的企业邮箱SMTP授权码或密码"
sender_name = "Sherry | EETOON GROUP"
bcc = "你的Gmail备份邮箱"

[imap]
host = "imap.qiye.163.com"
port = 993
user = "你的企业邮箱账号"
password = "你的企业邮箱IMAP授权码或密码"

[anthropic]
api_key = "你的Claude API Key（可后补）"
""".strip(),
    language="toml",
)

st.markdown("### GitHub Actions Secrets 需要填写")
st.write("位置：GitHub 仓库 -> Settings -> Secrets and variables -> Actions -> New repository secret")
st.code(
    """
SUPABASE_URL
SUPABASE_SERVICE_KEY
SMTP_HOST
SMTP_PORT
SMTP_USER
SMTP_PASS
SENDER_NAME
BCC_EMAIL
NOTIFY_EMAIL
IMAP_HOST
IMAP_PORT
IMAP_USER
IMAP_PASS
""".strip(),
    language="text",
)

st.info(
    "你不需要把密码发给我。只要按上面字段名填到对应平台，体检页会显示是否配置成功。"
)
