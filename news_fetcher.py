import os
import yfinance as yf
from textblob import TextBlob
from newspaper import Article
from transformers import pipeline

API_KEY = os.getenv("API_KEY")
summarizer = pipeline("summarization", model="facebook/bart-large-cnn")

def get_article_text(url):
    try:
        article = Article(url)
        article.download()
        article.parse()
        return article.text
    except Exception:
        return ""

def summarize_article_text(article_text):
    if not article_text.strip():
        return ""
    result = summarizer(article_text, max_length=60, min_length=10, do_sample=False)
    return result[0]['summary_text'].strip()

def fetch_news_ticker(ticker):
    summaries = []
    try:
        ticker_obj = yf.Ticker(ticker)
        news_items = ticker_obj.news
        if not news_items or not isinstance(news_items, list):
            print(f"[DEBUG] news_items not a list or empty for {ticker}: {news_items}")
            return [{"error": f"No news found from yfinance for ticker: {ticker}"}]
        for item in news_items[:5]:
            try:
                meta = item.get("content", {})
                headline = str(meta.get("title", ""))
                summary = str(meta.get("summary", ""))
                
                # Handle canonicalUrl and clickThroughUrl safely (dict or str)
                canonical_url = meta.get("canonicalUrl")
                click_url = meta.get("clickThroughUrl")
                url = ""
                for key in ("canonicalUrl", "clickThroughUrl"):
                    field = meta.get(key)
                    if isinstance(field, dict):
                        url = field.get("url", "")
                    elif isinstance(field, str):
                        url = field
                    if url:
                        break

                article_text = get_article_text(url)
                if article_text:
                    ai_summary = summarize_article_text(article_text)
                else:
                    ai_summary = summary or headline
                blob = TextBlob(headline)
                sentiment = blob.sentiment.polarity
                summaries.append({
                    "headline": headline,
                    "url": url,
                    "sentiment": sentiment,
                    "summary": ai_summary,
                    "article_text": article_text[:500]
                })
            except Exception as per_item_e:
                print(f"[DEBUG] Skipped bad news item for {ticker}: {per_item_e}")
        print("Fetched news for", ticker, ":", news_items)
        return summaries
    except Exception as e:
        print(f"Exception in fetch_news_ticker for {ticker}:", e)
        return [{"error": str(e)}]
