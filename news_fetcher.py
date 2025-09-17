import yfinance as yf
import finnhub
from textblob import TextBlob

API_KEY = os.getenv("API_KEY")
client = finnhub.Client(api_key=API_KEY)

def fetch_news_ticker(ticker):
    # Use yfinance's news fetching
    try:
        stock = yf.Ticker(ticker)
        news = client.company_news(ticker, _from='2025-09-01', to='2025-09-17')
        summaries = []
        for article in news[:5]:
            headline = article.get("title", "No Title")
            url = article.get("link", "#")
            blob = TextBlob(headline)
            sentiment = blob.sentiment.polarity
            summaries.append({
                "headline": headline,
                "url": url,
                "sentiment": sentiment
            })
        return summaries
    except Exception as e:
        return [{"error": str(e)}]

# To use: fetch_news("AAPL")
