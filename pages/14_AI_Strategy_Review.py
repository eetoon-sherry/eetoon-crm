"""Weekly and monthly strategy review based on campaign data."""

import streamlit as st

from utils.database import get_campaign_metrics, get_campaigns, judge_campaign_health


st.set_page_config(page_title="AI Strategy Review | EETOON CRM", layout="wide")

if not st.session_state.get("authenticated"):
    st.warning("请先登录")
    st.stop()

st.markdown("## AI Strategy Review")
st.caption("当前为规则版增长复盘。Claude API Key 到位后可升级为模型版，但仍必须引用真实数据。")

campaigns = get_campaigns()
if not campaigns:
    st.info("暂无 campaign。")
    st.stop()

selected = st.selectbox("Campaign", campaigns, format_func=lambda c: c.get("campaign_name", "Unknown"))
metrics = get_campaign_metrics(selected.get("id"))
judgement = judge_campaign_health(metrics)

review_type = st.radio("复盘类型", ["周复盘", "月底深度判断"], horizontal=True)

st.markdown("### 关键事实")
st.write(
    f"候选 {metrics['candidates']} 个，合格 {metrics['qualified']} 个，"
    f"已发送 {metrics['sent']} 封，退信率 {metrics['bounce_rate']}%，"
    f"回复率 {metrics['reply_rate']}%，正向回复率 {metrics['positive_reply_rate']}%。"
)

if review_type == "周复盘":
    st.markdown("### 本周发生了什么")
    if metrics["sent"] == 0:
        st.write("本周还没有形成发送样本，当前重点不是优化话术，而是补候选、确认邮箱、批准首封邮件。")
    else:
        st.write("本周已经形成初步发送记录，下一步需要继续补充回复和退信数据。")

    st.markdown("### 哪些数据好")
    positives = []
    if metrics["grade_a"] + metrics["grade_b"] > 0:
        positives.append("候选池里已经有 A/B 级客户，可以进入人工审核。")
    if metrics["bounce_rate"] and metrics["bounce_rate"] <= 8:
        positives.append("退信率暂时在可接受区间。")
    if metrics["reply_rate"] >= 2:
        positives.append("回复率达到继续低频测试标准。")
    st.write("\n".join(f"- {p}" for p in positives) if positives else "暂无正向信号，需要先补真实发送和回复样本。")

    st.markdown("### 哪些数据差")
    gaps = []
    if metrics["candidates"] < 50:
        gaps.append("候选客户数不足，6月底前很难判断细分方向。")
    if metrics["qualified"] < 20:
        gaps.append("合格客户数不足，开发流程还没有进入稳定产出。")
    if metrics["sent"] < 30:
        gaps.append("发送样本不足，暂时不能判断 hook 好坏。")
    if metrics["bounce_rate"] > 12:
        gaps.append("退信率偏高，需要优先修邮箱质量。")
    st.write("\n".join(f"- {g}" for g in gaps) if gaps else "没有明显红灯。")

    st.markdown("### 下周建议")
    st.write(judgement["next_action"])

else:
    st.markdown("### 这个 campaign 是否值得加码")
    st.write(f"当前建议：**{judgement['decision']}**。置信度：**{judgement['confidence']}**。")

    st.markdown("### 是否应该转向其他客户群体")
    if metrics["sent"] < 50:
        st.write("暂不建议直接转向。当前样本不足，先跑满基础发送量。")
    elif metrics["reply_rate"] < 2 and metrics["positive_reply_rate"] == 0:
        st.write("可以考虑并行测试品牌商客户，但先确认不是邮箱质量或首封 hook 问题。")
    else:
        st.write("可以保留美国礼品分销商线，同时准备品牌商线作为 7 月并行 campaign。")

    st.markdown("### 检测中心视频上线后的角度")
    st.write(
        "把开发角度从单纯供应包袋，升级为“有工厂和检测能力背书的包袋项目支持”。"
        "适合强调 RPET/GRS、质量一致性、交期控制、企业礼品项目风险降低。"
    )

    st.markdown("### 执行清单")
    st.write(
        "- 补足 A/B 级候选客户\n"
        "- 每封首封邮件必须人工审核\n"
        "- 记录退信、回复、正向回复\n"
        "- 每周停用表现差的 hook\n"
        "- 6月底用回复率、正向回复率、退信率决定加码/保持/暂停/转向"
    )

st.markdown("### 判断依据")
for evidence in judgement["evidence"]:
    st.write(f"- {evidence}")
st.write(f"风险：{judgement['risk']}")
