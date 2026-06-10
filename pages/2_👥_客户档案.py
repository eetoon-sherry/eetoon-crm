"""Client profiles page — full cards with research data and history."""

import streamlit as st
from datetime import date
from utils.database import (get_all_leads, get_lead, update_lead,
                             update_lead_status, get_email_history,
                             get_notes, add_note, get_setting)

st.set_page_config(page_title="客户档案 | EETOON CRM", page_icon="👥", layout="wide")

if not st.session_state.get("authenticated"):
    st.warning("请先登录"); st.stop()

st.markdown("## 👥 客户档案")

# ── FILTER BAR ────────────────────────────────────────────────────────────────
statuses_cfg = get_setting("statuses", [])
status_labels = ["全部"] + [s["label"] for s in statuses_cfg]
status_color_map = {s["label"]: s["color"] for s in statuses_cfg}

col_f1, col_f2, col_f3 = st.columns([2, 1, 1])
with col_f1:
    search_q = st.text_input("🔍 搜索公司名/联系人/邮件", placeholder="输入关键词...")
with col_f2:
    status_filter = st.selectbox("状态筛选", status_labels)
with col_f3:
    sort_by = st.selectbox("排序", ["评分从高到低", "最近发送", "公司名"])

# Load leads
all_leads = get_all_leads()

# Apply filters
filtered = all_leads
if status_filter != "全部":
    filtered = [l for l in filtered if l.get('status') == status_filter]
if search_q:
    q = search_q.lower()
    filtered = [l for l in filtered if
                q in (l.get('company_name') or '').lower() or
                q in (l.get('contact_name') or '').lower() or
                q in (l.get('email') or '').lower()]

if sort_by == "评分从高到低":
    filtered = sorted(filtered, key=lambda x: x.get('score', 0), reverse=True)
elif sort_by == "最近发送":
    filtered = sorted(filtered, key=lambda x: x.get('send_date') or date(2000,1,1), reverse=True)
else:
    filtered = sorted(filtered, key=lambda x: x.get('company_name', ''))

st.markdown(f"**共 {len(filtered)} 家客户**")
st.markdown("---")

# ── LEAD CARDS ────────────────────────────────────────────────────────────────
for lead in filtered:
    status = lead.get('status', '新建')
    status_color = status_color_map.get(status, '#9E9E9E')
    grade = lead.get('score_grade', 'C')
    grade_color = {'A': '#4CAF50', 'B': '#FF9800', 'C': '#9E9E9E'}.get(grade, '#9E9E9E')
    signal_map = {'强': '🔴', '较强': '🟠', '中': '🟡', '弱': '⚪', '': '⚪'}
    signal_icon = signal_map.get(lead.get('bag_signal_strength', ''), '⚪')

    header = (f"{signal_icon} **{lead['company_name']}** "
              f"| {lead.get('contact_name','')} "
              f"| {lead.get('location','')} "
              f"| {lead.get('company_size','')}人")

    with st.expander(header, expanded=False):
        # ── TOP ROW: status badge + grade + actions
        top1, top2, top3, top4 = st.columns([2, 1, 1, 2])
        with top1:
            st.markdown(
                f"<span style='background:{status_color}22;color:{status_color};"
                f"padding:4px 12px;border-radius:20px;font-weight:600;font-size:13px'>"
                f"{status}</span>", unsafe_allow_html=True
            )
        with top2:
            st.markdown(
                f"<span style='background:{grade_color}22;color:{grade_color};"
                f"padding:4px 12px;border-radius:20px;font-weight:700;font-size:13px'>"
                f"评分 {grade} ({lead.get('score',0)}分)</span>", unsafe_allow_html=True
            )
        with top3:
            st.markdown(f"触达 **{lead.get('touch_count',0)}/3**")
        with top4:
            # Quick status update
            statuses_opts = [s["label"] for s in statuses_cfg]
            new_status = st.selectbox(
                "更新状态", statuses_opts,
                index=statuses_opts.index(status) if status in statuses_opts else 0,
                key=f"status_{lead['id']}"
            )
            if new_status != status:
                if st.button("确认更新", key=f"btn_status_{lead['id']}", type="primary"):
                    update_lead_status(lead['id'], new_status)
                    st.success(f"已更新为：{new_status}")
                    st.rerun()

        st.markdown("---")

        # ── MAIN INFO COLUMNS
        c1, c2, c3 = st.columns(3)

        with c1:
            st.markdown("##### 📋 基本信息")
            st.markdown(f"**官网：** [{lead.get('website','')}]({lead.get('website','')})")
            st.markdown(f"**邮件：** `{lead.get('email','')}`")
            st.markdown(f"**PPAI会员：** {lead.get('ppai_member','待查')}")
            st.markdown(f"**发送日期：** {lead.get('send_date','—')}")
            st.markdown(f"**Day7跟进：** {lead.get('day7_date','—')}")
            st.markdown(f"**Day14跟进：** {lead.get('day14_date','—')}")
            st.markdown(f"**Day21跟进：** {lead.get('day21_date','—')}")
            if lead.get('reactivation_date'):
                st.markdown(f"**激活日期：** {lead.get('reactivation_date','—')}")

        with c2:
            st.markdown("##### 🔍 背调情报")
            if lead.get('company_direction'):
                st.markdown(f"**主营方向：**\n{lead.get('company_direction')}")
            if lead.get('bag_signal'):
                st.markdown(f"**袋包信号 {signal_icon}：**\n{lead.get('bag_signal')}")
            if lead.get('owner_topics'):
                st.markdown(f"**Owner近期话题：**\n{lead.get('owner_topics')}")
            if lead.get('hook_direction'):
                st.markdown(
                    f"<div style='background:#1976D215;border-left:3px solid #1976D2;"
                    f"padding:8px 12px;border-radius:4px;margin:8px 0;font-size:13px'>"
                    f"💡 <b>推荐Hook：</b><br>{lead.get('hook_direction')}</div>",
                    unsafe_allow_html=True
                )
            if lead.get('recommended_cta'):
                st.markdown(f"**推荐CTA资源：** `{lead.get('recommended_cta')}`")

        with c3:
            st.markdown("##### 🔗 社媒档案")
            if lead.get('owner_linkedin'):
                st.markdown(f"**Owner LinkedIn：**\n[查看]({lead.get('owner_linkedin')})")
            if lead.get('company_linkedin'):
                st.markdown(f"**公司LinkedIn：**\n[查看]({lead.get('company_linkedin')})")
            if lead.get('linkedin_active'):
                st.markdown(f"**LinkedIn活跃度：** {lead.get('linkedin_active')}")
            if lead.get('instagram'):
                st.markdown(f"**Instagram：** {lead.get('instagram')}")

        st.markdown("---")

        # ── EMAIL HISTORY
        history = get_email_history(lead['id'])
        st.markdown(f"##### ✉️ 触达记录 ({len(history)} 封)")
        if history:
            for h in history:
                sent_time = str(h.get('sent_at', ''))[:16]
                with st.container():
                    st.markdown(
                        f"<div style='background:#F5F5F5;padding:10px 14px;"
                        f"border-radius:6px;margin:6px 0;font-size:13px'>"
                        f"📨 <b>{h.get('subject','')}</b>"
                        f"<span style='float:right;color:#999'>{sent_time}</span><br>"
                        f"<span style='color:#666'>{(h.get('body') or '')[:120]}...</span>"
                        f"</div>", unsafe_allow_html=True
                    )
        else:
            st.caption("暂无触达记录")

        # ── NOTES
        st.markdown("##### 📝 跟进笔记")
        notes = get_notes(lead['id'])
        if notes:
            for note in notes:
                icon_map = {'email_reply':'💬','phone_call':'📞','meeting':'🤝',
                           'status_change':'🔄','other':'📌'}
                icon = icon_map.get(note.get('note_type','other'), '📌')
                time_str = str(note.get('created_at',''))[:16]
                st.markdown(
                    f"<div style='background:#E8F5E9;padding:8px 12px;border-radius:6px;"
                    f"margin:4px 0;font-size:13px'>{icon} {note.get('content','')} "
                    f"<span style='color:#999;float:right'>{time_str}</span></div>",
                    unsafe_allow_html=True
                )

        with st.form(key=f"note_form_{lead['id']}"):
            note_type = st.selectbox("类型", ["other","email_reply","phone_call","meeting"],
                                     format_func=lambda x: {"other":"📌备注","email_reply":"💬邮件回复",
                                                             "phone_call":"📞电话","meeting":"🤝见面"}[x])
            note_content = st.text_area("内容", height=60)
            if st.form_submit_button("添加笔记"):
                if note_content.strip():
                    add_note(lead['id'], note_type, note_content.strip())
                    st.success("✅ 已添加")
                    st.rerun()

        # ── EDIT BASIC INFO
        with st.expander("✏️ 编辑基本信息", expanded=False):
            with st.form(key=f"edit_form_{lead['id']}"):
                e1, e2 = st.columns(2)
                with e1:
                    new_contact = st.text_input("联系人", value=lead.get('contact_name',''))
                    new_email = st.text_input("邮件", value=lead.get('email',''))
                    new_size = st.text_input("公司规模", value=lead.get('company_size',''))
                with e2:
                    new_website = st.text_input("官网", value=lead.get('website',''))
                    new_location = st.text_input("地区", value=lead.get('location',''))
                    new_ppai = st.selectbox("PPAI会员", ["待查","是","否"],
                                           index=["待查","是","否"].index(lead.get('ppai_member','待查'))
                                           if lead.get('ppai_member','待查') in ["待查","是","否"] else 0)
                new_notes = st.text_area("备注", value=lead.get('notes',''))
                if st.form_submit_button("保存"):
                    update_lead(lead['id'],
                        contact_name=new_contact, email=new_email,
                        company_size=new_size, website=new_website,
                        location=new_location, ppai_member=new_ppai,
                        notes=new_notes)
                    st.success("✅ 已保存")
                    st.rerun()
