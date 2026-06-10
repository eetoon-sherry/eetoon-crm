"""Client discovery — search, research, and add new leads."""

import streamlit as st
import json
from datetime import date
from utils.database import (get_discovery_queue, add_discovery_candidate,
                             add_lead, get_setting, update_lead)
from utils.web_search import search_companies, extract_company_info, guess_email_formats

st.set_page_config(page_title="客户搜索 | EETOON CRM", page_icon="🔍", layout="wide")

if not st.session_state.get("authenticated"):
    st.warning("请先登录"); st.stop()

st.markdown("## 🔍 客户搜索与开发")

tab_search, tab_pending, tab_auto = st.tabs(["🔎 手动搜索", "📋 待审核候选", "🤖 自动补充设置"])

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


with tab_search:
    st.markdown("#### 搜索新目标公司")

    col_k, col_s, col_c = st.columns([2, 1, 1])
    with col_k:
        keyword = st.selectbox("搜索关键词", PROMO_KEYWORDS + ["自定义..."])
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
                        add_discovery_candidate(candidate)
                        st.success("✅ 已添加到待审核列表")


with tab_pending:
    st.markdown("#### 📋 待审核候选公司")
    candidates = get_discovery_queue('pending_review')

    if not candidates:
        st.info("暂无待审核候选，搜索后添加的公司会在这里显示")
    else:
        st.markdown(f"**共 {len(candidates)} 家待审核**")
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
                            # Add to leads table
                            lead_data = {
                                'company_name': cand.get('company_name',''),
                                'contact_name': owner_name,
                                'email': email,
                                'website': cand.get('website',''),
                                'location': cand.get('location',''),
                                'company_size': size,
                                'status': '新建',
                                'bag_signal_strength': '',
                            }
                            result = add_lead(lead_data)
                            if result:
                                # Update discovery queue status
                                from utils.database import get_conn
                                conn = get_conn()
                                cur = conn.cursor()
                                cur.execute("UPDATE discovery_queue SET status='approved' WHERE id=%s", (cand['id'],))
                                conn.commit(); cur.close(); conn.close()
                                st.success(f"✅ 已添加 {cand.get('company_name','')} 到客户池！")
                                st.rerun()
                            else:
                                st.error("邮件地址已存在或添加失败")

                        if rejected:
                            from utils.database import get_conn
                            conn = get_conn()
                            cur = conn.cursor()
                            cur.execute("UPDATE discovery_queue SET status='rejected' WHERE id=%s", (cand['id'],))
                            conn.commit(); cur.close(); conn.close()
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
