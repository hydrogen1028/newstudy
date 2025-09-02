import requests
import json
import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import google.generativeai as genai # <-- 1. 引入 Gemini 函式庫

# 載入 config.json
with open("config.json", "r", encoding="utf-8") as f:
    config = json.load(f)

EMAIL_SENDER = config["email"]["sender"]
EMAIL_PASSWORD = config["email"]["password"]
EMAIL_RECEIVER = config["email"]["receiver"]
SMTP_SERVER = config["email"]["smtp_server"]
SMTP_PORT = config["email"]["smtp_port"]

KEYWORDS = config["keywords"]

# --- Gemini AI 初始化 ---
# 2. 從環境變數設定您的 Google API 金鑰
# 請確認您已經設定了 GOOGLE_API_KEY 環境變數
try:
    genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
except TypeError:
    print("錯誤：請先設定 GOOGLE_API_KEY 環境變數。")
    exit()


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

# ------------------- 函式修改重點 -------------------
def summarize_papers(papers, keyword):
    """用 Gemini AI 摘要 + 結構化 JSON"""
    # 3. 選擇要使用的 Gemini 模型
    model = genai.GenerativeModel('gemini-1.5-flash-latest') # 速度快，CP值高
    # model = genai.GenerativeModel('gemini-1.5-pro-latest') # 能力更強

    summaries = []
    for paper in papers:
        prompt = f"""
你是一個專業的醫學文獻解析AI助手。請將以下提供的 PubMed 論文內容，嚴格按照指定的 JSON 格式進行整理和輸出。

指定的 JSON 格式欄位包括：
- pmid: string
- title: string
- authors: string[]
- journal: string
- year: string
- doi: string
- abstract: string
- summary: string (請用 3–5 句流暢的中文，總結研究的背景、方法與主要發現)
- study_design: {{
    "inclusion_criteria": string[],
    "primary_outcome": {{ "name": string, "result": string }},
    "secondary_outcomes": {{ "name": string, "result": string }}[],
    "subgroup_analysis": {{ "subgroup": string, "result": string }}[]
}}
- conclusion: string (論文的主要結論)

規則：
1.  所有欄位都必須存在，如果論文摘要中沒有提到相關資訊，請在對應的 string 類型欄位中填入 "Not reported" 或在 array 類型欄位中填入空陣列 `[]`。
2.  在 "result" 欄位中，請盡可能包含具體的數據，例如：風險比 (HR)、勝算比 (OR)、信賴區間 (CI)、p-value 等。若文中未提及具體數值，請填 "Not reported"。
3.  最終輸出**只能是**一個完整的 JSON 物件，絕對不要在 JSON 的前後包含任何額外的文字、解釋或 markdown 標籤 (例如 ```json ... ```)。

論文內容：
{json.dumps(paper, ensure_ascii=False, indent=2)}
"""
        # 4. 呼叫 Gemini API
        response = model.generate_content(prompt)
        
        try:
            # 5. Gemini 的回覆在 .text 屬性，並先清除可能的 markdown 標籤
            cleaned_response = response.text.strip().replace("```json", "").replace("```", "")
            summary = json.loads(cleaned_response)
        except (json.JSONDecodeError, AttributeError) as e:
            print(f"PMID {paper.get('pmid', 'N/A')} 的 JSON 解析失敗: {e}")
            summary = {"error": "JSON parsing failed", "raw": response.text}
        
        summaries.append(summary)
        
    return {"keyword": keyword, "papers": summaries}
# ----------------------------------------------------

def send_email(report_json):
    """發送包含 JSON 報告的電子郵件"""
    msg = MIMEMultipart()
    msg["From"] = EMAIL_SENDER
    msg["To"] = EMAIL_RECEIVER
    msg["Subject"] = f"最新文獻摘要報告 (Gemini AI) - {datetime.now().strftime('%Y-%m-%d')}"

    # 將 JSON 美化後作為郵件內容
    body_text = json.dumps(report_json, indent=4, ensure_ascii=False)
    body = MIMEText(body_text, "plain", "utf-8")
    msg.attach(body)

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_SENDER, EMAIL_RECEIVER, msg.as_string())
        print("✅ 郵件已成功寄出！")
    except smtplib.SMTPException as e:
        print(f"❌ 郵件寄送失敗: {e}")


if __name__ == "__main__":
    keyword = input("請輸入要搜尋的 PubMed 關鍵字： ")
    if not keyword:
        print("關鍵字不得為空。")
    else:
        print(f"🔍 正在搜尋關鍵字 '{keyword}' 的相關文章...")
        pmids = search_pubmed(keyword, retmax=3) # 為了測試，先設定為 3 篇
        if not pmids:
            print("找不到相關文獻。")
        else:
            print(f"📄 找到了 {len(pmids)} 篇文章，正在抓取摘要...")
            papers = [fetch_abstract(pmid) for pmid in pmids]
            
            print("🤖 正在使用 Gemini AI 進行分析與摘要，請稍候...")
            result = summarize_papers(papers, keyword)
            
            print("寄送報告中...")
            send_email(result) # <-- 修正了變數名稱
