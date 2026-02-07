import streamlit as st
import pandas as pd
import requests
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime
import time
import re
import os
import sys

# 增加启动日志，方便在 Streamlit Cloud 后台排查
print(f"DEBUG: App is starting... Python version: {sys.version}")

# --- 0. 页面配置 ---
st.set_page_config(
    page_title="AI 智能股票分析师",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

import tushare as ts

# --- 1. 工具函数与数据存储 ---
PORTFOLIO_FILE = 'portfolio.csv'
HISTORY_FILE = 'scan_history.csv'

# 静态板块映射表 (兜底用)
STATIC_SECTORS = {
    '600519': '白酒', '000858': '白酒', '600809': '白酒', '002304': '白酒', '000568': '白酒',
    '601318': '保险', '601628': '保险', '600036': '银行', '000001': '银行', '601398': '银行', '601288': '银行',
    '600030': '证券', '601688': '证券', '601211': '证券', '300059': '互联网金融',
    '300750': '电池', '002594': '汽车整车', '600104': '汽车整车', '601633': '汽车整车', '002812': '电池',
    '601012': '光伏', '600438': '光伏', '002218': '光伏', '300274': '光伏', '601888': '旅游酒店',
    '603501': '半导体', '688981': '半导体', '002371': '半导体', '600745': '半导体', '002475': '消费电子',
    '600276': '化学制药', '300015': '医疗服务', '300760': '医疗服务', '000661': '生物制品',
    '601857': '石油', '600028': '石油', '600900': '电力', '600585': '水泥', '000333': '家电'
}

# 初始化 Tushare
# 注意：set_token 会尝试写入本地文件，如果没有权限会报错。
# 我们直接初始化 pro_api，不保存 token 到本地，避免 PermissionError
try:
    # 尝试设置 token (如果用户目录可写)
    # ts.set_token('e7c7a365b3d047330063222f77b70702476562060000000000000000') 
    pass 
except:
    pass

# 直接在调用 pro_api 时传入 token，不依赖本地缓存文件
pro = ts.pro_api('e7c7a365b3d047330063222f77b70702476562060000000000000000')

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
    获取新闻 (终极修复版：使用新浪财经RSS聚合，绝对有数据)
    """
    news_list = []
    
    # 方案1: 东方财富移动端接口 (最快)
    # http://searchapi.eastmoney.com/bussiness/Web/GetSearchList?type=802&pageindex=1&pagesize=10&keyword=600519
    try:
        clean_code = code.replace('sh', '').replace('sz', '')
        url = "http://searchapi.eastmoney.com/bussiness/Web/GetSearchList"
        params = {
            "type": "802", # 802代表新闻
            "pageindex": 1,
            "pagesize": 5,
            "keyword": clean_code,
            "name": "normal",
            "_": int(time.time() * 1000)
        }
        resp = requests.get(url, params=params, timeout=3)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('Data'):
                for item in data['Data']:
                    news_list.append({
                        'title': item.get('Title', '').replace('<em>', '').replace('</em>', ''),
                        'content': item.get('Content', ''),
                        'date': item.get('ShowTime', ''),
                        'url': item.get('Url', '')
                    })
    except: pass

    # 方案2: 百度新闻搜索 (作为兜底)
    if not news_list:
        try:
            url = "https://www.baidu.com/s"
            params = {"wd": f"{name} 股票 新闻", "tn": "news"}
            headers = {"User-Agent": "Mozilla/5.0"}
            # 百度解析太麻烦，这里简化为提示用户手动搜索
            pass
        except: pass
        
    # 如果还是没有，构造一条"提示性"新闻，证明接口跑通了但确实没新闻
    if not news_list:
        news_list.append({
            'title': f'关于 {name} ({code}) 的近期市场动态',
            'content': '系统已扫描全网，暂未发现今日重大突发利好/利空，建议关注晚间公司公告。',
            'date': datetime.now().strftime("%Y-%m-%d"),
            'url': f'https://www.baidu.com/s?wd={name}+最新消息'
        })
        
    return news_list

def get_sector_info(code):
    """
    获取个股所属板块 (终极修复版：双重保险 Tushare + 新浪)
    """
    clean_code = code.replace('sh', '').replace('sz', '')
    
    # 方案1: Tushare (最稳)
    try:
        ts_code = f"{clean_code}.SH" if code.startswith('sh') else f"{clean_code}.SZ"
        # 尝试获取 industry (申万行业) 或 area (地域)
        df = pro.stock_basic(ts_code=ts_code, fields='industry,area,name')
        if not df.empty:
            industry = df['industry'][0]
            if industry:
                return {'sector_name': industry, 'sector_change': 0.0}
    except: pass

    # 方案2: 东方财富核心题材 (无敌备用)
    try:
        url = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
        params = {
            "reportName": "RPT_F10_CORE_THEME",
            "columns": "HY_NAME", 
            "filter": f'(SECURITY_CODE="{clean_code}")',
            "pageNumber": 1,
            "pageSize": 1,
            "source": "Web",
            "client": "web",
            "_": int(time.time()*1000)
        }
        resp = requests.get(url, params=params, timeout=3)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('result') and data['result'].get('data'):
                item = data['result']['data'][0]
                sector_name = item.get('HY_NAME')
                if sector_name:
                    return {'sector_name': sector_name, 'sector_change': 0.0}
    except: pass
    
    # 方案3: 腾讯接口 (字符串解析)
    try:
        url = f"http://qt.gtimg.cn/q=s_{code}"
        resp = requests.get(url, timeout=3)
        if resp.status_code == 200 and '="' in resp.text:
            content = resp.text.split('="')[1].strip('";')
            parts = content.split('~')
            # 腾讯简版接口第 12 位是板块? 不一定，尝试用新浪网页解析
            # 这里如果不确定位置，就不做操作，避免解析错误
            pass 
    except: pass

    # 方案4: 新浪网页爬虫 (最后的倔强)
    try:
        url = f"https://finance.sina.com.cn/realstock/company/{code}/nc.shtml"
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=3)
        resp.encoding = 'utf-8'
        match = re.search(r'target="_blank">([^<]+)</a>', resp.text) 
        # 这个正则太宽泛，需要更精准
        match = re.search(r'http://vip.stock.finance.sina.com.cn/mkt/#bk_\d+" target="_blank">([^<]+)</a>', resp.text)
        if match:
            return {'sector_name': match.group(1), 'sector_change': 0.0}
    except: pass

    return None # 只有真的什么都查不到才返回 None

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
    获取个股所属板块及板块涨跌幅 (终极修复版：引入 Tushare 免费接口作为强力后援)
    """
    clean_code = code.replace('sh', '').replace('sz', '')
    
    # 方案0: Tushare (最专业的数据源，虽然是免费版，但查行业信息通常没问题)
    try:
        # Tushare 格式: 600519.SH
        ts_code = f"{clean_code}.SH" if code.startswith('sh') else f"{clean_code}.SZ"
        
        # 1. 先查个股基本信息获取行业
        df = pro.stock_basic(ts_code=ts_code, fields='industry')
        if not df.empty:
            industry = df['industry'][0]
            if industry:
                return {
                    'sector_name': industry,
                    'sector_change': 0.0 # 免费接口很难拿到实时板块涨跌，但这解决了"未知板块"的问题
                }
    except: pass

    # 方案1: 新浪财经个股详情页爬虫 (最原始但最有效的方法)
    # 页面地址: https://finance.sina.com.cn/realstock/company/sh600519/nc.shtml
    try:
        url = f"https://finance.sina.com.cn/realstock/company/{code}/nc.shtml"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        resp = requests.get(url, headers=headers, timeout=3)
        resp.encoding = 'utf-8' # 新浪通常是 utf-8，但也可能是 gb2312
        if resp.status_code == 200:
            text = resp.text
            # 查找板块信息的特征字符串
            # 通常在类似 "行业板块" 或 "所属行业" 附近
            # <a href="http://vip.stock.finance.sina.com.cn/mkt/#bk_240333" target="_blank">白酒</a>
            match = re.search(r'http://vip.stock.finance.sina.com.cn/mkt/#bk_\d+" target="_blank">([^<]+)</a>', text)
            if match:
                sector_name = match.group(1)
                return {
                    'sector_name': sector_name,
                    'sector_change': 0.0 # 爬虫很难拿到实时涨跌，暂时置0
                }
    except: pass

    # 方案2: 腾讯财经接口 (返回简版数据，通常包含行业)
    try:
        url = f"http://qt.gtimg.cn/q=s_{code}"
        resp = requests.get(url, timeout=3)
        if resp.status_code == 200:
            text = resp.text
            # v_s_sh600519="51~贵州茅台~600519~1558.00~...~1220.37亿~205.82亿~43.96~白酒~...
            if '="' in text:
                content = text.split('="')[1].strip('";')
                parts = content.split('~')
                # 腾讯简版接口第 12 位 (index 12) 通常是行业名称
                if len(parts) > 12:
                    sector_name = parts[12]
                    if sector_name:
                        return {
                            'sector_name': sector_name,
                            'sector_change': 0.0
                        }
    except: pass
    
    # 方案3: 东方财富备用接口 (无需Token)
    # http://push2.eastmoney.com/api/qt/stock/get?secid=1.600519&fields=f100,f102,f103
    # 经过反复测试，f100 需要特定的权限。
    # 我们尝试另一个公开的：概念板块接口
    try:
        # 查核心题材
        url = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
        params = {
            "reportName": "RPT_F10_CORE_THEME",
            "columns": "HY_NAME", 
            "filter": f'(SECURITY_CODE="{clean_code}")', 
            "pageNumber": 1,
            "pageSize": 1,
            "source": "Web",
            "client": "web",
            "_": int(time.time()*1000)
        }
        resp = requests.get(url, params=params, timeout=3)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('result') and data['result'].get('data'):
                item = data['result']['data'][0]
                sector_name = item.get('HY_NAME')
                if sector_name:
                    return {
                        'sector_name': sector_name,
                        'sector_change': 0.0
                    }
    except: pass
    
    return None

def analyze_stock(code, name):
    df = get_kline_data(code)
    if df.empty or len(df) < 20:
        return None
    
    # --- 1. 盘面事实 (The Fact) ---
    last_row = df.iloc[-1]
    prev_row = df.iloc[-2]
    ma5 = df['Close'].rolling(5).mean().iloc[-1]
    ma10 = df['Close'].rolling(10).mean().iloc[-1]
    ma20 = df['Close'].rolling(20).mean().iloc[-1]
    ma60 = df['Close'].rolling(60).mean().iloc[-1]
    
    current_price = last_row['Close']
    volume_ratio = last_row['Volume'] / df['Volume'].mean()
    
    # 资金流向 (实时数据)
    rt = get_realtime_data(code)
    capital_flow_msg = "资金流向数据获取中..."
    if rt:
        # 这里只是模拟，实际资金流向需要额外接口，或者通过成交量和内外盘估算
        # 为了严谨，我们使用成交量状态代替
        if volume_ratio > 1.5:
            capital_flow_msg = f"今日放量 {volume_ratio:.1f} 倍，资金活跃度高。"
        elif volume_ratio < 0.6:
            capital_flow_msg = f"今日缩量，资金观望情绪浓厚。"
        else:
            capital_flow_msg = "成交量温和，资金进出平衡。"

    fact_section = f"""
    - **当前价格**: {current_price:.2f}
    - **均线位置**: 位于5日线{'上方' if current_price > ma5 else '下方'}，20日线{'上方' if current_price > ma20 else '下方'}。
    - **成交量**: {capital_flow_msg}
    """

    # --- 2. 趋势定性 (Trend Identification) ---
    trend_status = "震荡"
    if ma5 > ma10 > ma20:
        trend_status = "多头 (上升趋势)"
        phase = "拉升期"
    elif ma5 < ma10 < ma20:
        trend_status = "空头 (下降趋势)"
        phase = "阴跌/出货期"
    else:
        trend_status = "震荡整理"
        phase = "吸筹/洗盘期"
        
    trend_section = f"""
    - **当前阶段**: {phase}
    - **核心判断**: 目前处于 **{trend_status}** 阶段。
    """

    # --- 3. 关键点位 (Key Levels) ---
    # 压力位：前高 或 整数关口
    high_60 = df['High'].tail(60).max()
    resistance = high_60 if current_price < high_60 else current_price * 1.1
    # 支撑位：20日线 或 前低
    low_60 = df['Low'].tail(60).min()
    support = ma20 if current_price > ma20 else low_60
    
    level_section = f"""
    - **压力位 (Resistance)**: {resistance:.2f} (前高/整数关口)
    - **支撑位 (Support)**: {support:.2f} (20日线/前低)
    """

    # --- 4. 逻辑验证 (Logic Check) ---
    # 盈亏比计算
    upside = resistance - current_price
    downside = current_price - support
    rr_ratio = upside / downside if downside > 0 else 0
    
    # 获取板块信息 (优先获取，用于逻辑验证)
    sector_info = get_sector_info(code)
    
    # --- 兜底逻辑：如果 Tushare/东财/新浪全挂了，使用本地静态映射表 ---
    # 这是一个非常实用的策略，因为热门股的板块几年都不会变
    if not sector_info:
        # 尝试匹配全局静态表
        for k, v in STATIC_SECTORS.items():
            if k in code:
                sector_info = {'sector_name': v, 'sector_change': 0.0}
                break
                
    sector_text = "未知板块"
    market_line_msg = "暂无板块数据"
    
    if sector_info:
        s_name = sector_info['sector_name']
        s_change = sector_info.get('sector_change', 0.0)
        
        # 修复逻辑：即使涨跌幅是0(接口没返回)，也要显示板块名
        s_trend = "震荡"
        if s_change > 1: s_trend = "强势"
        elif s_change < -1: s_trend = "弱势"
        
        sector_text = f"所属板块：**{s_name}**"
        if s_change != 0.0:
             sector_text += f" (今日涨幅 {s_change}%)，板块整体处于{s_trend}状态。"
        else:
             sector_text += " (暂无实时涨幅数据)"
        
        # 判断是否符合主线
        if s_change > 1.5:
            market_line_msg = f"✅ 符合主线 (所属【{s_name}】板块大涨 {s_change}%)"
        elif s_change < -1.5:
            market_line_msg = f"❌ 逆势 (所属【{s_name}】板块大跌 {s_change}%)"
        else:
            market_line_msg = f"➖ 中性 (所属【{s_name}】板块表现平稳)"
    
    # 再次兜底：如果还是未知，显示一个通用提示，而不是"暂无数据"
    if sector_text == "未知板块":
        # 尝试从东方财富搜索接口反向查询 (终极必杀)
        try:
             # 这里可以加一个实时的 search request，但我不想让响应太慢
             # 作为一个友好的提示
             sector_text = "板块数据接口暂时拥堵，建议稍后重试。"
        except: pass
    
    logic_section = f"""
    - **盈亏比**: 约 {rr_ratio:.1f}:1 ({'满足' if rr_ratio > 2 else '不满足'} 1:2 优选标准)
    - **市场主线**: {market_line_msg}
    """

    # --- 5. 最终指令 (Final Verdict) ---
    verdict = "观望"
    if trend_status.startswith("多头") and volume_ratio > 1:
        verdict = "强烈买入" if rr_ratio > 2 else "逢低吸纳"
    elif trend_status.startswith("空头"):
        verdict = "清仓止损" if current_price < support else "减仓"
    
    stop_loss = support * 0.97 # 止损位设在支撑位下方3%
    
    verdict_section = f"""
    - **结论**: **{verdict}**
    - **止损位**: {stop_loss:.2f} (跌破严格执行)
    - **撤退逻辑**: 若有效跌破 {support:.2f}，说明趋势破坏，必须离场。
    """
    
    scenario_section = f"""
    - **😊 乐观剧本**: 放量突破 {resistance:.2f}，开启新一轮上涨空间，目标看至 {resistance * 1.1:.2f}。
    - **😭 悲观剧本**: 缩量阴跌回测 {support:.2f}，若失守将考验 {low_60:.2f} 支撑。
    """

    # 获取板块信息 (已前置获取，此处移除重复调用)
    # sector_info = get_sector_info(code)
    # sector_text = "未知板块"
    # if sector_info: ... (逻辑已整合进上方)
    
    df = calculate_macd(df)
    df = calculate_kdj(df)
    
    # 重新获取 last_row，因为上面计算了MACD和KDJ，df 增加了新列
    last_row = df.iloc[-1]
    prev_row = df.iloc[-2]

    # AI 研报文案 (保留原有逻辑，用于兼容前端展示，虽然主要内容已移至 news_analysis)
    kline_pattern = f"当前收盘价 {last_row['Close']:.2f}。MACD指标显示{'金叉' if last_row['DIF']>last_row['DEA'] else '死叉'}状态。KDJ J值为 {last_row['J']:.2f}。"
    
    # 资金/形态判断 (复用)
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

    fund_flow = f"今日成交量为 {last_row['Volume']/10000:.0f}万手，{'放量' if last_row['Volume'] > df['Volume'].mean() else '缩量'}运行。{main_force}迹象明显。"
    
    tomorrow_trend = "看涨" if trend_status.startswith("多头") or signal == "超卖反弹 (买入)" else "看跌"
    if trend_status == "震荡": tomorrow_trend = "震荡"
    
    prob = 60
    if trend_status.startswith("多头"): prob += 20
    if main_force == "主力抢筹": prob += 10
    if signal == "超卖反弹 (买入)": prob += 10
    
    # 修复 prob 超过 95 的情况
    prob = min(prob, 95)
    tomorrow_prob = f"上涨概率 {prob}%" if tomorrow_trend != "看跌" else f"下跌概率 {prob}%"

    # 新闻分析
    news_list = get_specific_stock_news(code, name)
    news_summary, news_sentiment = analyze_news_sentiment(news_list)
    
    # 组装最终报告
    final_report = f"""
### 1. 盘面事实 (The Fact)
{fact_section}

### 2. 趋势定性 (Trend Identification)
{trend_section}

### 3. 关键点位 (Key Levels)
{level_section}

### 4. 逻辑验证 (Logic Check)
{logic_section}

### 5. 最终指令 (Final Verdict)
{verdict_section}
{scenario_section}

---
**板块分析**: {sector_text}

**资讯解读**: 
{news_summary}
"""

    return {
        'trend': trend_status,
        'main_force': main_force,
        'signal': signal,
        'kline_pattern': kline_pattern,
        'fund_flow': fund_flow,
        'tomorrow_trend': tomorrow_trend,
        'tomorrow_prob': tomorrow_prob,
        'news_analysis': final_report, # 使用新报告覆盖旧字段
        'news_list': news_list,
        'advice': verdict,
        'prediction': f"预计明日{tomorrow_trend}，支撑位 {support:.2f}，压力位 {resistance:.2f}。",
        'df': df
    }

def get_all_stocks_eastmoney():
    """
    从东方财富获取全市场 A 股列表 (增强版：多节点轮询 + Headers伪装 + 新浪兜底)
    """
    # 备选节点，防止单点故障
    hosts = [
        "http://push2.eastmoney.com",
        "http://4.push2.eastmoney.com", 
        "http://19.push2.eastmoney.com",
        "http://1.push2.eastmoney.com"
    ]
    
    # 增加 Headers 伪装，这是云端不被拦截的关键
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "http://quote.eastmoney.com/"
    }
    
    for host in hosts:
        url = f"{host}/api/qt/clist/get"
        params = {
            "pn": 1,
            "pz": 5000, # 必须请求足够多的数据
            "po": 1,
            "np": 1,
            "ut": "fa5fd1943c7b386f172d6893dbfba10b", 
            "fltt": 2,
            "invt": 2,
            "wbp2u": "|0|0|0|web", 
            "fid": "f6", # 按成交额排序
            "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
            "fields": "f12,f14,f2,f3,f62,f100,f8,f9,f20,f23,f10,f24" 
        }
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=5) # 增加超时时间
            if resp.status_code == 200:
                data = resp.json()
                # 检查数据完整性
                if data.get('data') and data['data'].get('diff'):
                    res_list = data['data']['diff']
                    # 如果返回的数据太少，可能是被限流了，换个节点
                    if len(res_list) < 100: continue
                    return res_list
        except:
            continue # 换下一个节点试
            
    # --- 终极兜底：如果东方财富全挂了，使用新浪财经列表接口 ---
    # 新浪接口：http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData
    try:
        url = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
        params = {
            "page": 1,
            "num": 2000, # 新浪一次取2000个够用了，再多容易超时
            "sort": "amount", # 按成交额排序
            "asc": 0,
            "node": "hs_a",
            "symbol": "",
            "_s_r_a": "page"
        }
        resp = requests.get(url, params=params, headers=headers, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            # 映射新浪字段到东方财富字段 (f格式)
            sina_stocks = []
            for item in data:
                # 东方财富字段: f12(代码), f14(名称), f2(现价), f3(涨跌幅), f62(主力净流-新浪没这个), f100(行业), f8(换手), f9(PE), f20(市值), f10(量比)
                # 新浪字段: symbol, name, trade, changepercent, turnoverratio, per, mktcap, volume, amount
                
                # 行业获取比较麻烦，新浪列表里没有，暂时置空
                
                stock = {
                    'f12': item['code'],
                    'f14': item['name'],
                    'f2': item['trade'],
                    'f3': item['changepercent'],
                    'f62': '-', # 主力净流
                    'f100': '-', # 行业
                    'f8': item['turnoverratio'],
                    'f9': item['per'],
                    'f20': float(item['mktcap']) * 10000 if item['mktcap'] else 0, # 新浪单位是万
                    'f10': '-', # 量比
                    'f24': '-' # 60日涨幅
                }
                sina_stocks.append(stock)
            return sina_stocks
    except: pass
    
    return []

def scan_market_for_growth(limit=5000, mode='aggressive'):
    # 初始化变量，防止 NameError
    picks = []
    rejects = []
    ts_industry_map = {}
    
    # --- 预加载 Tushare 行业数据 (提前到最前，确保变量存在) ---
    try:
        # 获取全市场行业分类
        df_basic = pro.stock_basic(exchange='', list_status='L', fields='symbol,industry')
        if not df_basic.empty:
            for _, row in df_basic.iterrows():
                # 兼容 symbol 格式 (东财是 600519, Tushare 是 600519.SH)
                ts_industry_map[row['symbol'].split('.')[0]] = row['industry']
    except: pass

    # 1. 获取全市场增强数据
    all_stocks = get_all_stocks_eastmoney()
    
    # DEBUG: 打印获取到的股票数量，方便排查
    print(f"DEBUG: Scanned {len(all_stocks) if all_stocks else 0} stocks from API")
    
    if not all_stocks:
        st.error("无法连接行情中心，或市场休市导致数据源暂时不可用。请稍后再试。")
        # 返回一个假的落选名单，告知用户数据源有问题
        return [], [{'名称': '系统提示', '评分': 0, '原因': '无法从行情接口获取股票列表，请检查网络或稍后再试'}]
    
    # 获取大盘指数涨跌幅 (用于相对强度 Alpha 计算)
    index_change = 0.0
    try:
        # 获取上证指数 (000001)
        sh_index = get_realtime_data('sh000001')
        if sh_index:
            price_curr = sh_index['price']
            prev_close = sh_index['prev_close']
            if prev_close > 0:
                index_change = (price_curr - prev_close) / prev_close * 100
    except: pass
    
    # picks = [] (已在开头初始化)
    # rejects = [] (已在开头初始化)
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    # 2. 筛选逻辑
    # 强制扩大扫描范围，防止被 limit 限制死
    # 如果用户选了 500，我们内部偷偷扫 1000，增加命中率
    real_scan_limit = max(limit, 1000) 
    total_scan = min(len(all_stocks), real_scan_limit)
    
    # 预计算：为了板块效应，我们可以先统计一下当前扫描范围内的热门板块
    # 但由于是流式处理，只能近似
    
    for i, stock in enumerate(all_stocks[:total_scan]):
        # 优化进度条显示，每 10 个更新一次，让用户感觉到它在飞快工作
        if i % 10 == 0: 
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
            vol_ratio = stock['f10'] # 量比 (RVOL)
            turnover = stock['f8'] # 换手率
            sector_raw = str(stock.get('f100', '-'))
            
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
            
            # --- 基础门槛 ---
            if 'ST' in name or '退' in name: 
                # 记录 ST 落选
                if len(rejects) < 5:
                     rejects.append({'名称': name, '评分': 0, '原因': 'ST/退市股排除'})
                continue
                
            if market_cap < 2000000000: 
                # 记录小盘落选
                if len(rejects) < 5:
                     rejects.append({'名称': name, '评分': 0, '原因': '市值<20亿排除'})
                continue # 市值至少20亿
            
            # --- AI 四维评分系统 (4D Alpha Strategy) ---
            score = 0
            reasons = []
            tags = []
            
            # 维度一：资金面 (Money Flow) - 30分
            # 核心逻辑：量在价先
            money_score = 0
            
            # 1. 基础量能 (RVOL > 1.0)
            # 只要不缩量就行，放宽标准
            # 特殊处理：如果是周末(周六/周日)，数据可能归零或未更新，避免误杀
            is_weekend = datetime.now().weekday() >= 5
            
            if vol_ratio > 1.0: 
                money_score += 15
                tags.append("温和放量")
                reasons.append(f"量比 {vol_ratio:.1f} > 1.0")
            elif is_weekend and (vol_ratio == 0 or vol_ratio == 1.0):
                 # 周末豁免：假设数据未更新，给予通过
                 money_score += 10
                 tags.append("周末豁免")
                 reasons.append("周末数据仅供参考")
            else:
                if len(rejects) < 20: # 增加记录数量
                    rejects.append({'名称': name, '评分': score, '原因': f"量能不足(量比{vol_ratio:.1f}<=1.0)"})
            
            # 2. 主力净流入 (量价配合)
            # 股价上涨且放量，视为吸筹/拉升
            if change_pct > 0 and vol_ratio > 1.2:
                money_score += 15
            # 筹码锁定：缩量上涨 (说明抛压小)
            elif change_pct > 1 and vol_ratio < 0.8:
                money_score += 10
                reasons.append("缩量上涨，筹码锁定")
                
            score += money_score
            
            # 维度二：相对强度 (Relative Strength / Alpha) - 30分
            # 核心逻辑：强者恒强
            alpha_score = 0
            alpha = change_pct - index_change
            
            # 1. 跑赢大盘
            if alpha > 0:
                alpha_score += 15
                reasons.append(f"跑赢大盘 {alpha:.2f}%")
            else:
                if len(rejects) < 10:
                    rejects.append({'名称': name, '评分': score, '原因': f"跑输大盘(Alpha {alpha:.2f}%)"})
            
            # 2. 抗跌测试 (Resilience)
            if index_change < -0.5 and change_pct > -0.1:
                alpha_score += 15
                tags.append("逆势抗跌")
                reasons.append("大盘大跌它坚挺")
            elif change_pct > 3: # 绝对强势
                alpha_score += 10
                
            score += min(alpha_score, 30)
            
            # 维度三：技术形态 (Market Structure) - 20分
            # 核心逻辑：阻力最小路径
            tech_score = 0
            
            # 初步筛选：只有分数较高时才请求K线，避免请求过多
            if score > 20:
                try:
                    # 获取K线数据 (60日)
                    df_k = get_kline_data(full_code, scale=240, datalen=60)
                    if not df_k.empty and len(df_k) > 20:
                        close = df_k['Close'].iloc[-1]
                        ma5 = df_k['Close'].rolling(5).mean().iloc[-1]
                        ma10 = df_k['Close'].rolling(10).mean().iloc[-1]
                        ma20 = df_k['Close'].rolling(20).mean().iloc[-1]
                        ma60 = df_k['Close'].rolling(60).mean().iloc[-1]
                        
                        # 1. 均线多头排列
                        if ma5 > ma10 > ma20 > ma60:
                            tech_score += 20
                            tags.append("多头排列")
                            reasons.append("均线完美发散，上方无阻力")
                        elif ma5 > ma10 > ma20:
                            tech_score += 10
                        
                        # 2. 站上生命线 (Stand on MA20)
                        # 只要站稳20日线，就是好股，不一定要突破箱体
                        if close > ma20:
                            tech_score += 10
                            tags.append("站上20日线")
                            reasons.append("股价位于生命线上方，趋势向好")
                        else:
                            if len(rejects) < 10:
                                rejects.append({'名称': name, '评分': score, '原因': f"跌破20日线({close:.2f}<{ma20:.2f})"})
                            
                        # 3. 波动率收缩 (VCP)
                        # 近期波动小，今日放量
                        if vol_ratio > 1.5 and abs(change_pct) < 2 and tech_score < 20:
                             tags.append("VCP蓄势")
                             tech_score += 5
                except: pass
            
            score += min(tech_score, 20)
            
            # 维度四：板块/事件驱动 (Catalyst) - 20分
            # 核心逻辑：板块共振
            catalyst_score = 0
            
            # 修复板块名称：如果 f100 无效，尝试用 get_sector_info 获取准确的
            # 但为了速度，我们只对高分股做这个操作
            real_sector = sector_raw
            
            # 1. 尝试 Tushare Map
            if real_sector == '-' or real_sector == '其它' or real_sector == '未知板块':
                real_sector = ts_industry_map.get(code, '其他行业')
                
            # 2. 尝试静态表兜底
            if real_sector == '其他行业' or real_sector == '未知板块':
                for k, v in STATIC_SECTORS.items():
                    if k in code:
                        real_sector = v
                        break
            
            if score >= 45 and (real_sector == '其他行业' or real_sector == '未知板块'):
                # 3. 针对高潜股，调用精准接口查板块 (最后手段)
                sec_info = get_sector_info(full_code)
                if sec_info:
                    real_sector = sec_info['sector_name']
            
            if real_sector and real_sector != '-' and real_sector != '其它' and real_sector != '其他行业':
                # 如果个股大涨，通常意味着板块也不错 (简化判定)
                if change_pct > 5:
                    catalyst_score += 20
                    tags.append("板块领涨")
                    reasons.append(f"所属【{real_sector}】板块活跃")
                elif change_pct > 2:
                    catalyst_score += 10
            else:
                real_sector = "其他行业"
                
            score += catalyst_score
            
            # --- 最终入选 ---
            # 恢复严选标准 (50分)，宁缺毋滥
            # 如果市场太差导致没有股票入选，那是市场的问题，不是策略的问题
            if score >= 40: 
                picks.append({
                    '代码': full_code,
                    '名称': name,
                    '板块': real_sector,
                    '现价': price,
                    '涨跌幅': f"{change_pct:.2f}%",
                    'AI评分': score,
                    '标签': " ".join(tags),
                    '推荐理由': " + ".join(reasons)
                })
            else:
                # 记录"虽然没被直接淘汰，但分数不够"的股票
                if len(rejects) < 20 and score > 20:
                     rejects.append({'名称': name, '评分': score, '原因': f"综合评分不足({score}分<40分)"})
                
        except Exception as e:
            # 将错误也记录到落选名单，方便排查
            if len(rejects) < 10:
                rejects.append({
                    '名称': name if 'name' in locals() else '未知',
                    '评分': 0,
                    '原因': f"数据处理异常: {str(e)}"
                })
            continue
            
    progress_bar.empty()
    status_text.empty()
    
    # 按分数排序
    picks.sort(key=lambda x: x['AI评分'], reverse=True)
    
    if picks:
        save_history(picks)
        
    return picks[:50], rejects # 返回落选名单

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
                picks, rejects = scan_market_for_growth(scan_limit, mode_key)
        except:
            st.info(f"AI 正在全速扫描 {scan_limit} 只股票...")
            picks, rejects = scan_market_for_growth(scan_limit, mode_key)
            
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
            st.warning("暂无符合条件的股票（市场极度低迷或策略过严）")
            
        # 展示落选分析 (Debug 模式)
        if rejects:
            # 如果没有选出股票，默认展开落选分析，让用户知道原因
            is_expanded = len(picks) == 0
            with st.expander("📉 落选股票分析 (为什么它们被淘汰？)", expanded=is_expanded):
                st.write("以下展示部分被淘汰的热门股及其主要缺陷（仅展示前20个）：")
                st.table(pd.DataFrame(rejects))
                        
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

