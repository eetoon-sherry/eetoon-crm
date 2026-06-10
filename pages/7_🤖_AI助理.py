"""AI Assistant — placeholder, ready for Claude API integration."""

import streamlit as st

st.set_page_config(page_title="AI助理 | EETOON CRM", page_icon="🤖", layout="wide")

if not st.session_state.get("authenticated"):
    st.warning("请先登录"); st.stop()

st.markdown("## 🤖 AI 助理")

try:
    api_key = st.secrets.get("anthropic", {}).get("api_key", "")
except Exception:
    api_key = ""

if not api_key:
    st.info("""
    **AI助理功能待接入**

    接入后你可以：
    - 💬 问"Gary Austin最近有什么动态？" → 自动从数据库拉取回答
    - 📨 投喂客户回复邮件 → AI解析后自动更新客户档案
    - 🌐 输入官网URL → 自动提取公司信息预填表单
    - 📊 问"下周应该优先跟进哪几家？" → 结合数据给建议

    **接入方法：**
    1. 在 [console.anthropic.com](https://console.anthropic.com) 注册并充值
    2. 生成 API Key（格式：`sk-ant-api03-...`）
    3. 在 Streamlit Cloud 的 Secrets 里填入：
    ```
    [anthropic]
    api_key = "sk-ant-api03-你的key"
    ```
    4. 重启应用，AI助理自动激活
    """)

    st.markdown("---")
    st.markdown("### 暂用方案：直接在这里和我对话")
    st.markdown("在你的API Key到位之前，可以把客户信息复制粘贴到这里，我来帮你分析和起草。")

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

    # Display chat history
    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])

    user_input = st.chat_input("粘贴客户信息、回复邮件、或提问...")
    if user_input:
        st.session_state.chat_history.append({"role": "user", "content": user_input})
        # In the future, this calls Claude API
        response = (
            "AI助理功能尚未接入API Key。\n\n"
            "请前往 console.anthropic.com 获取API Key后，在Streamlit Cloud的Secrets中配置。\n\n"
            "配置完成后，我可以直接回答你关于客户的任何问题，并自动更新系统数据。"
        )
        st.session_state.chat_history.append({"role": "assistant", "content": response})
        st.rerun()

else:
    # ── FULL AI ASSISTANT (when API key is available) ────────────────────────
    import anthropic
    from utils.database import get_all_leads, get_lead_by_email, update_lead_status, add_note, get_stats

    client = anthropic.Anthropic(api_key=api_key)

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

    col_chat, col_actions = st.columns([2, 1])

    with col_actions:
        st.markdown("#### ⚡ 快捷操作")

        # URL extraction
        st.markdown("**🌐 URL快速录入**")
        url_input = st.text_input("输入公司官网URL", placeholder="https://example.com")
        if st.button("提取公司信息") and url_input:
            from utils.web_search import extract_company_info
            with st.spinner("抓取中..."):
                info = extract_company_info(url_input)
            msg = f"我从 {url_input} 提取到以下信息，请帮我分析这家公司是否符合EETOON的目标客户画像，并整理为客户档案草稿：\n\n{info}"
            st.session_state.chat_history.append({"role": "user", "content": msg})

        st.markdown("---")
        # Quick queries
        st.markdown("**💡 快捷提问**")
        quick_questions = [
            "下周应该优先跟进哪几家？",
            "哪些客户的袋包信号最强？",
            "给我一个Gary Austin的跟进角度建议",
            "分析这8家客户的整体开发情况",
        ]
        for q in quick_questions:
            if st.button(q, use_container_width=True, key=f"qq_{q[:10]}"):
                st.session_state.chat_history.append({"role": "user", "content": q})
                st.rerun()

    with col_chat:
        st.markdown("#### 💬 AI对话")

        # System context
        leads_summary = get_stats()
        active_leads = get_all_leads()
        leads_context = "\n".join([
            f"- {l['company_name']} ({l.get('status','')}, 评分{l.get('score','')}, {l.get('location','')})"
            for l in active_leads[:20]
        ])

        system_prompt = f"""你是Sherry的B2B客户开发助理。Sherry来自EETOON GROUP，中国袋包制造商，BSCI认证，有GRS认证的RPET产品。目标客户是美国推广品分销商（5-50人）。

当前客户池概况：
总客户数: {leads_summary['total']} | 开发中: {leads_summary['active']} | 有回复: {leads_summary['replied']} | 冷静期: {leads_summary['cold']}

当前客户列表：
{leads_context}

请用中文回答，提供具体可行的建议。如果涉及某家具体客户，结合上方数据回答。"""

        # Display messages
        for msg in st.session_state.chat_history:
            with st.chat_message(msg["role"]):
                st.write(msg["content"])

        user_input = st.chat_input("输入问题，或粘贴客户回复邮件...")

        if user_input or (st.session_state.chat_history and
                          st.session_state.chat_history[-1]["role"] == "user" and
                          len(st.session_state.chat_history) > 0):

            if user_input:
                st.session_state.chat_history.append({"role": "user", "content": user_input})

            # Call Claude API
            messages = [{"role": m["role"], "content": m["content"]}
                       for m in st.session_state.chat_history]

            with st.chat_message("assistant"):
                with st.spinner("思考中..."):
                    response = client.messages.create(
                        model="claude-opus-4-5",
                        max_tokens=1000,
                        system=system_prompt,
                        messages=messages
                    )
                    reply = response.content[0].text
                    st.write(reply)

            st.session_state.chat_history.append({"role": "assistant", "content": reply})

            # Auto-detect status updates in reply
            if "有回复" in reply or "replied" in reply.lower():
                st.info("💡 检测到回复信号，请在客户档案中更新状态")
