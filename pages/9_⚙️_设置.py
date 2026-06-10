"""Settings page — fully customizable system configuration."""

import streamlit as st
import json
from utils.database import get_setting, set_setting

st.set_page_config(page_title="系统设置 | EETOON CRM", page_icon="⚙️", layout="wide")

if not st.session_state.get("authenticated"):
    st.warning("请先登录"); st.stop()

st.markdown("## ⚙️ 系统设置")
st.info("所有设置修改后立即生效，无需重启应用。")

tab1, tab2, tab3, tab4, tab5 = st.tabs(["🎨 状态与颜色", "✉️ 邮件规则", "⏰ 跟进节奏", "🔍 自动搜索", "🔑 账号与签名"])

# ── TAB 1: STATUS & COLORS ────────────────────────────────────────────────────
with tab1:
    st.markdown("#### 🎨 客户状态标签与颜色")
    st.markdown("所有状态标签、颜色均可自由编辑。修改后仪表盘、档案等页面同步更新。")

    statuses = get_setting("statuses", [
        {"label": "新建", "color": "#9E9E9E"},
        {"label": "已发送第1封", "color": "#2196F3"},
        {"label": "有回复", "color": "#4CAF50"},
        {"label": "冷静期-90天后重新激活", "color": "#607D8B"},
    ])

    st.markdown("**当前状态配置：**（可直接编辑JSON保存）")
    statuses_json = st.text_area(
        "状态配置（JSON格式，每条包含 label 和 color）",
        value=json.dumps(statuses, ensure_ascii=False, indent=2),
        height=300
    )

    # Live preview
    st.markdown("**预览：**")
    try:
        preview_statuses = json.loads(statuses_json)
        cols = st.columns(min(len(preview_statuses), 4))
        for i, s in enumerate(preview_statuses):
            with cols[i % 4]:
                st.markdown(
                    f"<div style='background:{s.get('color','#999')}22;"
                    f"color:{s.get('color','#999')};padding:6px 12px;"
                    f"border-radius:20px;font-weight:600;font-size:13px;"
                    f"margin:4px 0;text-align:center'>{s.get('label','')}</div>",
                    unsafe_allow_html=True
                )
        if st.button("💾 保存状态设置", type="primary"):
            set_setting("statuses", preview_statuses)
            st.success("✅ 已保存")
    except json.JSONDecodeError:
        st.error("JSON格式错误，请检查")

    st.markdown("---")
    st.markdown("**添加新状态：**")
    col_new1, col_new2, col_new3 = st.columns(3)
    with col_new1:
        new_label = st.text_input("状态标签", placeholder="例如：样品跟进中")
    with col_new2:
        new_color = st.color_picker("颜色", "#1976D2")
    with col_new3:
        st.markdown("　")
        if st.button("➕ 添加"):
            if new_label:
                current = get_setting("statuses", [])
                if not any(s['label'] == new_label for s in current):
                    current.append({"label": new_label, "color": new_color})
                    set_setting("statuses", current)
                    st.success(f"✅ 已添加：{new_label}")
                    st.rerun()
                else:
                    st.warning("状态已存在")


# ── TAB 2: EMAIL RULES ────────────────────────────────────────────────────────
with tab2:
    st.markdown("#### ✉️ 邮件内容规则")

    col_e1, col_e2 = st.columns(2)

    with col_e1:
        st.markdown("**禁用词组（发送时自动检测）**")
        forbidden = get_setting("forbidden_phrases", [])
        forbidden_text = st.text_area(
            "每行一个禁用词组",
            value="\n".join(forbidden),
            height=150
        )
        if st.button("保存禁用词", key="save_forbidden"):
            new_forbidden = [f.strip() for f in forbidden_text.split('\n') if f.strip()]
            set_setting("forbidden_phrases", new_forbidden)
            st.success("✅ 已保存")

        st.markdown("**CTA资源列表**")
        cta_resources = get_setting("cta_resources", [])
        cta_text = st.text_area(
            "每行一个CTA资源名称",
            value="\n".join(cta_resources),
            height=120
        )
        if st.button("保存CTA列表", key="save_cta"):
            new_cta = [c.strip() for c in cta_text.split('\n') if c.strip()]
            set_setting("cta_resources", new_cta)
            st.success("✅ 已保存")

    with col_e2:
        st.markdown("**字数限制**")
        max_subject = st.number_input("主题行最大字符数", min_value=30, max_value=100, value=50)
        max_words = st.number_input("正文最大词数", min_value=50, max_value=300, value=120)

        st.markdown("**每家最多触达次数**")
        max_touches = st.number_input("最大触达次数", min_value=1, max_value=5,
                                      value=get_setting("max_touches", 3))
        if st.button("保存邮件规则"):
            set_setting("max_touches", int(max_touches))
            st.success("✅ 已保存")


# ── TAB 3: FOLLOWUP SCHEDULE ──────────────────────────────────────────────────
with tab3:
    st.markdown("#### ⏰ 跟进节奏设置")

    col_f1, col_f2 = st.columns(2)
    with col_f1:
        st.markdown("**跟进间隔（天）**")
        intervals = get_setting("followup_intervals", [7, 14, 21])
        d7 = st.number_input("Day1→Day2间隔（天）", min_value=1, max_value=30, value=intervals[0])
        d14 = st.number_input("Day2→Day3间隔（天）", min_value=1, max_value=30, value=intervals[1])
        d21 = st.number_input("Day3上限（天）", min_value=1, max_value=60, value=intervals[2])

        st.markdown("**冷静期天数**")
        cold_days = st.number_input("冷静期（天）", min_value=30, max_value=365,
                                    value=get_setting("cold_period_days", 90))

        if st.button("保存跟进设置"):
            set_setting("followup_intervals", [int(d7), int(d14), int(d21)])
            set_setting("cold_period_days", int(cold_days))
            st.success("✅ 已保存")

    with col_f2:
        st.markdown("**发送工作日**")
        all_days = ["Monday","Tuesday","Wednesday","Thursday","Friday"]
        send_days = get_setting("send_days", ["Tuesday","Wednesday","Thursday"])
        selected_days = st.multiselect("选择允许发送的工作日", all_days, default=send_days)

        st.markdown("**发送时间（当地时间）**")
        send_hour = st.slider("发送小时", min_value=7, max_value=17,
                              value=get_setting("send_hour", 9))
        st.markdown(f"📅 邮件将在收件人当地时间 **{send_hour}:00** 发出")

        st.markdown("**LinkedIn检查提醒（天）**")
        linkedin_days = st.number_input("超过X天未查看Owner主页时提醒", min_value=1, max_value=30,
                                        value=get_setting("linkedin_check_days", 14))

        if st.button("保存发送设置"):
            set_setting("send_days", selected_days)
            set_setting("send_hour", int(send_hour))
            set_setting("linkedin_check_days", int(linkedin_days))
            st.success("✅ 已保存")

    st.markdown("---")
    st.markdown("**季节性提醒配置**")
    seasonal = get_setting("seasonal_triggers", [])
    seasonal_json = st.text_area(
        "季节性提醒（JSON）",
        value=json.dumps(seasonal, ensure_ascii=False, indent=2),
        height=200
    )
    if st.button("保存季节性提醒"):
        try:
            set_setting("seasonal_triggers", json.loads(seasonal_json))
            st.success("✅ 已保存")
        except json.JSONDecodeError:
            st.error("JSON格式错误")


# ── TAB 4: AUTO DISCOVERY ─────────────────────────────────────────────────────
with tab4:
    st.markdown("#### 🔍 自动客户搜索设置")

    auto_enabled = get_setting("auto_discovery_enabled", True)
    enabled = st.toggle("启用每周自动搜索", value=auto_enabled)

    st.markdown("**搜索关键词（每行一个）**")
    keywords = get_setting("discovery_keywords", [])
    kw_text = st.text_area("关键词列表", value="\n".join(keywords), height=120)

    st.markdown("**目标州（逗号分隔，如 TX,FL,CA）**")
    states = get_setting("discovery_states", [])
    states_text = st.text_input("州缩写列表", value=",".join(states))

    if st.button("保存搜索设置"):
        set_setting("auto_discovery_enabled", enabled)
        new_kw = [k.strip() for k in kw_text.split('\n') if k.strip()]
        set_setting("discovery_keywords", new_kw)
        new_states = [s.strip().upper() for s in states_text.split(',') if s.strip()]
        set_setting("discovery_states", new_states)
        st.success("✅ 已保存")

    st.markdown("---")
    st.markdown("**客户评分权重**")
    weights = get_setting("score_weights", {})
    w1, w2 = st.columns(2)
    with w1:
        w_bag_strong = st.slider("袋包强信号", 0, 50, weights.get('bag_signal_strong', 40))
        w_bag_medium = st.slider("袋包中信号", 0, 30, weights.get('bag_signal_medium', 20))
        w_esg = st.slider("ESG/环保信号", 0, 40, weights.get('esg_signal', 30))
    with w2:
        w_ppai = st.slider("PPAI会员", 0, 20, weights.get('ppai_member', 15))
        w_linkedin = st.slider("Owner LinkedIn活跃", 0, 20, weights.get('owner_linkedin_active', 10))
        w_size = st.slider("5-50人规模", 0, 10, weights.get('size_5_50', 5))
    if st.button("保存评分权重"):
        set_setting("score_weights", {
            'bag_signal_strong': w_bag_strong, 'bag_signal_medium': w_bag_medium,
            'esg_signal': w_esg, 'ppai_member': w_ppai,
            'owner_linkedin_active': w_linkedin, 'size_5_50': w_size
        })
        st.success("✅ 已保存")


# ── TAB 5: ACCOUNT & SIGNATURE ────────────────────────────────────────────────
with tab5:
    st.markdown("#### 🔑 账号与签名")

    col_a1, col_a2 = st.columns(2)
    with col_a1:
        st.markdown("**面板访问密码**")
        current_pw = st.text_input("当前密码", type="password")
        new_pw = st.text_input("新密码", type="password")
        confirm_pw = st.text_input("确认新密码", type="password")
        if st.button("修改密码"):
            try:
                correct = st.secrets["auth"]["password"]
            except Exception:
                correct = "Eetoon2026!"
            if current_pw != correct:
                st.error("当前密码错误")
            elif new_pw != confirm_pw:
                st.error("两次新密码不一致")
            elif len(new_pw) < 6:
                st.error("密码至少6位")
            else:
                st.warning("密码修改需要在Streamlit Cloud的Secrets里手动更新auth.password字段")

    with col_a2:
        st.markdown("**BCC密送邮件**")
        bcc = get_setting("bcc_email", "")
        new_bcc = st.text_input("密送到", value=bcc if isinstance(bcc, str) else "")
        if st.button("保存BCC"):
            set_setting("bcc_email", new_bcc)
            st.success("✅ 已保存（注意：发送脚本从.env读取BCC，此处仅为显示）")

    st.markdown("---")
    st.markdown("**邮件签名**")
    sig = get_setting("sender_signature", "")
    if isinstance(sig, str):
        sig_val = sig
    else:
        sig_val = ""
    new_sig = st.text_area("签名内容（会自动附加到每封发出的邮件）", value=sig_val, height=150)
    if st.button("保存签名", type="primary"):
        set_setting("sender_signature", new_sig)
        st.success("✅ 签名已更新")

    st.markdown("---")
    st.markdown("**SMTP配置说明**")
    st.info("SMTP账号密码存储在Streamlit Cloud的Secrets里，不在数据库中，需要在Streamlit Cloud控制台修改。")
