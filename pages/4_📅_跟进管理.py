"""Follow-up management — calendar view, draft generation, date adjustment."""

import streamlit as st
from datetime import date, timedelta
from utils.database import (get_due_followups, get_all_leads, update_lead,
                             get_setting, get_reactivation_due)
from utils.email_sender import validate_content
from utils.timezone import beijing_today

st.set_page_config(page_title="跟进管理 | EETOON CRM", page_icon="📅", layout="wide")

if not st.session_state.get("authenticated"):
    st.warning("请先登录"); st.stop()

st.markdown("## 📅 跟进管理")
today_cn = beijing_today()

tab1, tab2, tab3 = st.tabs(["📋 到期跟进", "📆 日历视图", "❄️ 冷静期激活"])

FOLLOWUP_ANGLES = {
    1: [
        "引用对方一篇近期博文或LinkedIn帖子，切其内容里提到的具体业务痛点",
        "提一个行业数字（ASI数据：每个tote bag年均5700次品牌曝光），拉近采购决策依据",
        "问一个具体问题：'Q3有没有礼品季的备货计划？'",
        "提共同客户类型：'我们有服务过几家DFW本地活动公司的案例…'",
        "切他社媒近期话题换一个角度"
    ],
    2: [
        "分享一个具体案例（同类分销商如何用RPET帮客户满足ESG采购审核）",
        "切即将到来的美国节日/活动季：'Q4礼品采购通常10月锁定，现在打样刚好'",
        "提交期保障：'我们10周时间轴是含打样的，可以给一个具体的交付节点'",
        "换CTA资源：如果上封发了Gifting Occasions，这封改发RPET指南"
    ],
    3: [
        "最后一次触达：提供一个具体数字或参数让对方有理由回复（'当前MOQ是500件'）",
        "软告别：'如果时机不合适完全理解，随时欢迎联系'，留好印象",
        "转换渠道建议：这封不回就考虑LinkedIn私信"
    ]
}

CTA_RESOURCES = [
    "Bag Styles for Various Gifting Occasions",
    "RPET+GRS认证指南",
    "袋包规格清单",
    "10周定制订单时间轴"
]

def get_next_send_day(from_date: date) -> date:
    send_days = get_setting("send_days", ["Tuesday","Wednesday","Thursday"])
    day_map = {"Monday":0,"Tuesday":1,"Wednesday":2,"Thursday":3,
               "Friday":4,"Saturday":5,"Sunday":6}
    allowed = [day_map[d] for d in send_days if d in day_map]
    for i in range(0, 7):
        candidate = from_date + timedelta(days=i)
        if candidate.weekday() in allowed:
            return candidate
    return from_date


# ── TAB 1: DUE FOLLOWUPS ─────────────────────────────────────────────────────
with tab1:
    due = get_due_followups()
    if not due:
        st.success("✅ 今日没有到期的跟进任务")
    else:
        st.warning(f"📋 **{len(due)} 家客户需要跟进**")

        for lead in due:
            touch = lead.get('touch_count', 1)
            next_touch = touch + 1 if touch < 3 else 3
            angles = FOLLOWUP_ANGLES.get(touch, FOLLOWUP_ANGLES[1])

            with st.expander(
                f"📌 {lead['company_name']} | {lead.get('contact_name','')} "
                f"| 第{next_touch}封跟进 | 评分{lead.get('score_grade','C')}({lead.get('score',0)})",
                expanded=True
            ):
                col_info, col_draft = st.columns([1, 1])

                with col_info:
                    st.markdown("**基本信息**")
                    st.markdown(f"📧 `{lead.get('email','')}`")
                    st.markdown(f"📍 {lead.get('location','')}")
                    st.markdown(f"✉️ 上封主题：_{lead.get('last_subject','—')}_")
                    st.markdown("---")
                    st.markdown("**推荐角度**")
                    if lead.get('hook_direction'):
                        st.info(f"原始Hook方向：{lead.get('hook_direction','')}")
                    st.markdown("**新角度建议（选一个）：**")
                    for i, angle in enumerate(angles[:3]):
                        st.markdown(f"{i+1}. {angle}")

                with col_draft:
                    st.markdown("**生成跟进草稿**")
                    selected_angle = st.selectbox(
                        "选择角度", angles,
                        key=f"angle_{lead['id']}"
                    )
                    selected_cta = st.selectbox(
                        "CTA资源", CTA_RESOURCES,
                        index=CTA_RESOURCES.index(lead.get('recommended_cta', CTA_RESOURCES[0]))
                        if lead.get('recommended_cta') in CTA_RESOURCES else 0,
                        key=f"cta_{lead['id']}"
                    )

                    contact = lead.get('contact_name','').split()[0] if lead.get('contact_name') else 'there'
                    draft_subject = f"Following up — {selected_cta[:25]}"
                    draft_body = (
                        f"Hi {contact},\n\n"
                        f"{selected_angle}\n\n"
                        f"I'm Sherry from EETOON — we run our own BSCI-certified bag production line "
                        f"in China, with GRS-certified RPET options for clients with ESG requirements.\n\n"
                        f"Happy to share our {selected_cta} if it's useful for your current sourcing.\n\n"
                        f"Sherry"
                    )

                    with st.form(key=f"followup_form_{lead['id']}"):
                        subject_edit = st.text_input(
                            f"主题行（≤50字符，当前{len(draft_subject)}）",
                            value=draft_subject
                        )
                        body_edit = st.text_area(
                            f"正文（≤120词，当前{len(draft_body.split())}词）",
                            value=draft_body, height=200
                        )
                        errors = validate_content(subject_edit, body_edit)
                        if errors:
                            for err in errors:
                                st.error(f"❌ {err}")

                        col_sub1, col_sub2 = st.columns(2)
                        with col_sub1:
                            submitted = st.form_submit_button("📬 提交审核", type="primary",
                                                              disabled=bool(errors))
                        with col_sub2:
                            adjust_date = st.form_submit_button("📅 调整跟进日期")

                        if submitted and not errors:
                            from utils.email_sender import queue_email
                            state = lead.get('location','TX').split('/')[-1].split(',')[-1].strip()[-2:]
                            state = state if state.isupper() and len(state)==2 else 'TX'
                            job = queue_email(
                                lead['id'], lead['company_name'],
                                lead['email'], lead.get('contact_name',''),
                                subject_edit, body_edit, state
                            )
                            st.success(f"已提交到队列，需在 Review Queue 批准后才会发送。预定时间：{job['scheduled_local']}")

                # Adjust dates outside form
                with st.expander("📅 调整跟进日期"):
                    adj1, adj2, adj3 = st.columns(3)
                    with adj1:
                        new_d7 = st.date_input("Day7", value=lead.get('day7_date') or today_cn,
                                               key=f"adj7_{lead['id']}")
                    with adj2:
                        new_d14 = st.date_input("Day14", value=lead.get('day14_date') or today_cn,
                                                key=f"adj14_{lead['id']}")
                    with adj3:
                        new_d21 = st.date_input("Day21", value=lead.get('day21_date') or today_cn,
                                                key=f"adj21_{lead['id']}")
                    if st.button("保存日期", key=f"save_dates_{lead['id']}"):
                        update_lead(lead['id'], day7_date=new_d7, day14_date=new_d14, day21_date=new_d21)
                        st.success("✅ 日期已更新")
                        st.rerun()


# ── TAB 2: CALENDAR VIEW ──────────────────────────────────────────────────────
with tab2:
    st.markdown("#### 📆 未来30天跟进日历")
    all_leads = get_all_leads()
    today = today_cn
    calendar_data = {}

    for lead in all_leads:
        if lead.get('status') in ['有回复','无意向','退信','冷静期-90天后重新激活']:
            continue
        for field, label in [('day7_date','D7'),('day14_date','D14'),('day21_date','D21')]:
            d = lead.get(field)
            if d and isinstance(d, date) and today <= d <= today + timedelta(days=30):
                if d not in calendar_data:
                    calendar_data[d] = []
                calendar_data[d].append(f"{lead['company_name']}({label})")

    if not calendar_data:
        st.info("未来30天内没有到期跟进")
    else:
        for d in sorted(calendar_data.keys()):
            days_until = (d - today).days
            if days_until == 0:
                label = "🔴 **今天**"
            elif days_until <= 3:
                label = f"🟠 **{d}** ({days_until}天后)"
            else:
                label = f"🟢 {d} ({days_until}天后)"

            st.markdown(f"{label}")
            for item in calendar_data[d]:
                st.markdown(f"  • {item}")


# ── TAB 3: REACTIVATION ───────────────────────────────────────────────────────
with tab3:
    st.markdown("#### ❄️ 冷静期到期客户")
    reactivation = get_reactivation_due()

    if not reactivation:
        st.success("✅ 暂无冷静期到期客户")
        st.caption("当前冷静期客户（激活日期未到）：")
        cold_leads = [l for l in get_all_leads() if l.get('status') == '冷静期-90天后重新激活']
        for l in cold_leads:
            days_left = (l.get('reactivation_date') - today_cn).days if l.get('reactivation_date') else '?'
            st.markdown(f"• {l['company_name']} | 还剩 {days_left} 天 | 激活日期：{l.get('reactivation_date','—')}")
    else:
        st.warning(f"🔔 **{len(reactivation)} 家客户冷静期已到，建议重新激活**")
        for lead in reactivation:
            with st.expander(f"❄️ {lead['company_name']} | {lead.get('contact_name','')} | 激活日：{lead.get('reactivation_date','')}"):
                st.markdown(f"**原始备注：** {lead.get('notes','—')}")
                st.markdown(f"**原Hook方向：** {lead.get('hook_direction','—')}")
                st.markdown(f"**上次主题：** {lead.get('last_subject','—')}")

                col_a, col_b = st.columns(2)
                with col_a:
                    if st.button(f"✅ 重新激活并进入开发流程", key=f"reactivate_{lead['id']}"):
                        update_lead(lead['id'], status='新建', touch_count=0,
                                   reactivation_date=None)
                        st.success("已重置为新建状态，请前往邮件编辑器生成新一轮首封信")
                        st.rerun()
                with col_b:
                    if st.button(f"🗑️ 放弃此客户", key=f"abandon_{lead['id']}"):
                        update_lead(lead['id'], status='无意向')
                        st.info("已标记为无意向")
                        st.rerun()
