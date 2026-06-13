"""Human approval queue for candidates, contacts, emails, followups, and replies."""

import json

import streamlit as st

from utils.database import (
    approve_candidate_review,
    get_campaigns,
    get_lead,
    get_review_queue,
    update_review_item,
)
from utils.email_sender import queue_email, validate_content


st.set_page_config(page_title="Review Queue | EETOON CRM", layout="wide")

if not st.session_state.get("authenticated"):
    st.warning("请先登录")
    st.stop()


def _payload(item) -> dict:
    payload = item.get("payload") or {}
    if isinstance(payload, str):
        try:
            return json.loads(payload)
        except Exception:
            return {}
    return payload


def _state_from_location(location: str) -> str:
    text = (location or "").replace(",", " ").split()
    for part in text:
        clean = part.strip().upper()
        if len(clean) == 2 and clean.isalpha():
            return clean
    return "NY"


def _draft_first_email(lead: dict) -> tuple[str, str]:
    company = lead.get("company_name") or "your team"
    contact = lead.get("contact_name") or "there"
    subject = "Bag options for client gifting"
    body = (
        f"Hi {contact},\n\n"
        f"I noticed {company} works in promotional products and client gifting. "
        "EETOON develops custom tote bags, cooler bags, backpacks, and RPET bag options "
        "for distributors that need reliable factory support behind seasonal programs.\n\n"
        "Would it be useful if I sent a short bag style list for upcoming gifting or trade-show projects?"
    )
    return subject, body


st.markdown("## Review Queue")
st.caption("所有需要人工确认的动作集中在这里。未批准的邮件不会被自动发送。")

campaigns = get_campaigns()
campaign_options = [{"id": None, "campaign_name": "全部 Campaign"}] + campaigns
selected_campaign = st.selectbox(
    "Campaign",
    campaign_options,
    format_func=lambda c: c.get("campaign_name", "Unknown"),
)
campaign_id = selected_campaign.get("id")

item_type = st.selectbox(
    "类型",
    [
        ("all", "全部"),
        ("candidate_company", "候选公司"),
        ("first_email", "首封开发信"),
        ("followup_email", "跟进信"),
        ("reply", "客户回复"),
    ],
    format_func=lambda item: item[1],
)
type_filter = None if item_type[0] == "all" else item_type[0]

items = get_review_queue("pending", item_type=type_filter, campaign_id=campaign_id)

if not items:
    st.info("当前没有待审核项目。")
    st.stop()

st.markdown(f"待审核：**{len(items)}** 项")

for item in items:
    payload = _payload(item)
    label = f"#{item.get('id')} | {item.get('item_type')} | {item.get('title')}"
    with st.expander(label, expanded=item.get("priority") == 1):
        st.caption(item.get("campaign_name") or "")
        if item.get("summary"):
            st.write(item.get("summary"))
        if item.get("recommendation"):
            st.info(item.get("recommendation"))

        if item.get("item_type") == "candidate_company":
            col_info, col_action = st.columns([2, 1])
            with col_info:
                st.write(f"公司：{payload.get('company_name', '')}")
                st.write(f"官网：{payload.get('website', '')}")
                st.write(f"地区：{payload.get('location', '')}")
                st.write(f"邮箱：{payload.get('email', '') or '未确认'}")
                st.write(f"评分：{payload.get('score_grade', 'C')} / {payload.get('score', 0)}")
                reason = payload.get("score_reason", {})
                if isinstance(reason, str):
                    try:
                        reason = json.loads(reason)
                    except Exception:
                        reason = {}
                st.write("评分依据：" + ", ".join(reason.get("reasons", [])))
            with col_action:
                with st.form(f"candidate_{item['id']}"):
                    contact = st.text_input("联系人", value=payload.get("contact_name") or payload.get("owner_name") or "")
                    email = st.text_input("邮箱", value=payload.get("email", ""))
                    size = st.text_input("公司规模", value=payload.get("company_size", ""))
                    approve = st.form_submit_button("通过，进入开发流程", type="primary")
                    need_info = st.form_submit_button("需要补充信息")
                    later = st.form_submit_button("稍后看")
                    reject = st.form_submit_button("放弃")

                    if approve:
                        if not email:
                            st.error("进入开发流程前至少需要可用邮箱。")
                        else:
                            lead_id = approve_candidate_review(item["id"], contact, email, size)
                            if lead_id:
                                st.success(f"已创建客户 #{lead_id}，并生成首封开发信审核任务。")
                                st.rerun()
                            else:
                                st.error("创建客户失败。可能是邮箱重复或数据库未连接。")
                    if need_info:
                        update_review_item(item["id"], "needs_info")
                        st.rerun()
                    if later:
                        update_review_item(item["id"], "later")
                        st.rerun()
                    if reject:
                        update_review_item(item["id"], "rejected")
                        st.rerun()

        elif item.get("item_type") in {"first_email", "followup_email"}:
            lead_id = item.get("item_id") or payload.get("lead_id")
            lead = get_lead(lead_id) if lead_id else None
            if not lead:
                st.error("找不到对应客户，无法进入发送队列。")
                if st.button("标记为失败", key=f"missing_lead_{item['id']}"):
                    update_review_item(item["id"], "failed")
                    st.rerun()
                continue

            default_subject, default_body = _draft_first_email(lead)
            subject = payload.get("subject") or default_subject
            body = payload.get("body") or default_body
            col_edit, col_meta = st.columns([2, 1])
            with col_edit:
                edited_subject = st.text_input("主题", value=subject, key=f"subject_{item['id']}")
                edited_body = st.text_area("正文", value=body, height=220, key=f"body_{item['id']}")
                errors = validate_content(edited_subject, edited_body)
                if errors:
                    st.warning("；".join(errors))
            with col_meta:
                st.write(f"公司：{lead.get('company_name', '')}")
                st.write(f"联系人：{lead.get('contact_name', '')}")
                st.write(f"邮箱：{lead.get('email', '')}")
                st.write(f"地区：{lead.get('location', '')}")
                st.write(f"当前触达次数：{lead.get('touch_count') or 0}")

                approve_send = st.button("批准发送", type="primary", key=f"approve_email_{item['id']}")
                rewrite = st.button("换角度重写", key=f"rewrite_{item['id']}")
                pause = st.button("暂不开发", key=f"pause_email_{item['id']}")

                if approve_send:
                    if errors:
                        st.error("请先修正主题或正文限制。")
                    elif not lead.get("email"):
                        st.error("客户没有邮箱，不能发送。")
                    else:
                        state = _state_from_location(lead.get("location", ""))
                        job = queue_email(
                            lead["id"],
                            lead.get("company_name", ""),
                            lead.get("email", ""),
                            lead.get("contact_name", ""),
                            edited_subject,
                            edited_body,
                            state,
                            campaign_id=item.get("campaign_id"),
                            touch_number=(lead.get("touch_count") or 0) + 1,
                            requires_approval=False,
                        )
                        update_review_item(item["id"], "approved", {
                            "subject": edited_subject,
                            "body": edited_body,
                            "queue_id": job.get("queue_id"),
                        })
                        st.success(f"已批准并进入发送队列：{job.get('scheduled_local')}")
                        st.rerun()
                if rewrite:
                    update_review_item(item["id"], "needs_rewrite", {"subject": edited_subject, "body": edited_body})
                    st.rerun()
                if pause:
                    update_review_item(item["id"], "paused")
                    st.rerun()

        elif item.get("item_type") == "reply":
            st.write(payload.get("body") or payload)
            col1, col2, col3 = st.columns(3)
            if col1.button("确认：有回复", key=f"reply_ok_{item['id']}"):
                update_review_item(item["id"], "approved", {"decision": "replied"})
                st.rerun()
            if col2.button("确认：无意向", key=f"reply_no_{item['id']}"):
                update_review_item(item["id"], "approved", {"decision": "no_interest"})
                st.rerun()
            if col3.button("需要人工判断", key=f"reply_manual_{item['id']}"):
                update_review_item(item["id"], "needs_info")
                st.rerun()

        else:
            st.json(payload)
            if st.button("标记完成", key=f"done_{item['id']}"):
                update_review_item(item["id"], "approved")
                st.rerun()
