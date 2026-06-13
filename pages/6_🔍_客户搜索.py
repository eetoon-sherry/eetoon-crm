"""Client discovery — search, research, and add new leads."""

import streamlit as st
import json
import pandas as pd
from datetime import date
from utils.database import (
    add_discovery_candidate_for_campaign,
    approve_candidate_review,
    get_campaigns,
    get_discovery_queue,
    get_or_create_default_campaign,
    get_review_queue,
    get_setting,
    score_candidate,
    update_discovery_status,
    update_review_item,
)
from utils.web_search import search_companies, extract_company_info, guess_email_formats

st.set_page_config(page_title="客户搜索 | EETOON CRM", page_icon="🔍", layout="wide")

if not st.session_state.get("authenticated"):
    st.warning("请先登录"); st.stop()

st.markdown("## 🔍 客户搜索与开发")

get_or_create_default_campaign()
campaigns = get_campaigns()
if not campaigns:
    st.warning("当前没有可用 Campaign。请先到系统体检确认 Supabase 连接，或到 Campaign Manager 创建 campaign。")
    st.stop()
selected_campaign = st.selectbox(
    "当前 Campaign",
    campaigns,
    format_func=lambda c: c.get("campaign_name", "Unknown"),
)
campaign_id = selected_campaign.get("id")

tab_import, tab_search, tab_pending, tab_auto = st.tabs(["CSV导入", "🔎 手动搜索", "📋 待审核候选", "🤖 自动补充设置"])

PROMO_KEYWORDS = [
    "promotional products distributor",
    "branded merchandise distributor",
    "advertising specialty distributor",
    "custom swag company",
    "corporate gifting company"
]

US_STATES = [
    "TX - Texas", "FL - Florida", "CA - California", "IL - Illinois",
    "NY - New York", "OH - Ohio", "CO - Colorado", "TN - Tennessee",
    "WA - Washington", "GA - Georgia", "NC - North Carolina", "AZ - Arizona",
    "PA - Pennsylvania", "MI - Michigan", "MN - Minnesota", "VA - Virginia",
    "OR - Oregon", "NV - Nevada", "MA - Massachusetts", "WI - Wisconsin"
]

US_CITIES = {
    "TX - Texas": ["Houston", "Dallas", "Austin", "San Antonio", "Fort Worth", "Plano"],
    "FL - Florida": ["Miami", "Tampa", "Orlando", "Jacksonville", "Palm Harbor", "Fort Lauderdale"],
    "CA - California": ["Los Angeles", "San Francisco", "San Diego", "Sacramento", "Orange County"],
    "IL - Illinois": ["Chicago", "Naperville", "Schaumburg", "Rockford"],
    "CO - Colorado": ["Denver", "Boulder", "Colorado Springs", "Fort Collins"],
    "NY - New York": ["New York City", "Buffalo", "Albany", "Rochester"],
    "GA - Georgia": ["Atlanta", "Savannah", "Augusta"],
    "NC - North Carolina": ["Charlotte", "Raleigh", "Durham"],
}


with tab_import:
    st.markdown("#### CSV 导入候选客户")
    st.caption("建议列名：company_name, website, location, email, contact_name, description, snippet")
    uploaded = st.file_uploader("上传 CSV", type=["csv"])
    if uploaded:
        df = pd.read_csv(uploaded)
        st.dataframe(df.head(50), use_container_width=True)
        if st.button("导入并自动评分", type="primary"):
            imported = 0
            for _, row in df.iterrows():
                raw = row.to_dict()
                candidate = {
                    "company_name": raw.get("company_name") or raw.get("company") or raw.get("name") or "",
                    "website": raw.get("website") or raw.get("url") or "",
                    "location": raw.get("location") or raw.get("city") or "",
                    "email": raw.get("email") or "",
                    "contact_name": raw.get("contact_name") or raw.get("owner_name") or "",
                    "description": raw.get("description") or "",
                    "snippet": raw.get("snippet") or "",
                    "research_brief": json.dumps({
                        "description": raw.get("description") or "",
                        "snippet": raw.get("snippet") or "",
                    }, ensure_ascii=False),
                    "source": "csv_import",
                    "status": "pending_review",
                }
                if candidate["company_name"] or candidate["website"]:
                    if add_discovery_candidate_for_campaign(candidate, campaign_id):
                        imported += 1
            st.success(f"已导入 {imported} 个候选，并进入 Review Queue。")

    st.markdown("#### 手动输入官网背调")
    with st.form("manual_website_research"):
        website = st.text_input("公司官网 URL", placeholder="https://example.com")
        company_name = st.text_input("公司名（可选）")
        submitted = st.form_submit_button("抓取并加入候选池", type="primary")
        if submitted:
            with st.spinner("正在抓取官网信息..."):
                extra = extract_company_info(website)
            candidate = {
                "company_name": company_name or extra.get("company_name", ""),
                "website": website,
                "location": extra.get("location", "United States"),
                "email": extra.get("email", ""),
                "description": extra.get("description", ""),
                "research_brief": json.dumps(extra, ensure_ascii=False),
                "source": "manual_website",
                "status": "pending_review",
            }
            scored = score_candidate(candidate, selected_campaign)
            ok = add_discovery_candidate_for_campaign(candidate, campaign_id)
            if ok:
                st.success(f"已加入候选池：{scored['score_grade']}级 / {scored['score']}分")
            else:
                st.error("添加失败。请检查数据库连接。")


with tab_search:
    st.markdown("#### 搜索新目标公司")

    col_k, col_s, col_c = st.columns([2, 1, 1])
    with col_k:
        campaign_keywords = selected_campaign.get("search_keywords") or []
        if isinstance(campaign_keywords, str):
            try:
                campaign_keywords = json.loads(campaign_keywords)
            except Exception:
                campaign_keywords = []
        keyword_pool = list(dict.fromkeys(campaign_keywords + PROMO_KEYWORDS))
        keyword = st.selectbox("搜索关键词", keyword_pool + ["自定义..."])
        if keyword == "自定义...":
            keyword = st.text_input("输入自定义关键词")
    with col_s:
        state = st.selectbox("目标州", US_STATES)
        state_abbr = state.split(' - ')[0]
    with col_c:
        state_full = state.split(' - ')[1] if ' - ' in state else state
        city_options = US_CITIES.get(state, [state_full])
        city = st.selectbox("城市（可选）", ["不限"] + city_options)

    search_query = f"{keyword} {city if city != '不限' else state_full}"
    st.markdown(f"**搜索词预览：** `{search_query}`")

    col_btn, col_n = st.columns([1, 2])
    with col_btn:
        do_search = st.button("🔍 开始搜索", type="primary", use_container_width=True)
    with col_n:
        max_r = st.slider("最多返回结果数", 5, 20, 10)

    if do_search:
        with st.spinner(f"正在搜索：{search_query}..."):
            results = search_companies(search_query, location=f"{city} {state_full}", max_results=max_r)

        if not results:
            st.warning("未找到结果，请尝试不同关键词或城市")
        else:
            st.success(f"找到 {len(results)} 家候选公司")
            st.session_state['search_results'] = results

    if 'search_results' in st.session_state:
        results = st.session_state['search_results']
        st.markdown("---")
        st.markdown("#### 搜索结果 — 选择要添加的公司")

        for i, r in enumerate(results):
            with st.expander(f"🏢 {r.get('company_name','未知')} — {r.get('website','')}", expanded=False):
                col_info, col_action = st.columns([2, 1])
                with col_info:
                    st.markdown(f"**官网：** {r.get('website','')}")
                    st.markdown(f"**摘要：** {r.get('snippet','')[:200]}")

                with col_action:
                    if st.button(f"➕ 添加到候选池", key=f"add_candidate_{i}"):
                        # Try to extract more info
                        with st.spinner("正在抓取官网信息..."):
                            extra = extract_company_info(r.get('website',''))

                        candidate = {
                            'company_name': r.get('company_name', extra.get('company_name','')),
                            'website': r.get('website',''),
                            'location': f"{city}, {state_abbr}",
                            'email': extra.get('email',''),
                            'research_brief': json.dumps({'snippet': r.get('snippet',''), 'description': extra.get('description','')}),
                            'status': 'pending_review',
                            'source': 'manual_search'
                        }
                        add_discovery_candidate_for_campaign(candidate, campaign_id)
                        st.success("✅ 已添加到待审核列表")


with tab_pending:
    st.markdown("#### 📋 待审核候选公司")
    review_candidates = get_review_queue("pending", item_type="candidate_company", campaign_id=campaign_id)
    candidates = get_discovery_queue('pending_review')

    if not review_candidates and not candidates:
        st.info("暂无待审核候选，搜索后添加的公司会在这里显示")
    else:
        st.markdown(f"**Review Queue 候选：{len(review_candidates)} 个**")
        st.info("建议到 Review Queue 页面集中审核；这里保留旧候选池兼容视图。")

        for item in review_candidates:
            payload = item.get("payload") or {}
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except Exception:
                    payload = {}
            with st.expander(f"{payload.get('score_grade','C')}级 / {payload.get('score',0)}分 | {payload.get('company_name','')}"):
                st.write(f"官网：{payload.get('website','')}")
                st.write(f"地区：{payload.get('location','')}")
                st.write(f"邮箱：{payload.get('email','未确认')}")
                reason = payload.get("score_reason", {})
                if isinstance(reason, str):
                    try:
                        reason = json.loads(reason)
                    except Exception:
                        reason = {}
                st.write("评分依据：" + ", ".join(reason.get("reasons", [])))
                col1, col2, col3, col4 = st.columns(4)
                if col1.button("通过", key=f"rq_approve_{item['id']}"):
                    if not payload.get("email"):
                        st.error("缺邮箱，先补邮箱再通过。")
                    else:
                        lead_id = approve_candidate_review(item["id"], payload.get("contact_name", ""), payload.get("email", ""), payload.get("company_size", ""))
                        if lead_id:
                            st.success("已进入开发流程")
                            st.rerun()
                if col2.button("放弃", key=f"rq_reject_{item['id']}"):
                    update_review_item(item["id"], "rejected")
                    st.rerun()
                if col3.button("稍后看", key=f"rq_later_{item['id']}"):
                    update_review_item(item["id"], "later")
                    st.rerun()
                if col4.button("需补信息", key=f"rq_info_{item['id']}"):
                    update_review_item(item["id"], "needs_info")
                    st.rerun()

        st.markdown("---")
        st.markdown("#### 旧候选池")
        for cand in candidates:
            brief = cand.get('research_brief', {})
            if isinstance(brief, str):
                try: brief = json.loads(brief)
                except: brief = {}

            with st.expander(f"🏢 {cand.get('company_name','')} | {cand.get('location','')} | {cand.get('website','')}"):
                col_a, col_b = st.columns([2, 1])
                with col_a:
                    st.markdown(f"**官网：** {cand.get('website','')}")
                    st.markdown(f"**邮件：** {cand.get('email','未找到')}")
                    if brief.get('description'):
                        st.markdown(f"**官网描述：** {brief.get('description','')[:200]}")
                    if brief.get('snippet'):
                        st.markdown(f"**搜索摘要：** {brief.get('snippet','')[:200]}")

                    # Email guessing
                    domain = cand.get('website','').replace('https://','').replace('http://','').split('/')[0]
                    contact = cand.get('owner_name','')
                    if not cand.get('email') and domain:
                        guessed = guess_email_formats(contact, domain)
                        if guessed:
                            st.markdown("**推测邮件格式：**")
                            for g in guessed[:3]:
                                st.markdown(f"• `{g}`")

                with col_b:
                    # Manual fill before approval
                    with st.form(key=f"approve_{cand['id']}"):
                        st.markdown("**补充信息后审核**")
                        owner_name = st.text_input("联系人姓名", value=cand.get('owner_name',''))
                        email = st.text_input("邮件地址", value=cand.get('email',''))
                        size = st.text_input("公司规模（人数）", "")
                        approved = st.form_submit_button("✅ 确认开发", type="primary")
                        rejected = st.form_submit_button("❌ 排除")

                        if approved:
                            candidate = dict(cand)
                            candidate["contact_name"] = owner_name
                            candidate["email"] = email
                            candidate["company_size"] = size
                            ok = add_discovery_candidate_for_campaign(candidate, campaign_id)
                            if ok:
                                update_discovery_status(cand['id'], 'migrated_to_review_queue')
                                st.success("已送入 Review Queue，请在那里批准进入开发流程。")
                                st.rerun()
                            else:
                                st.error("迁移失败")

                        if rejected:
                            update_discovery_status(cand['id'], 'rejected')
                            st.info("已排除")
                            st.rerun()


with tab_auto:
    st.markdown("#### 🤖 自动定期搜索设置")
    st.info("自动搜索通过GitHub Actions每周一运行，搜索结果自动进入「待审核候选」列表，不会自动发邮件。")

    auto_enabled = get_setting("auto_discovery_enabled", True)
    keywords = get_setting("discovery_keywords", [])
    states = get_setting("discovery_states", [])

    col_1, col_2 = st.columns(2)
    with col_1:
        st.markdown("**当前自动搜索关键词：**")
        for kw in keywords:
            st.markdown(f"• {kw}")
    with col_2:
        st.markdown("**当前目标州：**")
        st.markdown(", ".join(states) if states else "未设置")

    st.markdown("---")
    st.markdown("修改自动搜索设置请前往 **⚙️ 设置** 页面")
