import streamlit as st
import pandas as pd
import requests
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime
import time
import re
import os

# --- 0. 页面配置 ---
st.set_page_config(
    page_title="AI 智能股票分析师",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 1. 工具函数与数据存储 ---
PORTFOLIO_FILE = 'portfolio.csv'
HISTORY_FILE = 'scan_history.csv'

def load_portfolio():
    if os.path.exists(PORTFOLIO_FILE):
        try:
            df = pd.read_csv(PORTFOLIO_FILE, dtype={'code': str})
            return df
        except:
            return pd.DataFrame(columns=['code', 'name', 'add_time'])
    return pd.DataFrame(columns=['code', 'name', 'add_time'])

def save_portfolio(df):
    df.to_csv(PORTFOLIO_FILE, index=False)

def load_history():
    """加载选股历史"""
    if os.path.exists(HISTORY_FILE):
        try:
            df = pd.read_csv(HISTORY_FILE, dtype={'code': str})
            return df
        except:
            pass
    return pd.DataFrame(columns=['scan_time', 'code', 'name', 'init_price', 'ai_score', 'reason'])

def save_history(picks):
    """保存选股历史 (只存前10名，避免文件过大)"""
    df = load_history()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    new_rows = []
    for p in picks[:10]: # 只存前10个高分股
        new_rows.append({
            'scan_time': now_str,
            'code': p['代码'],
            'name': p['名称'],
            'init_price': p['现价'],
            'ai_score': p['AI评分'],
            'reason': p['推荐理由']
        })
    
    new_df = pd.DataFrame(new_rows)
    # 合并并去重 (保留最新的)
    df = pd.concat([new_df, df], ignore_index=True)
    df.to_csv(HISTORY_FILE, index=False)

def normalize_code(code):
    code = code.strip()
    if not (code.startswith('sh') or code.startswith('sz')):
        if code.startswith('6'):
            return 'sh' + code
        elif code.startswith(('0', '3')):
            return 'sz' + code
    return code

def add_to_portfolio(code, name):
    df = load_portfolio()
    code = normalize_code(code)
    if code not in df['code'].values:
        new_row = pd.DataFrame({'code': [code], 'name': [name], 'add_time': [datetime.now().strftime("%Y-%m-%d %H:%M")]})
        df = pd.concat([df, new_row], ignore_index=True)
        save_portfolio(df)
        return True
    return False

def remove_from_portfolio(code):
    df = load_portfolio()
    if code in df['code'].values:
        df = df[df['code'] != code]
        save_portfolio(df)
        return True
    return False

# --- 2. 数据获取接口 ---

def search_stock_code(keyword):
    """
    通过中文名称搜索股票代码 (使用新浪建议接口)
    """
    url = f"http://suggest3.sinajs.cn/suggest/type=11,12&key={keyword}"
    try:
        response = requests.get(url, headers={'Referer': 'https://finance.sina.com.cn'}, timeout=3)
        if response.status_code == 200:
            text = response.text
            match = re.search(r'="([^"]*)"', text)
            if match:
                data_str = match.group(1)
                if data_str:
                    items = data_str.split(';')
                    if items:
                        first_item = items[0].split(',')
                        if len(first_item) > 4:
                            full_code = first_item[3] # 修正：有些接口返回位置不同，通常是第4个
                            # 再次确认格式
                            if not (full_code.startswith('sh') or full_code.startswith('sz')):
                                full_code = first_item[0] # 备用
                            name = first_item[4]
                            return full_code, name
    except Exception as e:
        print(f"Search Error: {e}")
    return None, None

def get_realtime_data(code):
    url = f"http://hq.sinajs.cn/list={code}"
    try:
        response = requests.get(url, headers={'Referer': 'https://finance.sina.com.cn'}, timeout=3)
        if response.status_code == 200:
            text = response.text
            if '=""' in text or '=","' in text:
                return None
            match = re.search(r'="([^"]*)"', text)
            if match:
                data_str = match.group(1)
                parts = data_str.split(',')
                if len(parts) > 3:
                    return {
                        'code': code,
                        'name': parts[0],
                        'open': float(parts[1]),
                        'prev_close': float(parts[2]),
                        'price': float(parts[3]),
                        'high': float(parts[4]),
                        'low': float(parts[5]),
                        'volume': float(parts[8]),
                        'amount': float(parts[9]),
                        'date': parts[30],
                        'time': parts[31]
                    }
    except:
        pass
    return None

def get_kline_data(code, scale=240, datalen=120):
    symbol = code.replace('sh', '').replace('sz', '')
    url = f"http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={code}&scale={scale}&ma=no&datalen={datalen}"
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            df = pd.DataFrame(data)
            df.rename(columns={'day': 'date', 'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'volume': 'Volume'}, inplace=True)
            df['Open'] = df['Open'].astype(float)
            df['High'] = df['High'].astype(float)
            df['Low'] = df['Low'].astype(float)
            df['Close'] = df['Close'].astype(float)
            df['Volume'] = df['Volume'].astype(float)
            return df
    except:
        pass
    return pd.DataFrame()

def get_specific_stock_news(code, name):
    """
    获取特定个股的新闻资讯 (来源：东方财富接口)
    """
    clean_code = code.replace('sh', '').replace('sz', '')
    url = "https://search-api-web.eastmoney.com/search/json/page"
    params = {
        "client": "web",
        "coll": "cms_article",
        "keyword": name,
        "page": 1,
        "pageSize": 5,
        "sort": "date",
        "_": int(time.time() * 1000)
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Referer": "https://so.eastmoney.com/"
    }
    news_list = []
    try:
        response = requests.get(url, params=params, headers=headers, timeout=3)
        if response.status_code == 200:
            data = response.json()
            if data.get('result') and data['result'].get('items'):
                for item in data['result']['items']:
                    title = item.get('title', '').replace('<em>', '').replace('</em>', '')
                    content = item.get('content', '').replace('<em>', '').replace('</em>', '')
                    date_str = item.get('showTime', '')
                    if name in title or clean_code in title or name in content:
                        news_list.append({
                            'title': title,
                            'content': content,
                            'date': date_str,
                            'url': item.get('url', '')
                        })
    except:
        pass
    return news_list

def analyze_news_sentiment(news_list):
    if not news_list:
        return "暂无最新资讯", "中性"
    
    positive_keywords = ['增长', '预增', '盈利', '中标', '合同', '突破', '利好', '回购', '增持', '分红', '新高', '获批', '首发']
    negative_keywords = ['亏损', '下降', '减少', '违规', '立案', '调查', '减持', '解禁', '利空', '跌停', '警示', '诉讼']
    
    score = 0
    recent_news = news_list[:5]
    for news in recent_news:
        title = news['title']
        p_hits = [k for k in positive_keywords if k in title]
        n_hits = [k for k in negative_keywords if k in title]
        if p_hits: score += 1
        if n_hits: score -= 1
            
    sentiment = "中性"
    if score > 0:
        sentiment = "偏利好"
        analysis_text = f"近期资讯中出现 {score} 条利好信号，市场关注度较高。"
    elif score < 0:
        sentiment = "偏利空"
        analysis_text = f"近期资讯中出现 {abs(score)} 条潜在风险信号，需警惕情绪面冲击。"
    else:
        analysis_text = "近期资讯面相对平静，无重大利好或利空消息。"
        
    return analysis_text, sentiment

# --- 3. 技术指标计算 ---

def calculate_macd(df, short=12, long=26, mid=9):
    df['EMA12'] = df['Close'].ewm(span=short, adjust=False).mean()
    df['EMA26'] = df['Close'].ewm(span=long, adjust=False).mean()
    df['DIF'] = df['EMA12'] - df['EMA26']
    df['DEA'] = df['DIF'].ewm(span=mid, adjust=False).mean()
    df['MACD'] = (df['DIF'] - df['DEA']) * 2
    return df

def calculate_kdj(df, n=9, m1=3, m2=3):
    low_list = df['Low'].rolling(window=n, min_periods=1).min()
    high_list = df['High'].rolling(window=n, min_periods=1).max()
    rsv = (df['Close'] - low_list) / (high_list - low_list) * 100
    df['K'] = rsv.ewm(com=m1-1, adjust=False).mean()
    df['D'] = df['K'].ewm(com=m2-1, adjust=False).mean()
    df['J'] = 3 * df['K'] - 2 * df['D']
    return df

# --- 4. 核心分析逻辑 ---

def get_sector_info(code):
    """
    获取个股所属板块及板块涨跌幅 (使用东方财富接口)
    """
    # 东方财富需要secid，简单映射：sh->1, sz->0
    clean_code = code.replace('sh', '').replace('sz', '')
    market_id = '1' if code.startswith('sh') else '0'
    secid = f"{market_id}.{clean_code}"
    
    url = f"http://push2.eastmoney.com/api/qt/stock/get"
    params = {
        "secid": secid,
        "fields": "f100,f102,f103", # f100行业, f102行业代码, f103行业涨幅
        "invt": 2,
        "fltt": 2
    }
    try:
        resp = requests.get(url, params=params, timeout=3)
        if resp.status_code == 200:
            data = resp.json()
            if data['data']:
                return {
                    'sector_name': data['data']['f100'],
                    'sector_change': data['data']['f103']
                }
    except:
        pass
    return None

def analyze_stock(code, name):
    df = get_kline_data(code)
    if df.empty:
        return None
    
    # 获取板块信息
    sector_info = get_sector_info(code)
    sector_text = "未知板块"
    if sector_info:
        s_name = sector_info['sector_name']
        s_change = sector_info['sector_change']
        s_trend = "强势" if s_change > 1 else "弱势" if s_change < -1 else "震荡"
        sector_text = f"所属板块：**{s_name}** (今日涨幅 {s_change}%)，板块整体处于{s_trend}状态。"
    
    df = calculate_macd(df)
    df = calculate_kdj(df)
    
    last_row = df.iloc[-1]
    prev_row = df.iloc[-2]
    
    # 基础指标
    trend = "震荡"
    if last_row['DIF'] > last_row['DEA'] and last_row['DIF'] > 0:
        trend = "强势上涨"
    elif last_row['DIF'] < last_row['DEA'] and last_row['DIF'] < 0:
        trend = "弱势下跌"
        
    # 资金/形态判断
    main_force = "资金观望"
    if last_row['Volume'] > df['Volume'].mean() * 1.5 and last_row['Close'] > last_row['Open']:
        main_force = "主力抢筹"
    elif last_row['Volume'] > df['Volume'].mean() * 1.5 and last_row['Close'] < last_row['Open']:
        main_force = "主力出货"
        
    # 信号
    signal = "持有"
    if last_row['K'] < 20 and last_row['K'] > prev_row['K']:
        signal = "超卖反弹 (买入)"
    elif last_row['K'] > 80 and last_row['K'] < prev_row['K']:
        signal = "超买回调 (卖出)"
        
    # AI 研报文案
    kline_pattern = f"当前收盘价 {last_row['Close']:.2f}。MACD指标显示{'金叉' if last_row['DIF']>last_row['DEA'] else '死叉'}状态。KDJ J值为 {last_row['J']:.2f}。"
    fund_flow = f"今日成交量为 {last_row['Volume']/10000:.0f}万手，{'放量' if last_row['Volume'] > df['Volume'].mean() else '缩量'}运行。{main_force}迹象明显。"
    
    tomorrow_trend = "看涨" if trend == "强势上涨" or signal == "超卖反弹 (买入)" else "看跌"
    if trend == "震荡": tomorrow_trend = "震荡"
    
    prob = 60
    if trend == "强势上涨": prob += 20
    if main_force == "主力抢筹": prob += 10
    if signal == "超卖反弹 (买入)": prob += 10
    tomorrow_prob = f"上涨概率 {min(prob, 95)}%" if tomorrow_trend != "看跌" else f"下跌概率 {min(prob, 95)}%"

    # 新闻分析
    news_list = get_specific_stock_news(code, name)
    news_summary, news_sentiment = analyze_news_sentiment(news_list)
    
    news_analysis = f"{news_summary}\n\n**板块分析**: {sector_text}\n\n**AI 综合推演**: 结合技术面{trend}趋势与{main_force}信号，"
    if news_sentiment == "偏利好":
        news_analysis += "消息面利好共振，建议积极关注。"
    elif news_sentiment == "偏利空":
        news_analysis += "消息面存在利空扰动，建议谨慎规避。"
    else:
        news_analysis += "消息面平稳，以技术面操作为主。"

    return {
        'trend': trend,
        'main_force': main_force,
        'signal': signal,
        'kline_pattern': kline_pattern,
        'fund_flow': fund_flow,
        'tomorrow_trend': tomorrow_trend,
        'tomorrow_prob': tomorrow_prob,
        'news_analysis': news_analysis,
        'news_list': news_list,
        'advice': f"当前处于{trend}阶段，建议{signal}。",
        'prediction': f"预计明日{tomorrow_trend}，支撑位 {df['Low'].min():.2f}，压力位 {df['High'].max():.2f}。",
        'df': df
    }

def get_all_stocks_eastmoney():
    """
    从东方财富获取全市场 A 股列表 (增强版：包含PE、市值、量比、60日涨幅等)
    """
    url = "http://4.push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": 1,
        "pz": 5000,
        "po": 1,
        "np": 1,
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": 2,
        "invt": 2,
        "fid": "f6", # 按成交额排序
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
        # 增加字段: f9(PE动态), f20(总市值), f23(市净率), f10(量比), f24(60日涨幅), f100(行业), f103(行业涨幅)
        "fields": "f12,f14,f2,f3,f62,f100,f8,f9,f20,f23,f10,f24" 
    }
    try:
        resp = requests.get(url, params=params, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if data['data'] and data['data']['diff']:
                return data['data']['diff']
    except:
        pass
    return []

def scan_market_for_growth(limit=5000, mode='aggressive'):
    # 1. 获取全市场增强数据
    all_stocks = get_all_stocks_eastmoney()
    if not all_stocks:
        st.error("无法连接行情中心，请检查网络")
        return []
    
    picks = []
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    # 2. 筛选逻辑
    total_scan = min(len(all_stocks), limit)
    
    for i, stock in enumerate(all_stocks[:total_scan]):
        if i % 50 == 0: 
            progress_bar.progress((i + 1) / total_scan)
            status_text.caption(f"AI 正在深度扫描: {stock['f14']} ({i}/{total_scan})...")
            
        try:
            # --- 基础数据提取 ---
            price = stock['f2']
            change_pct = stock['f3']
            name = stock['f14']
            code = stock['f12']
            pe = stock['f9']
            market_cap = stock['f20']
            vol_ratio = stock['f10'] # 量比
            turnover = stock['f8'] # 换手率
            
            # 数据清洗
            if price == '-' or change_pct == '-' or market_cap == '-': continue
            
            price = float(price)
            change_pct = float(change_pct)
            market_cap = float(market_cap)
            vol_ratio = float(vol_ratio) if vol_ratio != '-' else 1.0
            turnover = float(turnover) if turnover != '-' else 0
            pe = float(pe) if pe != '-' else -1
            
            # 补全代码
            full_code = f"sh{code}" if code.startswith('6') else f"sz{code}"
            
            # --- 基础门槛 (放宽) ---
            # 1. 排除极小盘和ST (ST股名字通常带ST)
            if 'ST' in name or '退' in name: continue
            if market_cap < 2000000000: continue # 市值至少20亿
            
            # --- AI 动态评分系统 (Score) ---
            score = 0
            reasons = []
            tags = []
            
            # 1. 资金面打分 (权重 40%)
            if vol_ratio > 1.5: 
                score += 15
                tags.append("放量")
            if vol_ratio > 3.0: 
                score += 10 # 爆量额外加分
                
            if turnover > 3: 
                score += 10
                tags.append("活跃")
            if turnover > 10: 
                score += 5 # 高换手额外加分
                
            # 2. 技术面打分 (权重 40%)
            # 激进模式：喜欢涨势好的
            if mode == 'aggressive':
                if 2 <= change_pct <= 9: 
                    score += 20
                    reasons.append("主升浪启动区间(2-9%)")
                elif change_pct > 9:
                    score += 10 # 涨停板虽然好，但不好买，分给低点
            # 稳健模式：喜欢跌不动的
            else:
                if -5 <= change_pct <= 1:
                    score += 20
                    reasons.append("低位抗跌/微涨")
            
            # 3. 基本面打分 (权重 20%)
            if pe > 0 and pe < 60: 
                score += 10
                reasons.append("估值合理")
            elif pe > 0:
                score += 5
                
            # --- 进阶技术确认 (K线形态) ---
            # 只有当基础分及格时(例如>30分)，才去请求K线，节省资源
            if score > 30:
                try:
                    df_k = get_kline_data(full_code, scale=240, datalen=30)
                    if not df_k.empty and len(df_k) > 20:
                        close = df_k['Close'].iloc[-1]
                        ma5 = df_k['Close'].rolling(5).mean().iloc[-1]
                        ma10 = df_k['Close'].rolling(10).mean().iloc[-1]
                        ma20 = df_k['Close'].rolling(20).mean().iloc[-1]
                        ma30 = df_k['Close'].rolling(30).mean().iloc[-1]
                        
                        # 策略 A: 均线多头 (最强趋势)
                        if ma5 > ma10 > ma20:
                            score += 30
                            tags.append("多头排列")
                            reasons.append("均线完美发散，趋势极强")
                            
                        # 策略 B: 回踩生命线 (最佳买点)
                        elif close > ma20 and abs(close - ma20)/ma20 < 0.02:
                            score += 25
                            tags.append("回踩支撑")
                            reasons.append("回踩20日线企稳，黄金买点")
                            
                        # 策略 C: 底部突破 (低位首板)
                        elif close > ma30 and df_k['Close'].iloc[-5] < ma30:
                            score += 20
                            tags.append("底部突破")
                            reasons.append("刚刚站上30日线，脱离底部")
                except:
                    pass # K线获取失败不扣分，按基础分算

            # --- 板块加成 (优先使用批量接口自带的行业信息) ---
            sector_str = str(stock.get('f100', '未知板块'))
            
            # 如果是数字(有些接口返回行业ID)，尝试用备用字段或映射(这里简化处理，直接显示)
            # 实际上 f100 返回的是行业名称，如"半导体"
            
            # 只有当板块涨幅明显时才加分 (f103是行业涨幅，需要从批量接口获取)
            # 修正 get_all_stocks_eastmoney 请求字段，确保包含 f100(行业名) 和 f103(行业涨幅,如果有的话)
            # 注: 东方财富 clist 接口 f100 是行业名
            
            # 尝试获取行业涨幅 (f103不在默认clist里，我们需要依赖个股的强势程度来反推板块热度，或者单独获取)
            # 为了不卡顿，这里简化：如果个股是涨停的，就认为板块也热
            
            if sector_str != '-' and sector_str != '其它':
                 # 简单的板块热度判断
                 if change_pct > 5:
                     score += 10
                     tags.append("板块领涨")
                     reasons.append(f"所属【{sector_str}】板块表现活跃")
            else:
                 sector_str = "其他行业"
            
            # --- 最终入选门槛 ---
            # 只要分数超过 50 分就能入选，不再一票否决
            if score >= 50:
                picks.append({
                    '代码': full_code,
                    '名称': name,
                    '板块': sector_str,
                    '现价': price,
                    '涨跌幅': f"{change_pct:.2f}%",
                    'AI评分': score,
                    '标签': " ".join(tags),
                    '推荐理由': " + ".join(reasons)
                })
                
        except Exception as e:
            continue
            
    progress_bar.empty()
    status_text.empty()
    
    # 按分数从高到低排序，只取前N名
    picks.sort(key=lambda x: x['AI评分'], reverse=True)
    
    # 自动保存历史记录
    if picks:
        save_history(picks)
        
    return picks[:50] # 只展示精选的前50个，宁缺毋滥

def send_pushplus(token, title, content):
    url = 'http://www.pushplus.plus/send'
    data = {
        "token": token,
        "title": title,
        "content": content
    }
    try:
        requests.post(url, json=data)
    except:
        pass

# --- 5. 主界面逻辑 ---

# 初始化 Session
if 'selected_stock' not in st.session_state:
    st.session_state['selected_stock'] = 'sh600519'
if 'auto_run' not in st.session_state:
    st.session_state['auto_run'] = False

st.title("🤖 AI 智能股票分析师")
st.markdown("---")

# 侧边栏
st.sidebar.title("控制台")
app_mode = st.sidebar.selectbox("选择模式", ["个股详细分析", "智能选股扫描"])

st.sidebar.markdown("---")
st.sidebar.subheader("📌 我的自选股")
pf = load_portfolio()

# 自选股编辑器
if not pf.empty:
    edited_df = st.sidebar.data_editor(
        pf[['code', 'name']],
        num_rows="dynamic",
        key="portfolio_editor",
        column_config={
            "code": st.column_config.TextColumn("代码", help="双击修改"),
            "name": st.column_config.TextColumn("名称", disabled=True)
        }
    )
    # 简单保存逻辑
    if not edited_df.equals(pf[['code', 'name']]):
        new_pf = edited_df.copy()
        new_pf['add_time'] = datetime.now().strftime("%Y-%m-%d %H:%M")
        new_pf['code'] = new_pf['code'].apply(normalize_code)
        # 更新名称
        for idx, row in new_pf.iterrows():
            if row['code'] != pf.iloc[idx]['code'] if idx < len(pf) else True:
                 rt = get_realtime_data(row['code'])
                 if rt: new_pf.at[idx, 'name'] = rt['name']
        save_portfolio(new_pf)
        st.rerun()
else:
    st.sidebar.info("暂无自选股")

# 手动添加
with st.sidebar.expander("➕ 手动添加"):
    with st.form("add_form"):
        u_input = st.text_input("代码或名称", placeholder="如 600519 或 茅台")
        if st.form_submit_button("添加"):
            final_code = None
            final_name = "获取中..."
            
            if re.search(r'[\u4e00-\u9fa5]', u_input):
                c, n = search_stock_code(u_input)
                if c: final_code, final_name = c, n
            else:
                final_code = normalize_code(u_input)
                rt = get_realtime_data(final_code)
                if rt: final_name = rt['name']
                
            if final_code:
                add_to_portfolio(final_code, final_name)
                st.success(f"已添加 {final_name}")
                st.rerun()
            else:
                st.error("无法识别")

# 快速跳转
st.sidebar.caption("点击跳转分析:")
for idx, row in pf.iterrows():
    if st.sidebar.button(f"{row['name']}", key=f"btn_{row['code']}"):
        st.session_state['selected_stock'] = row['code']
        st.session_state['auto_run'] = True
        st.rerun()

st.sidebar.markdown("---")
# 推送配置
push_token = st.sidebar.text_input("PushPlus Token (微信推送)", value="d506d2e47d27443bba16a213720dbe4a", type="password")
if st.sidebar.button("启动实时监控 (循环)"):
    st.toast("开始监控... 请勿关闭页面")
    ph = st.empty()
    while True:
        msg_list = []
        for _, row in pf.iterrows():
            rt = get_realtime_data(row['code'])
            if rt:
                change = (rt['price'] - rt['prev_close']) / rt['prev_close'] * 100
                if abs(change) > 3:
                    msg_list.append(f"{rt['name']}: {change:.2f}% 现价 {rt['price']}")
        
        if msg_list:
            ph.error(f"⚠️ 预警: {', '.join(msg_list)}")
            if push_token: send_pushplus(push_token, "股价预警", "<br>".join(msg_list))
        else:
            ph.info(f"监控中... {datetime.now().strftime('%H:%M:%S')} 暂无异常")
        
        time.sleep(60)

# --- 主页面内容 ---

if app_mode == "个股详细分析":
    target_code = st.session_state['selected_stock']
    col1, col2 = st.columns([1, 4])
    with col1:
        st.text_input("当前分析", target_code, disabled=True)
    with col2:
        new_search = st.text_input("搜索其他股票", placeholder="输入代码或名称回车")
        if new_search:
            # 简单搜索逻辑
            if re.search(r'[\u4e00-\u9fa5]', new_search):
                c, n = search_stock_code(new_search)
                if c: 
                    st.session_state['selected_stock'] = c
                    st.rerun()
            else:
                st.session_state['selected_stock'] = normalize_code(new_search)
                st.rerun()

    if st.button("开始深度分析") or st.session_state.get('auto_run'):
        st.session_state['auto_run'] = False # 重置
        
        with st.spinner("AI 正在分析大数据..."):
            rt = get_realtime_data(target_code)
            if rt:
                # 头部指标
                c1, c2, c3, c4 = st.columns(4)
                change = (rt['price'] - rt['prev_close']) / rt['prev_close'] * 100
                color = "normal"
                if change > 0: color = "normal" # streamlit metric会自动变色
                
                c1.metric("股票名称", rt['name'])
                c1.metric("股票代码", rt['code'])
                c2.metric("当前价格", f"¥{rt['price']}", f"{change:.2f}%")
                c3.metric("今日开盘", f"¥{rt['open']}")
                c4.metric("成交量", f"{rt['volume']/100:.0f}手")
                
                # 深度分析
                analysis = analyze_stock(target_code, rt['name'])
                if analysis:
                    # 图表
                    df = analysis['df']
                    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.7, 0.3])
                    fig.add_trace(go.Candlestick(x=df['date'], open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='K线'), row=1, col=1)
                    fig.add_trace(go.Bar(x=df['date'], y=df['Volume'], name='成交量'), row=2, col=1)
                    fig.update_layout(xaxis_rangeslider_visible=False, height=500)
                    st.plotly_chart(fig, use_container_width=True)
                    
                    # 研报
                    st.subheader("📝 AI 深度研报")
                    with st.expander("📊 K线形态与资金动向 (点击展开)", expanded=True):
                        k_col, f_col = st.columns(2)
                        k_col.markdown(f"**【K线形态】**：\n{analysis['kline_pattern']}")
                        f_col.markdown(f"**【主力动向】**：\n{analysis['fund_flow']}")
                        
                    with st.expander("🔮 明日走势与资讯解读 (点击展开)", expanded=True):
                        st.markdown(f"**【明日预测】**：{analysis['tomorrow_trend']} ({analysis['tomorrow_prob']})")
                        st.markdown("---")
                        st.markdown(f"**【资讯解读】**：\n{analysis['news_analysis']}")
                        if analysis['news_list']:
                            for n in analysis['news_list'][:3]:
                                st.markdown(f"- [{n['title']}]({n['url']}) ({n['date']})")

                    # 建议
                    st.success(f"💡 **最终建议**: {analysis['advice']}")
                    
            else:
                st.error("获取数据失败，请检查代码是否正确")

elif app_mode == "智能选股扫描":
    st.subheader("🚀 全市场智能扫描")
    
    col_config1, col_config2 = st.columns(2)
    with col_config1:
        mode = st.radio("选择策略", ["激进型 (短线追涨)", "稳健型 (超跌反弹)"])
        mode_key = 'aggressive' if '激进' in mode else 'conservative'
    with col_config2:
        scan_limit = st.slider("扫描范围 (按成交额排名)", min_value=100, max_value=5000, value=500, step=100, help="例如选500，即只扫描全市场成交额最大的前500只股票，效率更高且能过滤垃圾股")
    
    if st.button("开始全市场扫描"):
        # 兼容 spinner
        try:
            with st.spinner(f'AI 正在全速扫描 {scan_limit} 只股票 ({mode_key}模式)...'):
                picks = scan_market_for_growth(scan_limit, mode_key)
        except:
            st.info(f"AI 正在全速扫描 {scan_limit} 只股票...")
            picks = scan_market_for_growth(scan_limit, mode_key)
            
        if picks:
            st.success(f"扫描完成！共发现 {len(picks)} 只优质股 (按AI综合评分排序)：")
            st.dataframe(pd.DataFrame(picks)[['代码', '名称', '板块', '现价', '涨跌幅', 'AI评分', '标签', '推荐理由']])
            
            st.markdown("### 🏆 AI 精选板块")
            df_picks = pd.DataFrame(picks)
            if '板块' in df_picks.columns:
                sector_counts = df_picks['板块'].value_counts()
                top_sectors = sector_counts.head(5).index.tolist()
                st.info(f"🔥 热门板块聚集: {', '.join(top_sectors)}")
                
                # 按板块分组展示
                for sector in top_sectors:
                    with st.expander(f"📁 {sector} ({sector_counts[sector]}只)"):
                        sector_stocks = df_picks[df_picks['板块'] == sector]
                        st.table(sector_stocks[['代码', '名称', '涨跌幅', 'AI评分', '推荐理由']])
            
            st.markdown("### 逐个分析")
            for p in picks:
                with st.expander(f"{p['名称']} ({p['代码']}) - {p['板块']}"):
                    st.write(p['推荐理由'])
                    if st.button(f"加入自选 {p['代码']}", key=f"add_{p['代码']}"):
                        add_to_portfolio(p['代码'], p['名称'])
                        st.toast(f"已加入 {p['名称']}")
                        st.rerun()
        else:
            st.warning("暂无符合条件的股票")
                        
    st.markdown("---")
    st.subheader("📜 历史选股复盘 (验证AI胜率)")
    history_df = load_history()
    if not history_df.empty:
        # 按时间倒序展示最近20条
        recents = history_df.tail(20).iloc[::-1]
        
        # 计算最新收益
        display_rows = []
        for idx, row in recents.iterrows():
            rt = get_realtime_data(row['code'])
            current_price = rt['price'] if rt else 0
            init_price = float(row['init_price'])
            
            profit = 0
            profit_str = "获取中..."
            if current_price > 0:
                profit = (current_price - init_price) / init_price * 100
                profit_str = f"{profit:+.2f}%"
            
            display_rows.append({
                '选出时间': row['scan_time'],
                '代码': row['code'],
                '名称': row['name'],
                '选出价': init_price,
                '现价': current_price,
                '至今收益': profit_str,
                '当时评分': row['ai_score']
            })
            
        st.dataframe(pd.DataFrame(display_rows))
    else:
        st.info("暂无历史记录，快去点击上面的'开始全市场扫描'吧！")

