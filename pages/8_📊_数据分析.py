"""Analytics — reply rates, funnel, and performance tracking."""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import date, timedelta
from utils.database import get_all_leads, get_conn

st.set_page_config(page_title="数据分析 | EETOON CRM", page_icon="📊", layout="wide")

if not st.session_state.get("authenticated"):
    st.warning("请先登录"); st.stop()

st.markdown("## 📊 数据分析")

leads = get_all_leads()
if not leads:
    st.info("暂无数据"); st.stop()

# ── FUNNEL ────────────────────────────────────────────────────────────────────
st.markdown("#### 🎯 开发漏斗")
total = len(leads)
sent = len([l for l in leads if l.get('touch_count', 0) >= 1])
replied = len([l for l in leads if l.get('status') == '有回复'])
reply_rate = replied / sent * 100 if sent > 0 else 0

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("客户总数", total)
with col2:
    st.metric("已触达", sent, f"{sent/total*100:.0f}%" if total else "0%")
with col3:
    st.metric("有回复", replied, f"{reply_rate:.1f}%")
with col4:
    avg_touches = sum(l.get('touch_count',0) for l in leads) / total if total else 0
    st.metric("平均触达次数", f"{avg_touches:.1f}")

fig_funnel = go.Figure(go.Funnel(
    y=["客户总数", "已触达", "有回复"],
    x=[total, sent, replied],
    textinfo="value+percent initial",
    marker_color=["#1976D2", "#FF9800", "#4CAF50"]
))
fig_funnel.update_layout(height=250, margin=dict(t=10, b=10))
st.plotly_chart(fig_funnel, use_container_width=True)

st.markdown("---")

# ── STATUS BREAKDOWN ──────────────────────────────────────────────────────────
col_left, col_right = st.columns(2)

with col_left:
    st.markdown("#### 状态分布")
    status_counts = {}
    for l in leads:
        s = l.get('status', '新建')
        status_counts[s] = status_counts.get(s, 0) + 1
    df_status = pd.DataFrame(list(status_counts.items()), columns=['状态', '数量'])
    df_status = df_status.sort_values('数量', ascending=False)
    st.dataframe(df_status, use_container_width=True, hide_index=True)

with col_right:
    st.markdown("#### 地区分布")
    region_counts = {}
    for l in leads:
        loc = l.get('location', '未知')
        state = loc.split('/')[-1].split(',')[-1].strip()[:10] if loc else '未知'
        region_counts[state] = region_counts.get(state, 0) + 1
    df_region = pd.DataFrame(list(region_counts.items()), columns=['地区', '数量'])
    df_region = df_region.sort_values('数量', ascending=False)
    fig_region = px.bar(df_region, x='地区', y='数量', color='数量',
                        color_continuous_scale='Blues')
    fig_region.update_layout(height=250, margin=dict(t=10, b=10, l=10, r=10))
    st.plotly_chart(fig_region, use_container_width=True)

st.markdown("---")

# ── SCORE DISTRIBUTION ────────────────────────────────────────────────────────
st.markdown("#### 🏆 客户评分排行榜（TOP 10）")
sorted_leads = sorted(leads, key=lambda x: x.get('score', 0), reverse=True)
top10 = sorted_leads[:10]
df_top = pd.DataFrame([{
    '评分': f"{l.get('score_grade','C')} ({l.get('score',0)})",
    '公司名': l['company_name'],
    '地区': l.get('location',''),
    '袋包信号': l.get('bag_signal_strength',''),
    '状态': l.get('status',''),
    '触达次数': l.get('touch_count',0),
} for l in top10])
st.dataframe(df_top, use_container_width=True, hide_index=True)

st.markdown("---")

# ── EMAIL HISTORY ANALYSIS ────────────────────────────────────────────────────
st.markdown("#### ✉️ 邮件发送历史")
try:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT DATE(sent_at) as send_date, COUNT(*) as count
        FROM email_history
        WHERE sent_at IS NOT NULL
        GROUP BY DATE(sent_at)
        ORDER BY send_date DESC
        LIMIT 30
    """)
    rows = cur.fetchall()
    cur.close(); conn.close()

    if rows:
        df_hist = pd.DataFrame(rows, columns=['发送日期', '封数'])
        fig_hist = px.bar(df_hist, x='发送日期', y='封数',
                         title='每日发送量', color_discrete_sequence=['#1976D2'])
        fig_hist.update_layout(height=250, margin=dict(t=30, b=10))
        st.plotly_chart(fig_hist, use_container_width=True)
    else:
        st.info("暂无发送历史数据")
except Exception as e:
    st.error(f"数据加载失败：{e}")

st.markdown("---")

# ── EXPORT ────────────────────────────────────────────────────────────────────
st.markdown("#### 📥 导出数据")
col_exp1, col_exp2 = st.columns(2)
with col_exp1:
    df_export = pd.DataFrame([{
        '公司名': l['company_name'],
        '联系人': l.get('contact_name',''),
        '邮件': l.get('email',''),
        '官网': l.get('website',''),
        '地区': l.get('location',''),
        '规模': l.get('company_size',''),
        '状态': l.get('status',''),
        '触达次数': l.get('touch_count',0),
        '评分': l.get('score',0),
        '评级': l.get('score_grade','C'),
        '发送日期': str(l.get('send_date','')),
        'Day7': str(l.get('day7_date','')),
        'Day14': str(l.get('day14_date','')),
        'Day21': str(l.get('day21_date','')),
        '激活日期': str(l.get('reactivation_date','')),
        '备注': l.get('notes',''),
    } for l in leads])
    csv = df_export.to_csv(index=False).encode('utf-8-sig')
    st.download_button("📥 导出全部客户 (CSV)", csv,
                      f"eetoon_leads_{date.today()}.csv", "text/csv",
                      use_container_width=True)
with col_exp2:
    st.caption("Excel格式：下载CSV后用Excel打开即可，中文字段使用utf-8-sig编码")
