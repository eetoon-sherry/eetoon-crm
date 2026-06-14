"""EETOON CRM — Main entry with login and dashboard overview."""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import date, timedelta
from utils.database import (
    ensure_schema,
    get_mission_control,
    get_all_leads,
    get_due_followups,
    get_last_db_error,
    get_reactivation_due,
    get_setting,
    get_stats,
    has_db_config,
)
from utils.email_sender import process_due_emails
from utils.timezone import beijing_today

st.set_page_config(
    page_title="EETOON CRM",
    page_icon="🧳",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ── AUTH ──────────────────────────────────────────────────────────────────────
def check_auth():
    import os

    try:
        correct_pw = st.secrets.get("auth", {}).get("password", "")
    except Exception:
        correct_pw = ""
    correct_pw = correct_pw or os.getenv("CRM_PASSWORD", "")

    if not correct_pw:
        st.error("访问密码未配置。请在 Streamlit Secrets 中设置 [auth].password。")
        st.stop()

    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if not st.session_state.authenticated:
        st.markdown("""
        <div style='text-align:center;padding:60px 0 30px'>
        <h1>🧳 EETOON CRM</h1>
        <p style='color:#666;font-size:16px'>B2B 客户开发管理系统</p>
        </div>
        """, unsafe_allow_html=True)
        col1, col2, col3 = st.columns([1, 1, 1])
        with col2:
            pw = st.text_input("访问密码", type="password", placeholder="输入密码登录")
            if st.button("登录", use_container_width=True, type="primary"):
                if pw == correct_pw:
                    st.session_state.authenticated = True
                    st.rerun()
                else:
                    st.error("密码错误")
        st.stop()

check_auth()
ensure_schema()

# ── AUTO PROCESS QUEUE (runs every page load) ─────────────────────────────────
today_cn = beijing_today()

if "last_queue_check" not in st.session_state:
    st.session_state.last_queue_check = today_cn

if st.session_state.last_queue_check != today_cn:
    sent, failed = process_due_emails()
    st.session_state.last_queue_check = today_cn
    if sent > 0:
        st.toast(f"✅ 自动发送 {sent} 封邮件", icon="📬")
    if failed > 0:
        st.toast(f"⚠️ {failed} 封邮件发送失败，请检查队列", icon="⚠️")

# ── LOAD DATA ─────────────────────────────────────────────────────────────────
stats = get_stats()
leads = get_all_leads()
due_followups = get_due_followups()
reactivation_due = get_reactivation_due()
statuses = get_setting("statuses", [])
status_color_map = {s["label"]: s["color"] for s in statuses} if statuses else {}
mission = get_mission_control()

# ── SIDEBAR ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 🧳 EETOON CRM")
    st.markdown("---")
    st.markdown(f"**Sherry XIE** | EETOON GROUP")
    st.markdown(f"📅 {today_cn.strftime('%Y年%m月%d日')}")
    st.markdown("---")

    # Quick manual queue trigger
    if st.button("📬 立即处理发送队列", use_container_width=True):
        with st.spinner("发送中..."):
            sent, failed = process_due_emails()
        if sent:
            st.success(f"已发送 {sent} 封")
        elif failed:
            st.error(f"{failed} 封失败")
        else:
            st.info("暂无到期邮件")

    st.markdown("---")
    st.markdown("##### 📍 今日提醒")
    if due_followups:
        for lead in due_followups[:5]:
            st.markdown(f"• **{lead['company_name'][:18]}** 待跟进")
    else:
        st.markdown("✅ 今日无到期跟进")

    if reactivation_due:
        st.markdown(f"##### 🔔 冷静期到期")
        for lead in reactivation_due[:3]:
            st.markdown(f"• {lead['company_name'][:18]}")

    db_error = get_last_db_error()
    if db_error:
        st.markdown("---")
        st.warning("数据库暂不可用，当前显示为空数据。请检查 Supabase Secrets。")

# ── HEADER ────────────────────────────────────────────────────────────────────
st.markdown("## Mission Control / 今日工作台")
if not has_db_config():
    st.warning("数据库未配置：请在 Streamlit Secrets 中添加 `[supabase]` 的连接信息。")
elif get_last_db_error():
    st.warning("数据库连接失败，页面已进入空数据模式。修复连接后刷新即可恢复。")

campaign = mission.get("campaign") or {}
metrics = mission.get("metrics") or {}
judgement = mission.get("judgement") or {}
review_counts = mission.get("review_counts") or {}
candidate_email_counts = mission.get("candidate_email_counts") or {}

st.markdown(f"**当前优先 Campaign：** {campaign.get('campaign_name', '未创建')}")
st.caption(campaign.get("target_segment", ""))

task_cols = st.columns(6)
task_cards = [
    ("候选待审核", review_counts.get("candidate_company", len(mission.get("candidate_reviews", [])))),
    ("待确认邮箱", candidate_email_counts.get("missing_email", 0)),
    ("邮件待审核", review_counts.get("first_email", 0) + review_counts.get("followup_email", 0)),
    ("今日跟进", len(mission.get("due_followups", []))),
    ("回复待判断", review_counts.get("reply", len(mission.get("reply_reviews", [])))),
    ("Campaign已发送", metrics.get("sent", 0)),
]
for col, (label, value) in zip(task_cols, task_cards):
    with col:
        st.metric(label, value)

st.markdown("#### AI 今日建议")
st.info(
    f"判断：{judgement.get('decision', '暂无')} | "
    f"瓶颈：{judgement.get('bottleneck', '暂无')} | "
    f"置信度：{judgement.get('confidence', '低')}\n\n"
    f"下一步：{judgement.get('next_action', '先补齐配置并产生真实发送数据。')}"
)

with st.expander("判断依据", expanded=False):
    for item in judgement.get("evidence", []):
        st.markdown(f"- {item}")
    if judgement.get("risk"):
        st.warning(judgement["risk"])

st.markdown("---")
col_work1, col_work2 = st.columns(2)
with col_work1:
    st.markdown("#### 待审核候选客户")
    candidate_reviews = mission.get("candidate_reviews", [])
    if candidate_reviews:
        for item in candidate_reviews[:8]:
            st.markdown(f"- **{item.get('title','')}** — {item.get('summary','')}")
        st.caption("去 Review Queue 批量处理。")
    else:
        st.info("暂无待审核候选。先去客户搜索导入/搜索候选客户。")

    st.markdown("#### 待审核开发信/跟进信")
    email_reviews = mission.get("email_reviews", [])
    if email_reviews:
        for item in email_reviews[:8]:
            st.markdown(f"- **{item.get('title','')}** — {item.get('summary','')}")
    else:
        st.info("暂无待审核邮件。")

with col_work2:
    st.markdown("#### 今日到期跟进")
    if due_followups:
        for lead in due_followups[:10]:
            st.markdown(f"- **{lead['company_name']}** / {lead.get('contact_name','')} / touch {lead.get('touch_count',0)}")
    else:
        st.info("今日无到期跟进。")

    st.markdown("#### 当前 Campaign 核心数据")
    metric_cols = st.columns(3)
    metric_cols[0].metric("候选", metrics.get("candidates", 0))
    metric_cols[1].metric("合格", metrics.get("qualified", 0))
    metric_cols[2].metric("回复率", f"{metrics.get('reply_rate', 0)}%")
    metric_cols2 = st.columns(3)
    metric_cols2[0].metric("退信率", f"{metrics.get('bounce_rate', 0)}%")
    metric_cols2[1].metric("正向回复率", f"{metrics.get('positive_reply_rate', 0)}%")
    metric_cols2[2].metric("待人工处理", metrics.get("pending_reviews", 0))

st.markdown("---")
st.markdown("## 📊 总览仪表盘")

# ── KPI CARDS ─────────────────────────────────────────────────────────────────
col1, col2, col3, col4, col5, col6 = st.columns(6)
kpis = [
    ("总客户数", stats['total'], "#1976D2", "👥"),
    ("开发中", stats['active'], "#FF9800", "📤"),
    ("有回复", stats['replied'], "#4CAF50", "💬"),
    ("冷静期", stats['cold'], "#607D8B", "❄️"),
    ("待发邮件", stats['pending_emails'], "#9C27B0", "📬"),
    ("累计发信", stats['total_sent'], "#00BCD4", "✉️"),
]
for col, (label, value, color, icon) in zip([col1,col2,col3,col4,col5,col6], kpis):
    with col:
        st.markdown(f"""
        <div style='background:{color}15;border-left:4px solid {color};
                    padding:12px 16px;border-radius:8px;margin-bottom:8px'>
        <div style='font-size:22px;font-weight:700;color:{color}'>{icon} {value}</div>
        <div style='font-size:12px;color:#666;margin-top:2px'>{label}</div>
        </div>
        """, unsafe_allow_html=True)

st.markdown("---")

# ── STATUS CHART + SCORE DISTRIBUTION ────────────────────────────────────────
col_left, col_right = st.columns([1, 1])

with col_left:
    st.markdown("#### 客户状态分布")
    if leads:
        status_counts = {}
        for lead in leads:
            s = lead.get('status', '新建')
            status_counts[s] = status_counts.get(s, 0) + 1

        colors = [status_color_map.get(s, "#9E9E9E") for s in status_counts.keys()]
        fig = go.Figure(data=[go.Pie(
            labels=list(status_counts.keys()),
            values=list(status_counts.values()),
            marker_colors=colors,
            hole=0.45,
            textfont_size=12,
        )])
        fig.update_layout(
            showlegend=True, height=280,
            margin=dict(t=10, b=10, l=10, r=10),
            legend=dict(font=dict(size=11))
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("暂无数据")

with col_right:
    st.markdown("#### 客户评分分布 (A/B/C级)")
    if leads:
        grade_counts = {'A': 0, 'B': 0, 'C': 0}
        for lead in leads:
            g = lead.get('score_grade', 'C')
            grade_counts[g] = grade_counts.get(g, 0) + 1
        fig2 = go.Figure(data=[go.Bar(
            x=list(grade_counts.keys()),
            y=list(grade_counts.values()),
            marker_color=['#4CAF50', '#FF9800', '#9E9E9E'],
            text=list(grade_counts.values()),
            textposition='outside',
        )])
        fig2.update_layout(
            height=280, margin=dict(t=10, b=10, l=10, r=10),
            xaxis_title="等级", yaxis_title="客户数",
            plot_bgcolor='rgba(0,0,0,0)'
        )
        st.plotly_chart(fig2, use_container_width=True)

st.markdown("---")

# ── ALL LEADS TABLE ───────────────────────────────────────────────────────────
st.markdown("#### 全部客户一览")

if leads:
    df_data = []
    for lead in leads:
        status = lead.get('status', '')
        color = status_color_map.get(status, '#9E9E9E')
        due_flag = any(l['id'] == lead['id'] for l in due_followups)
        df_data.append({
            '评分': f"{lead.get('score_grade','C')} ({lead.get('score',0)})",
            '公司名': lead['company_name'],
            '联系人': lead.get('contact_name', ''),
            '地区': lead.get('location', ''),
            '规模': lead.get('company_size', ''),
            '状态': status,
            '触达次数': lead.get('touch_count', 0),
            '发送日': str(lead.get('send_date', '')) if lead.get('send_date') else '—',
            'Day7跟进': str(lead.get('day7_date', '')) if lead.get('day7_date') else '—',
            '⏰': '📋 待跟进' if due_flag else '',
        })

    df = pd.DataFrame(df_data)

    # Color rows by status
    def color_status(val):
        color_map = status_color_map
        c = color_map.get(val, '#9E9E9E')
        return f'background-color: {c}25; color: {c}; font-weight: 600; border-radius: 4px; padding: 2px 6px'

    styler = df.style
    if hasattr(styler, "map"):
        styled = styler.map(color_status, subset=['状态'])
    else:
        styled = styler.applymap(color_status, subset=['状态'])
    st.dataframe(styled, use_container_width=True, height=420, hide_index=True)
else:
    st.info("暂无客户数据")

# ── FOLLOWUP ALERT ────────────────────────────────────────────────────────────
if due_followups:
    st.markdown("---")
    st.markdown("#### ⏰ 今日到期跟进")
    for lead in due_followups:
        with st.expander(f"📌 {lead['company_name']} — {lead.get('contact_name','')} ({lead.get('location','')})", expanded=False):
            col_a, col_b = st.columns(2)
            with col_a:
                st.markdown(f"**邮件:** {lead.get('email','')}")
                st.markdown(f"**触达次数:** {lead.get('touch_count',0)}/3")
                st.markdown(f"**上次主题:** {lead.get('last_subject','—')}")
            with col_b:
                st.markdown(f"**推荐Hook方向:** {lead.get('hook_direction','—')}")
                st.markdown(f"**推荐CTA:** {lead.get('recommended_cta','—')}")
            st.markdown(f"[→ 前往邮件编辑器](编辑跟进邮件)")
