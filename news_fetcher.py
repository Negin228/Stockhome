import os
import datetime
import json
import yfinance as yf
import finnhub
from textblob import TextBlob
from newspaper import Article
from transformers import pipeline


API_KEY = os.getenv("API_KEY")
finnhub_client = finnhub.Client(api_key=API_KEY)

summarizer = pipeline("summarization", model="facebook/bart-large-cnn")

def get_article_text(url):
        try:
                article = Article(url)
                article.download()
                article.parse()
                return article.text
        except Exception as e:
                return ""
                            
def summarize_article_text(article_text):
        if not article_text.strip():
                return ""
        result = summarizer(article_text, max_length=60, min_length=10, do_sample=False)
        return result[0]['summary_text'].strip()

def fetch_news_ticker(ticker):
        summaries = []
        # Use yfinance's news fetching
        #from_date = (datetime.datetime.now() - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
        #to_date = datetime.datetime.now().strftime("%Y-%m-%d")
        #news = finnhub_client.company_news(ticker, _from=from_date, to=to_date)
        try:
                ticker_obj = yf.Ticker(ticker)
                news_items = ticker_obj.news  # List of dicts with real news links!
                if not news_items or not isinstance(news_items, list):
                        # Could be None, an error, or not a list of dicts
                        return [{"error": "No news found from yfinance for ticker: " + str(ticker)}]
                for item in news_items[:5]:
                    print(item.keys())
                    print(json.dumps(item, indent=2))  # show full available fields
                    meta = item.get("content", {})
                    headline = item.get("title") or meta.get("title", "")
                    summary = item.get("summary") or meta.get("summary", "")
                    url = (
                        item.get("url") or
                        (meta.get("canonicalUrl") or {}).get("url")
                        or (meta.get("clickThroughUrl") or {}).get("url")
                        or "")
                    article_text = get_article_text(url)
                    if article_text:
                        ai_summary = summarize_article_text(article_text)
                    else:
                        #ai_summary = item.get("summary") or item.get("title") or ""
                        ai_summary = summary or headline
                    blob = TextBlob(headline)
                    sentiment = blob.sentiment.polarity
                    #text = ""
                        
                    summaries.append({
                        "headline": headline,
                        "url": url,
                        "sentiment": sentiment,
                        "summary": ai_summary,
                        #"summary": summary if summary else headline,
                        "article_text": article_text[:500]})
                print("Fetched news for", ticker, ":", news_items)
                return summaries
        except Exception as e:
                return [{"error": str(e)}]
