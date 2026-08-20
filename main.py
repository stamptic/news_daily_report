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

# 财经RSS源（待测试替换）
RSS_SOURCES = {
    "财联社": "https://rsshub.app/cls/telegraph",
    "华尔街见闻": "https://rsshub.app/wallstreetcn/live/global",
    "金十数据": "https://rsshub.app/jin10",
}

def fetch_news():
    news_list = []
    for source, url in RSS_SOURCES.items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:30]:
                # 过滤24小时内
                pub_time = entry.get('published_parsed') or entry.get('updated_parsed')
                if pub_time:
                    dt = datetime(*pub_time[:6])
                    if datetime.now() - dt > timedelta(hours=24):
                        continue
                news_list.append({
                    "title": entry.title,
                    "link": entry.link,
                    "summary": entry.get("summary", ""),
                    "source": source,
                    "time": entry.get("published", entry.get("updated", "")),
                })
        except Exception as e:
            print(f"抓取{source}失败: {e}")
    # 去重
    seen = set()
    unique_news = []
    for item in news_list:
        hash_id = hashlib.md5(item['title'].encode()).hexdigest()
        if hash_id not in seen:
            seen.add(hash_id)
            item['hash'] = hash_id
            unique_news.append(item)
    return unique_news

def filter_relevant(news_list):
    keywords = ['股市','A股','基金','央行','证监会','板块','涨停','跌停','IPO','降准','降息',
                '美联储','汇率','新能源','半导体','消费','医药','科技','政策','数据','财报','回购','增持','港股','美股']
    return [n for n in news_list if any(k in n['title']+n['summary'] for k in keywords)]

def analyze_news(news_list):
    if not news_list:
        return "今日无相关财经新闻。"
    news_text = "\n".join([f"{i+1}. {n['title']}（来源：{n['source']}）" for i,n in enumerate(news_list[:50])])
    prompt = f"""你是一位资深财经分析师，请根据以下今日财经新闻，输出一份简洁的“今日市场要点”报告，要求：
1. 核心事件：不超过5条，每条一句话概括。
2. 影响判断：标注利多/利空/中性，并说明可能影响的板块（如半导体、新能源、消费等）。
3. 重点关注：给出1-2个今日最值得关注的方向或风险提示。

新闻列表：
{news_text}
"""
    response = dashscope.Generation.call(
        model='qwen-plus',
        prompt=prompt,
        temperature=0.3,
        max_tokens=800
    )
    if response.status_code == 200:
        return response.output.text
    else:
        return f"分析失败，错误信息：{response.message}"

def send_feishu(report):
    payload = {
        "msg_type": "text",
        "content": {"text": report}
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
    send_feishu(report)
    print("任务完成")

if __name__ == "__main__":
    main()
