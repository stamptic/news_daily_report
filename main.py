import feedparser
import requests
import os
import hashlib
from datetime import datetime, timedelta
import dashscope

# 从环境变量读取配置
FEISHU_WEBHOOK = os.environ.get("FEISHU_WEBHOOK")
DASHSCOPE_API_KEY = os.environ.get("DASHSCOPE_API_KEY")
dashscope.api_key = DASHSCOPE_API_KEY

# 传统媒体 RSS 源（均已验证可用）
RSS_SOURCES = {
    "华尔街见闻": "https://plink.anyfeeder.com/weixin/wallstreetcn",
    "央视财经": "https://plink.anyfeeder.com/weixin/cctvyscj",
    "21世纪经济报道": "https://plink.anyfeeder.com/weixin/jjbd21",
    "界面新闻: 财经": "https://plink.anyfeeder.com/jiemian/finance",
    "新华社新闻": "https://plink.anyfeeder.com/newscn/whxw",
    "中国日报: 财经": "https://plink.anyfeeder.com/chinadaily/caijing",
    "科技 - 财富中文网": "https://plink.anyfeeder.com/fortunechina/keji",
}

def fetch_sina_news():
    """从新浪财经7×24快讯API获取实时快讯"""
    url = "https://zhibo.sina.com.cn/api/zhibo/feed?page=1&page_size=20&zhibo_id=152&tag_id=0&dire=f&dpc=1"
    news_list = []
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        # 解析路径可能随接口微调，做兼容处理
        feed_data = data.get("result", {}).get("data", {}).get("feed_data", [])
        for item in feed_data:
            # 提取标题（content字段通常是文本内容）
            title = item.get("content", "").strip()
            if not title or len(title) < 5:
                continue
            # 过滤纯图片消息
            if title.startswith("[图片]"):
                continue
            news_list.append({
                "title": title,
                "link": item.get("docurl", ""),
                "summary": "",
                "source": "新浪财经快讯",
                "time": item.get("create_time", ""),
            })
    except Exception as e:
        print(f"新浪快讯获取失败: {e}")
    return news_list

def fetch_news():
    all_news = []
    # 1. 获取传统RSS
    for source, url in RSS_SOURCES.items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:20]:  # 每个源取前20条
                pub_time = entry.get('published_parsed') or entry.get('updated_parsed')
                if pub_time:
                    dt = datetime(*pub_time[:6])
                    # 只保留24小时内的新闻
                    if datetime.now() - dt > timedelta(hours=24):
                        continue
                # 提取链接并过滤搜狗微信链接
                original_link = extract_original_link(entry)
                if original_link and 'weixin.sogou.com' in original_link:
                    original_link = ''
                all_news.append({
                    "title": entry.title,
                    "link": original_link,
                    "summary": entry.get("summary", ""),
                    "source": source,
                    "time": entry.get("published", entry.get("updated", "")),
                })
        except Exception as e:
            print(f"抓取{source}失败: {e}")
    # 2. 获取新浪快讯
    sina_news = fetch_sina_news()
    all_news.extend(sina_news)
    
    # 去重（按标题哈希）
    seen = set()
    unique_news = []
    for item in all_news:
        hash_id = hashlib.md5(item['title'].encode()).hexdigest()
        if hash_id not in seen:
            seen.add(hash_id)
            unique_news.append(item)
    return unique_news

def filter_relevant(news_list):
    """关键词过滤，只保留与股票/基金相关的新闻"""
    keywords = ['股市','A股','基金','央行','证监会','板块','涨停','跌停','IPO','降准','降息',
                '美联储','汇率','新能源','半导体','消费','医药','科技','政策','数据','财报','回购','增持','港股','美股','证券','指数','交易','债券']
    filtered = []
    for n in news_list:
        text = n['title'] + n['summary']
        if any(k in text for k in keywords):
            filtered.append(n)
    return filtered

def analyze_news(news_list):
    """调用大模型生成分析报告"""
    if not news_list:
        return "今日无相关财经新闻。"
            
    # 获取当前日期（北京时间）
    today_str = datetime.now().strftime('%Y年%m月%d日')
    
    # 限制最多50条，避免token超限
    news_text = "\n".join([f"{i+1}. {n['title']}（来源：{n['source']}）" for i,n in enumerate(news_list[:50])])
    prompt = f"""你是一位资深财经分析师，今天是{today_str}。请根据以下今日财经新闻，输出一份简洁的“今日市场要点”报告，要求：
1. 核心事件：不超过5条，每条一句话概括。
2. 影响判断：标注利多/利空/中性，并说明可能影响的板块（如半导体、新能源、消费等）及影响原因。
3. 重点关注：给出1-2个今日最值得关注的方向或风险提示。
注意：不要输出报告中未提及的日期，不要使用“2025年4月5日”等虚构日期。

新闻列表：
{news_text}
"""
    response = dashscope.Generation.call(
        model='qwen-flash',
        prompt=prompt,
        temperature=0.3,
        max_tokens=800
    )
    if response.status_code == 200:
        return response.output.text
    else:
        return f"分析失败，错误信息：{response.message}"

def send_feishu(report, news_list):

    content = f"📈 **今日财经日报**\n{report}"
    
    # 附加相关新闻列表（最多显示10条，可调整）
    if news_list:
        content += "\n\n📎 **相关新闻列表**\n"
        for idx, n in enumerate(news_list[:10], 1):
            title = n['title'].strip()
            source = n['source']
            link = n.get('link', '')
            if link and 'weixin.sogou.com' not in link:
                # 有有效链接，显示为标题和链接（飞书会自动识别URL）
                content += f"{idx}. [{source}] {title} - {link}\n"
            else:
                # 无有效链接，只显示标题和来源，方便搜索
                content += f"{idx}. [{source}] {title}\n"
    
    payload = {
        "msg_type": "text",
        "content": {"text": content}
    }
    headers = {'Content-Type': 'application/json'}
    response = requests.post(FEISHU_WEBHOOK, json=payload, headers=headers)
    print(f"飞书推送状态: {response.status_code}, {response.text}")

def main():
    print(f"任务开始：{datetime.now()}")
    news = fetch_news()
    print(f"抓取到原始新闻 {len(news)} 条")
    filtered = filter_relevant(news)
    print(f"过滤后剩余 {len(filtered)} 条")
    report = analyze_news(filtered)
    send_feishu(report, filtered)   # 传入新闻列表
    print("任务完成")

if __name__ == "__main__":
    main()
