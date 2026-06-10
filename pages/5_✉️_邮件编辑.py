"""Email composer — write, validate, and queue outreach emails."""

import streamlit as st
from utils.database import get_all_leads, get_setting, get_templates, add_template
from utils.email_sender import validate_content, queue_email

st.set_page_config(page_title="邮件编辑 | EETOON CRM", page_icon="✉️", layout="wide")

if not st.session_state.get("authenticated"):
    st.warning("请先登录"); st.stop()

st.markdown("## ✉️ 邮件编辑器")

tab_compose, tab_templates = st.tabs(["📝 写邮件", "📚 模板库"])

TZ_STATE_MAP = {
    '加州/CA': 'CA', '德克萨斯/TX': 'TX', '纽约/NY': 'NY',
    '佛罗里达/FL': 'FL', '伊利诺伊/IL': 'IL', '科罗拉多/CO': 'CO',
    '田纳西/TN': 'TN', '俄亥俄/OH': 'OH', '华盛顿州/WA': 'WA',
    '密苏里/MO': 'MO', '新泽西/NJ': 'NJ', '南卡/SC': 'SC',
    '肯塔基/KY': 'KY', '犹他/UT': 'UT', '俄克拉荷马/OK': 'OK',
    '威斯康星/WI': 'WI', '佐治亚/GA': 'GA', '北卡/NC': 'NC',
    '其他/ET': 'NY'
}

CTA_RESOURCES = get_setting("cta_resources", [
    "Bag Styles for Various Gifting Occasions",
    "RPET+GRS认证指南", "袋包规格清单", "10周定制订单时间轴"
])
FORBIDDEN = get_setting("forbidden_phrases", [])

with tab_compose:
    # ── SELECT LEAD ───────────────────────────────────────────────────────────
    all_leads = get_all_leads()
    lead_options = {f"{l['company_name']} | {l.get('contact_name','')} | {l.get('email','')}": l
                    for l in all_leads}

    selected_label = st.selectbox("选择目标客户（或手动输入）", ["手动输入"] + list(lead_options.keys()))

    if selected_label != "手动输入":
        selected_lead = lead_options[selected_label]
        contact_name = selected_lead.get('contact_name', '')
        to_email = selected_lead.get('email', '')
        to_name = contact_name.split()[0] if contact_name else ''
        company = selected_lead.get('company_name', '')
        location = selected_lead.get('location', '')
        lead_id = selected_lead['id']

        # Auto-detect state
        state_abbr = 'TX'
        for part in location.replace('/',' ').split():
            if part.upper() in ['TX','FL','NY','CA','CO','IL','TN','OH','WA','MO','NJ','SC','KY','UT','OK','WI','GA','NC']:
                state_abbr = part.upper()
                break

        with st.container():
            st.markdown(
                f"<div style='background:#E3F2FD;padding:10px 16px;border-radius:8px;font-size:13px'>"
                f"📋 <b>{company}</b> | 📧 {to_email} | 📍 {location} | "
                f"触达次数：{selected_lead.get('touch_count',0)}/3 | "
                f"评分：{selected_lead.get('score_grade','C')}({selected_lead.get('score',0)}分)<br>"
                f"💡 推荐Hook：{selected_lead.get('hook_direction','—')}"
                f"</div>", unsafe_allow_html=True
            )
        st.markdown("")
    else:
        col_m1, col_m2, col_m3 = st.columns(3)
        with col_m1:
            company = st.text_input("公司名", "")
            to_email = st.text_input("收件人邮件", "")
        with col_m2:
            to_name = st.text_input("收件人名字（Hi后面的称呼）", "")
            contact_name = to_name
        with col_m3:
            tz_label = st.selectbox("时区（所在州）", list(TZ_STATE_MAP.keys()))
            state_abbr = TZ_STATE_MAP[tz_label]
        lead_id = None

    st.markdown("---")

    # ── COMPOSE ───────────────────────────────────────────────────────────────
    col_left, col_right = st.columns([2, 1])

    with col_left:
        subject = st.text_input(
            "主题行",
            placeholder="控制在50字符以内",
            help="上限50字符，尽量具体，不要泛泛"
        )
        char_count = len(subject)
        char_color = "red" if char_count > 50 else ("#FF9800" if char_count > 40 else "green")
        st.markdown(f"<small style='color:{char_color}'>{char_count}/50 字符</small>",
                    unsafe_allow_html=True)

        body = st.text_area(
            "正文（不含签名）",
            height=280,
            placeholder=(
                "结构：\n"
                "① 第一段 Hook：具体调研发现，换家公司这句话就不成立\n"
                "② 第二段：I'm Sherry from EETOON...\n"
                "③ 第三段 CTA：提供一个资源"
            )
        )
        word_count = len(body.split()) if body else 0
        word_color = "red" if word_count > 120 else ("#FF9800" if word_count > 100 else "green")
        st.markdown(f"<small style='color:{word_color}'>{word_count}/120 词</small>",
                    unsafe_allow_html=True)

    with col_right:
        st.markdown("##### ✅ 实时校验")
        if subject or body:
            errors = validate_content(subject, body)
            if not errors:
                st.success("✅ 内容通过校验")
            else:
                for err in errors:
                    st.error(f"❌ {err}")

        st.markdown("##### 📎 CTA资源参考")
        for cta in CTA_RESOURCES:
            st.markdown(f"• {cta}")

        st.markdown("##### 🚫 禁用词提醒")
        combined = (subject + ' ' + body).lower()
        for phrase in FORBIDDEN:
            if phrase in combined:
                st.error(f"⚠️ 包含：'{phrase}'")

        st.markdown("##### ⏰ 发送时间预览")
        if state_abbr:
            from utils.email_sender import next_send_window
            try:
                sched_utc, tz_name, local_time = next_send_window(state_abbr)
                from zoneinfo import ZoneInfo
                beijing = sched_utc.astimezone(ZoneInfo('Asia/Shanghai'))
                st.info(f"📅 {local_time.strftime('%m-%d %H:%M')} {tz_name.split('/')[-1]}\n"
                        f"🕐 北京时间：{beijing.strftime('%m-%d %H:%M')}")
            except Exception:
                st.info("时区计算中...")

    st.markdown("---")

    # ── SIGNATURE PREVIEW ─────────────────────────────────────────────────────
    signature = get_setting("sender_signature", "")
    if signature:
        with st.expander("👁️ 签名预览"):
            st.text(signature)

    # ── ACTION BUTTONS ────────────────────────────────────────────────────────
    col_q, col_s, col_t = st.columns(3)
    errors = validate_content(subject, body) if (subject and body) else ['内容为空']

    with col_q:
        if st.button("📬 排入定时队列", type="primary", disabled=bool(errors),
                     use_container_width=True):
            if lead_id:
                job = queue_email(lead_id, company, to_email, to_name or contact_name,
                                  subject, body, state_abbr)
            else:
                from utils.email_sender import queue_email as qe
                from utils.database import add_to_queue
                import uuid
                from datetime import datetime, timezone, timedelta
                from utils.email_sender import next_send_window
                sched_utc, tz_name, local_time = next_send_window(state_abbr)
                job = {
                    'queue_id': str(uuid.uuid4())[:8],
                    'lead_id': None,
                    'company_name': company,
                    'to_email': to_email,
                    'to_name': to_name,
                    'subject': subject,
                    'body': body,
                    'recipient_tz': tz_name,
                    'scheduled_utc': sched_utc,
                    'scheduled_local': local_time.strftime('%Y-%m-%d %H:%M %Z'),
                    'status': 'pending',
                }
                add_to_queue(job)
            st.success(f"✅ 已排入队列！发送时间：{job['scheduled_local']}")

    with col_s:
        if st.button("💾 保存为模板", disabled=bool(errors), use_container_width=True):
            st.session_state['save_template'] = True

    with col_t:
        if st.button("🔄 清空", use_container_width=True):
            st.rerun()

    # ── SAVE TEMPLATE FORM ────────────────────────────────────────────────────
    if st.session_state.get('save_template'):
        with st.form("save_template_form"):
            st.markdown("**保存为模板**")
            t1, t2, t3 = st.columns(3)
            with t1:
                t_name = st.text_input("模板名称", placeholder="e.g. RPET首封-eco方向")
            with t2:
                t_cat = st.selectbox("分类", ["eco","gifting","trade-show","new-hire","general","已回复高效"])
            with t3:
                t_touch = st.selectbox("触达阶段", [1,2,3], format_func=lambda x: f"第{x}封")
            if st.form_submit_button("保存"):
                add_template({'name': t_name, 'category': t_cat,
                              'touch_number': t_touch, 'subject': subject, 'body': body})
                st.success("✅ 模板已保存")
                st.session_state['save_template'] = False
                st.rerun()


# ── TEMPLATE LIBRARY ──────────────────────────────────────────────────────────
with tab_templates:
    st.markdown("#### 📚 模板库")

    tf1, tf2, tf3 = st.columns(3)
    with tf1:
        cat_filter = st.selectbox("分类", ["全部","eco","gifting","trade-show","new-hire","general","已回复高效"])
    with tf2:
        touch_filter = st.selectbox("触达阶段", ["全部", 1, 2, 3],
                                    format_func=lambda x: "全部" if x=="全部" else f"第{x}封")
    with tf3:
        show_high = st.checkbox("只看高效模板⭐")

    templates = get_templates(
        category=cat_filter if cat_filter != "全部" else None,
        touch_number=touch_filter if touch_filter != "全部" else None
    )
    if show_high:
        templates = [t for t in templates if t.get('is_high_performer')]

    if not templates:
        st.info("暂无模板，在写邮件时保存模板后会在这里显示")
    else:
        for tmpl in templates:
            perf_badge = "⭐ 高效" if tmpl.get('is_high_performer') else ""
            with st.expander(
                f"[第{tmpl.get('touch_number',1)}封][{tmpl.get('category','')}] "
                f"{tmpl.get('name','')} {perf_badge} | 使用{tmpl.get('use_count',0)}次 "
                f"| 回复率{tmpl.get('reply_rate',0):.0%}"
            ):
                st.markdown(f"**主题：** {tmpl.get('subject','')}")
                st.markdown(f"**正文：**")
                st.text(tmpl.get('body',''))
                if st.button("📋 使用此模板", key=f"use_tmpl_{tmpl['id']}"):
                    st.session_state['template_subject'] = tmpl['subject']
                    st.session_state['template_body'] = tmpl['body']
                    st.info("已加载到编辑器，请切换到「写邮件」标签")
