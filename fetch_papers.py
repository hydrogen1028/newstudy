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

# 設定 OpenAI API Key
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# PubMed API base
PUBMED_API = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"

def search_pubmed(keyword, retmax=3):
    """用 PubMed 搜尋關鍵字，回傳 PMID 清單"""
    url = f"{PUBMED_API}esearch.fcgi"
    params = {
        "db": "pubmed",
        "term": keyword,
        "retmode": "json",
        "retmax": retmax
    }
    r = requests.get(url, params=params)
    r.raise_for_status()
    data = r.json()
    return data["esearchresult"]["idlist"]

def fetch_abstract(pmid):
    """抓取 PMID 的摘要與基本資訊"""
    url = f"{PUBMED_API}esummary.fcgi"
    params = {"db": "pubmed", "id": pmid, "retmode": "json"}
    r = requests.get(url, params=params)
    r.raise_for_status()
    summary = r.json()["result"][pmid]

    fetch_url = f"{PUBMED_API}efetch.fcgi"
    params = {"db": "pubmed", "id": pmid, "retmode": "text", "rettype": "abstract"}
    r2 = requests.get(fetch_url, params=params)
    r2.raise_for_status()
    abstract = r2.text

    return {
        "pmid": pmid,
        "title": summary.get("title", ""),
        "authors": [a["name"] for a in summary.get("authors", [])],
        "journal": summary.get("fulljournalname", ""),
        "year": summary.get("pubdate", "").split(" ")[0],
        "doi": summary.get("elocationid", ""),
        "abstract": abstract
    }

def summarize_papers(papers, keyword):
    """用 GPT 摘要 + 結構化 JSON"""
    summaries = []
    for paper in papers:
        prompt = f"""
你是一個醫學文獻解析助手。請將以下 PubMed 論文內容整理成 JSON。
欄位包括：
- pmid, title, authors[], journal, year, doi, abstract
- summary (用 3–5 句整理研究背景與主要發現)
- study_design {{
    inclusion_criteria[],
    primary_outcome {{ name, result }},
    secondary_outcomes [{{ name, result }}],
    subgroup_analysis [{{ subgroup, result }}]
}}
- conclusion

規則：
1. 結果數據請包含數值 (HR, OR, CI, p-value)，若文中未提及請填 "not reported"。
2. 請只輸出 JSON，不要額外文字。

論文內容：
{json.dumps(paper, ensure_ascii=False)}
"""
        response = client.chat.completions.create(
            model="gpt-4o-mini",  # 可換 gpt-4.1 / gpt-4o
            messages=[{"role": "system", "content": "你是醫學研究助手。"},
                      {"role": "user", "content": prompt}],
            temperature=0
        )
        try:
            summary = json.loads(response.choices[0].message.content)
        except:
            summary = {"error": "JSON parsing failed", "raw": response.choices[0].message.content}
        summaries.append(summary)
    return {"keyword": keyword, "papers": summaries}

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
    keyword = input("請輸入關鍵字： ")
    pmids = search_pubmed(keyword, retmax=10)
    papers = [fetch_abstract(pmid) for pmid in pmids]
    result = summarize_papers(papers, keyword)

    send_email(all_reports)
    print("📩 報告已寄出！")
