"""Create and manage reusable outreach campaigns."""

import json

import pandas as pd
import streamlit as st

from utils.database import (
    DEFAULT_CAMPAIGN,
    add_campaign,
    get_campaigns,
    get_or_create_default_campaign,
    update_campaign,
)


st.set_page_config(page_title="Campaign Manager | EETOON CRM", layout="wide")

if not st.session_state.get("authenticated"):
    st.warning("请先登录")
    st.stop()


def _lines_to_list(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _as_list(value) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return _lines_to_list(value)
    return []


def _as_dict(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


st.markdown("## Campaign Manager")
st.caption("这里配置可复用 campaign，不把客户线写死在代码里。")

get_or_create_default_campaign()
campaigns = get_campaigns()

if campaigns:
    table_rows = []
    for c in campaigns:
        table_rows.append({
            "ID": c.get("id"),
            "Campaign": c.get("campaign_name"),
            "Segment": c.get("target_segment"),
            "Region": c.get("country_region"),
            "Daily limit": c.get("daily_send_limit"),
            "Status": c.get("status"),
        })
    st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)
else:
    st.warning("还没有 campaign。")

tab_create, tab_edit = st.tabs(["新建 Campaign", "编辑 Campaign"])

with tab_create:
    with st.form("create_campaign"):
        st.markdown("### 新建")
        name = st.text_input("campaign_name", value="Bag Brands - July Test")
        target_segment = st.text_input("target_segment", value="US bag brands and lifestyle product companies")
        country_region = st.text_input("country / region", value="United States")
        icp = st.text_area("ICP 描述", value=DEFAULT_CAMPAIGN["icp_description"], height=120)
        keywords = st.text_area("搜索关键词（每行一个）", value="\n".join(DEFAULT_CAMPAIGN["search_keywords"]), height=120)
        excludes = st.text_area("排除客户类型（每行一个）", value="\n".join(DEFAULT_CAMPAIGN["exclude_customer_types"]), height=100)
        titles = st.text_area("联系人职位（每行一个）", value="\n".join(DEFAULT_CAMPAIGN["contact_titles"]), height=100)
        angles = st.text_area("value angle（每行一个）", value="\n".join(DEFAULT_CAMPAIGN["value_angles"]), height=100)
        template_group = st.text_input("默认模板组", value="bag_brand_outreach")
        followup_days = st.text_input("followup_days", value="7,14,21")
        daily_limit = st.number_input("daily_send_limit", min_value=1, max_value=200, value=10)
        status = st.selectbox("status", ["draft", "active", "paused", "completed"], index=0)

        submitted = st.form_submit_button("创建 Campaign", type="primary")
        if submitted:
            campaign_id = add_campaign({
                "campaign_name": name,
                "target_segment": target_segment,
                "country_region": country_region,
                "icp_description": icp,
                "search_keywords": _lines_to_list(keywords),
                "exclude_customer_types": _lines_to_list(excludes),
                "contact_titles": _lines_to_list(titles),
                "value_angles": _lines_to_list(angles),
                "default_template_group": template_group,
                "followup_days": [int(x.strip()) for x in followup_days.split(",") if x.strip().isdigit()],
                "daily_send_limit": daily_limit,
                "status": status,
            })
            if campaign_id:
                st.success(f"已创建 campaign #{campaign_id}")
                st.rerun()
            else:
                st.error("创建失败。请到系统体检页检查数据库连接和表结构。")

with tab_edit:
    if not campaigns:
        st.info("暂无可编辑 campaign。")
    else:
        selected = st.selectbox(
            "选择 Campaign",
            campaigns,
            format_func=lambda c: f"{c.get('campaign_name')} ({c.get('status')})",
        )
        with st.form("edit_campaign"):
            st.markdown("### 编辑")
            name = st.text_input("campaign_name", value=selected.get("campaign_name", ""))
            target_segment = st.text_input("target_segment", value=selected.get("target_segment", ""))
            country_region = st.text_input("country / region", value=selected.get("country_region", ""))
            icp = st.text_area("ICP 描述", value=selected.get("icp_description", ""), height=120)
            keywords = st.text_area("搜索关键词（每行一个）", value="\n".join(_as_list(selected.get("search_keywords"))), height=120)
            excludes = st.text_area("排除客户类型（每行一个）", value="\n".join(_as_list(selected.get("exclude_customer_types"))), height=100)
            titles = st.text_area("联系人职位（每行一个）", value="\n".join(_as_list(selected.get("contact_titles"))), height=100)
            angles = st.text_area("value angle（每行一个）", value="\n".join(_as_list(selected.get("value_angles"))), height=100)
            rules = st.text_area("客户评分规则 JSON", value=json.dumps(_as_dict(selected.get("scoring_rules")), ensure_ascii=False, indent=2), height=160)
            template_group = st.text_input("默认模板组", value=selected.get("default_template_group") or "")
            followup_days = st.text_input("followup_days", value=",".join(str(x) for x in _as_list(selected.get("followup_days")) or [7, 14, 21]))
            daily_limit = st.number_input("daily_send_limit", min_value=1, max_value=200, value=int(selected.get("daily_send_limit") or 10))
            status = st.selectbox(
                "status",
                ["draft", "active", "paused", "completed"],
                index=["draft", "active", "paused", "completed"].index(selected.get("status") or "draft"),
            )

            saved = st.form_submit_button("保存修改", type="primary")
            if saved:
                try:
                    scoring_rules = json.loads(rules) if rules.strip() else {}
                except Exception:
                    scoring_rules = {}
                    st.warning("评分规则 JSON 无法解析，已保存为空对象。")
                ok = update_campaign(
                    selected["id"],
                    campaign_name=name,
                    target_segment=target_segment,
                    country_region=country_region,
                    icp_description=icp,
                    search_keywords=_lines_to_list(keywords),
                    exclude_customer_types=_lines_to_list(excludes),
                    contact_titles=_lines_to_list(titles),
                    scoring_rules=scoring_rules,
                    value_angles=_lines_to_list(angles),
                    default_template_group=template_group,
                    followup_days=[int(x.strip()) for x in followup_days.split(",") if x.strip().isdigit()],
                    daily_send_limit=daily_limit,
                    status=status,
                )
                if ok:
                    st.success("已保存")
                    st.rerun()
                else:
                    st.error("保存失败。请检查系统体检页。")
