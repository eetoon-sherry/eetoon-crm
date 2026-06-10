"""Email queue monitor — real-time status of pending/sent/failed emails."""

import streamlit as st
from datetime import datetime, timezone
from utils.database import get_all_queue, get_setting
from utils.email_sender import process_due_emails

st.set_page_config(page_title="邮件队列 | EETOON CRM", page_icon="📬", layout="wide")

if not st.session_state.get("authenticated"):
    st.warning("请先登录"); st.stop()

st.markdown("## 📬 邮件队列监控")

# Manual trigger
col_btn1, col_btn2, col_refresh = st.columns([1, 1, 3])
with col_btn1:
    if st.button("▶️ 立即处理队列", type="primary", use_container_width=True):
        with st.spinner("处理中..."):
            sent, failed = process_due_emails()
        if sent:
            st.success(f"✅ 已发送 {sent} 封")
        elif failed:
            st.error(f"❌ {failed} 封失败")
        else:
            st.info("暂无到期邮件")
        st.rerun()
with col_btn2:
    if st.button("🔄 刷新", use_container_width=True):
        st.rerun()

st.markdown("---")

queue = get_all_queue()
pending = [q for q in queue if q.get('status') == 'pending']
sent = [q for q in queue if q.get('status') == 'sent']
failed = [q for q in queue if q.get('status') == 'failed']

# ── STATS ROW ─────────────────────────────────────────────────────────────────
c1, c2, c3 = st.columns(3)
with c1:
    st.metric("⏳ 待发送", len(pending))
with c2:
    st.metric("✅ 已发送", len(sent))
with c3:
    st.metric("❌ 失败", len(failed))

# ── PENDING EMAILS ────────────────────────────────────────────────────────────
st.markdown("### ⏳ 待发送")
if pending:
    now_utc = datetime.now(timezone.utc)
    for job in pending:
        sched = job.get('scheduled_utc')
        if sched and hasattr(sched, 'tzinfo') and sched.tzinfo is None:
            sched = sched.replace(tzinfo=timezone.utc)

        is_due = sched and now_utc >= sched
        border_color = "#4CAF50" if is_due else "#FF9800"
        status_label = "🟢 可立即发送" if is_due else "🟡 定时等待中"

        with st.container():
            st.markdown(
                f"<div style='border-left:4px solid {border_color};padding:12px 16px;"
                f"background:#FAFAFA;border-radius:6px;margin:8px 0'>",
                unsafe_allow_html=True
            )
            col_a, col_b, col_c = st.columns([2, 2, 1])
            with col_a:
                st.markdown(f"**{job.get('company_name','')}**")
                st.markdown(f"📧 `{job.get('to_email','')}`")
            with col_b:
                st.markdown(f"**主题：** {job.get('subject','')}")
                local_time = job.get('scheduled_local', '')
                st.markdown(f"**定时：** {local_time} {status_label}")
            with col_c:
                st.markdown(f"**ID：** `{job.get('queue_id','')}`")
            with st.expander("查看正文"):
                st.text(job.get('body', ''))
            st.markdown("</div>", unsafe_allow_html=True)
else:
    st.info("✅ 队列为空，无待发邮件")

# ── SENT EMAILS ───────────────────────────────────────────────────────────────
st.markdown("### ✅ 已发送")
if sent:
    for job in sent[:20]:
        sent_time = str(job.get('sent_at', ''))[:16]
        st.markdown(
            f"<div style='border-left:4px solid #4CAF50;padding:10px 14px;"
            f"background:#F1F8E9;border-radius:6px;margin:6px 0;font-size:13px'>"
            f"✅ <b>{job.get('company_name','')}</b> → `{job.get('to_email','')}`<br>"
            f"📝 {job.get('subject','')} "
            f"<span style='float:right;color:#666'>{sent_time}</span>"
            f"</div>", unsafe_allow_html=True
        )
else:
    st.info("暂无已发送记录")

# ── FAILED EMAILS ─────────────────────────────────────────────────────────────
if failed:
    st.markdown("### ❌ 发送失败")
    for job in failed:
        st.markdown(
            f"<div style='border-left:4px solid #F44336;padding:10px 14px;"
            f"background:#FFEBEE;border-radius:6px;margin:6px 0;font-size:13px'>"
            f"❌ <b>{job.get('company_name','')}</b> → `{job.get('to_email','')}`<br>"
            f"📝 {job.get('subject','')}<br>"
            f"⚠️ 错误：{job.get('error_message','未知错误')} "
            f"| 重试次数：{job.get('retry_count',0)}"
            f"</div>", unsafe_allow_html=True
        )
