"""Campaign metrics and decision support."""

import pandas as pd
import streamlit as st

from utils.database import get_campaign_metrics, get_campaigns, judge_campaign_health


st.set_page_config(page_title="Campaign Analytics | EETOON CRM", layout="wide")

if not st.session_state.get("authenticated"):
    st.warning("请先登录")
    st.stop()

st.markdown("## Campaign Analytics")
st.caption("只基于系统内真实记录判断，不用空泛建议。")

campaigns = get_campaigns()
if not campaigns:
    st.info("暂无 campaign。")
    st.stop()

selected = st.selectbox("Campaign", campaigns, format_func=lambda c: c.get("campaign_name", "Unknown"))
metrics = get_campaign_metrics(selected.get("id"))
judgement = judge_campaign_health(metrics)

cols = st.columns(5)
cols[0].metric("候选客户", metrics["candidates"])
cols[1].metric("合格客户", metrics["qualified"])
cols[2].metric("已发送", metrics["sent"])
cols[3].metric("回复率", f"{metrics['reply_rate']}%")
cols[4].metric("退信率", f"{metrics['bounce_rate']}%")

cols2 = st.columns(5)
cols2[0].metric("A级", metrics["grade_a"])
cols2[1].metric("B级", metrics["grade_b"])
cols2[2].metric("C级", metrics["grade_c"])
cols2[3].metric("正向回复率", f"{metrics['positive_reply_rate']}%")
cols2[4].metric("机会数", metrics["opportunities"])

st.markdown("### AI 判断（规则版）")
col_a, col_b, col_c = st.columns(3)
col_a.metric("建议", judgement["decision"])
col_b.metric("最大瓶颈", judgement["bottleneck"])
col_c.metric("置信度", judgement["confidence"])

st.write("判断依据")
st.dataframe(pd.DataFrame({"数据": judgement["evidence"]}), use_container_width=True, hide_index=True)

st.write("推理原因")
st.write(judgement["next_action"])

st.write("风险")
st.write(judgement["risk"])

st.markdown("### 原始指标")
st.json(metrics)
