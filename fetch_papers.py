import requests
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from openai import OpenAI
from datetime import datetime

# 載入 config.json
with open("config.json", "r", encoding="utf-8") as f:
    config = json.load(f)

EMAIL_SENDER = config["email"]["sender"]
EMAIL_PASSWORD = config["email"]["password"]
EMAIL_RECEIVER = config["email"]["receiver"]
SMTP_SERVER = config["email"]["smtp_server"]
SMTP_PORT = config["email"]["smtp_port"]

KEYWORDS = config["keywords"]

# 初始化 OpenAI
client = OpenAI()

def search_pubmed(query, max_results=5):
    url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    params = {
        "db": "pubmed",
        "term": query,
        "retmode": "json",
        "retmax": max_results,
        "sort": "date"
    }
    response = requests.get(url, params=params)
    data = response.json()
    ids = data.get("esearchresult", {}).get("idlist", [])
    
    papers = []
    for pmid in ids:
        fetch_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
        fetch_params = {
            "db": "pubmed",
            "id": pmid,
            "retmode": "xml"
        }
        paper = requests.get(fetch_url, params=fetch_params).text
        papers.append({"pmid": pmid, "raw": paper})
    return papers

def summarize_papers(papers, keyword):
    summaries = []
    for paper in papers:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "你是一個醫學文獻摘要助手，請用 JSON 格式回覆。"},
                {"role": "user", "content": f"請幫我摘要以下 PubMed 論文，並輸出 JSON 格式，欄位包含：title, authors, journal, year, abstract, keyword。原始內容：{paper['raw']}。Keyword={keyword}"}
            ]
        )
        try:
            summaries.append(json.loads(response.choices[0].message.content))
        except:
            summaries.append({"error": "無法解析摘要", "pmid": paper["pmid"]})
    return summaries

def send_email(report_json):
    msg = MIMEMultipart()
    msg["From"] = EMAIL_SENDER
    msg["To"] = EMAIL_RECEIVER
    msg["Subject"] = f"最新文獻摘要報告 - {datetime.now().strftime('%Y-%m-%d')}"

    body = MIMEText(json.dumps(report_json, indent=2, ensure_ascii=False), "plain", "utf-8")
    msg.attach(body)

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_SENDER, EMAIL_RECEIVER, msg.as_string())

if __name__ == "__main__":
    all_reports = {}
    for kw in KEYWORDS:
        papers = search_pubmed(kw, max_results=3)
        summaries = summarize_papers(papers, kw)
        all_reports[kw] = summaries

    send_email(all_reports)
    print("📩 報告已寄出！")
