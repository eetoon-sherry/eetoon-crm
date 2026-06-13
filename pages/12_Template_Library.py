"""Campaign-aware email template library."""

import pandas as pd
import streamlit as st

from utils.database import add_template, get_campaigns, get_templates_for_campaign


st.set_page_config(page_title="Template Library | EETOON CRM", layout="wide")

if not st.session_state.get("authenticated"):
    st.warning("请先登录")
    st.stop()

st.markdown("## Template Library")
st.caption("模板按 campaign、阶段和客户类型管理；发送数据积累后用于比较回复率。")

campaigns = get_campaigns()
campaign_options = [{"id": None, "campaign_name": "通用模板"}] + campaigns
selected_campaign = st.selectbox(
    "Campaign",
    campaign_options,
    format_func=lambda c: c.get("campaign_name", "Unknown"),
)

tab_list, tab_add = st.tabs(["模板列表", "新增模板"])

with tab_list:
    templates = get_templates_for_campaign(selected_campaign.get("id"))
    if not templates:
        st.info("暂无模板。")
    else:
        rows = []
        for t in templates:
            sent = t.get("sent_count") or t.get("use_count") or 0
            replies = t.get("reply_count") or 0
            positive = t.get("positive_reply_count") or 0
            rows.append({
                "ID": t.get("id"),
                "Campaign ID": t.get("campaign_id") or "通用",
                "分类": t.get("category"),
                "阶段": t.get("touch_number"),
                "客户类型": t.get("customer_type"),
                "启用": t.get("enabled"),
                "发送": sent,
                "回复率": f"{round(replies / sent * 100, 2)}%" if sent else "0%",
                "正向回复率": f"{round(positive / sent * 100, 2)}%" if sent else "0%",
                "主题": t.get("subject"),
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        for t in templates:
            with st.expander(f"#{t.get('id')} | {t.get('subject')}"):
                st.write(f"模板组：{t.get('template_group') or ''}")
                st.write(f"版本：{t.get('version') or 1}")
                st.write(f"启用：{t.get('enabled')}")
                st.text_area("正文", value=t.get("body") or "", height=180, disabled=True, key=f"template_body_{t.get('id')}")

with tab_add:
    with st.form("add_template"):
        category = st.selectbox("阶段分类", ["first", "day7", "day14", "day21", "reactivation"])
        touch_number = st.number_input("touch_number", min_value=1, max_value=4, value=1)
        customer_type = st.text_input("客户类型", value="promo distributor")
        template_group = st.text_input("模板组", value="us_promo_bag_demand")
        subject = st.text_input("主题", value="Bag options for client gifting")
        body = st.text_area("正文", height=220)
        hook = st.text_input("Hook / angle", value="seasonal gifting and trade-show bag demand")
        enabled = st.checkbox("启用", value=True)
        submitted = st.form_submit_button("保存模板", type="primary")

        if submitted:
            ok = add_template({
                "campaign_id": selected_campaign.get("id"),
                "category": category,
                "touch_number": int(touch_number),
                "customer_type": customer_type,
                "template_group": template_group,
                "subject": subject,
                "body": body,
                "hook": hook,
                "enabled": enabled,
                "version": 1,
            })
            if ok:
                st.success("模板已保存")
                st.rerun()
            else:
                st.error("保存失败。请检查数据库表结构。")
