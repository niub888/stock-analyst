import streamlit as st
import pandas as pd
import requests
import plotly.graph_objects as go
from datetime import datetime
import time
import re

st.set_page_config(page_title="AI股票分析", layout="wide")
st.title("AI 智能股票分析师 (极速版)")

# 核心函数
def get_realtime_data(code):
    url = f"http://hq.sinajs.cn/list={code}"
    try:
        resp = requests.get(url, headers={'Referer': 'https://finance.sina.com.cn'}, timeout=5)
        if resp.status_code == 200 and '="' in resp.text:
            parts = resp.text.split('"')[1].split(',')
            if len(parts) > 3:
                return {'name': parts[0], 'price': float(parts[3]), 'code': code}
    except: pass
    return None

# 侧边栏
code = st.sidebar.text_input("股票代码", "sh600519")
if st.sidebar.button("分析"):
    with st.spinner("分析中..."):
        data = get_realtime_data(code)
        if data:
            st.metric(data['name'], data['price'])
            st.success("数据获取成功！")
        else:
            st.error("无法获取数据")

st.info("如果能看到这个页面，说明服务已经修好了！")
