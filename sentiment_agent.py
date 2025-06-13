import logging
import datetime
import json
import os
from newsapi import NewsApiClient
from textblob import TextBlob

class SentimentAgent:
    """
    An agent responsible for fetching news and determining market sentiment.
    It now includes a local caching mechanism to avoid re-fetching news.
    """
    def __init__(self, config):
        self.config = config
        self.newsapi = NewsApiClient(api_key=config['news_api']['api_key'])
        self.cache_dir = "news_cache"
        os.makedirs(self.cache_dir, exist_ok=True)
        self.top_constituents = [
            "Reliance Industries", "HDFC Bank", "ICICI Bank", "Infosys",
            "Larsen & Toubro", "TCS", "Bharti Airtel", "ITC", "Kotak Mahindra Bank",
            "Hindustan Unilever", "RBI", "NIFTY", "Attack"
        ]

    def _get_news_articles(self):
        """
        Fetches news from cache if available, otherwise from the API.
        """
        today_str = datetime.date.today().isoformat()
        cache_file_path = os.path.join(self.cache_dir, f"news_{today_str}.json")

        # Check if cached news for today exists
        if os.path.exists(cache_file_path):
            logging.info(f"SentimentAgent: Loading today's news from cache: {cache_file_path}")
            with open(cache_file_path, 'r') as f:
                return json.load(f)
        
        # If no cache, fetch from API
        logging.info("SentimentAgent: No cache found. Fetching fresh news from API...")
        try:
            query = f"{self.config['trading_flags']['underlying_instrument']} OR " + " OR ".join(self.top_constituents)
            from_date = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
            
            top_headlines = self.newsapi.get_everything(
                q=query,
                language='en',
                sort_by='relevancy',
                page_size=100, # Fetch a few more to allow for filtering
                from_param=from_date
            )

            # Save the fresh news to cache for future runs today
            with open(cache_file_path, 'w') as f:
                json.dump(top_headlines, f)
            logging.info(f"SentimentAgent: Saved fresh news to cache: {cache_file_path}")
            
            return top_headlines

        except Exception as e:
            logging.error(f"SentimentAgent: Could not fetch news from API: {e}")
            return None


    def get_market_sentiment(self):
        """
        Calculates average sentiment from news and returns the market bias.
        """
        logging.info("SentimentAgent: Determining market sentiment...")
        
        top_headlines = self._get_news_articles()

        if not top_headlines or not top_headlines.get('articles'):
            logging.warning("SentimentAgent: No news articles found. Defaulting to Neutral.")
            return "Neutral"

        sentiment_scores = []
        logging.info("SentimentAgent: Analyzing top headlines...")
        for article in top_headlines['articles']:
            title = article.get('title', '')
            description = article.get('description', '')
            
            # Skip articles that are just "[Removed]"
            if not title or title == "[Removed]":
                continue

            content = f"{title}. {description}"
            analysis = TextBlob(content)
            sentiment_scores.append(analysis.sentiment.polarity)
            logging.info(f"  - Headline: '{title[:60]}...' | Polarity: {analysis.sentiment.polarity:.2f}")

        if not sentiment_scores:
            logging.warning("SentimentAgent: No valid headlines to analyze. Defaulting to Neutral.")
            return "Neutral"

        average_sentiment = sum(sentiment_scores) / len(sentiment_scores)
        logging.info(f"SentimentAgent: Average sentiment score is {average_sentiment:.3f}")

        if average_sentiment > 0.05:
            return "Bullish"
        elif average_sentiment < -0.05:
            return "Bearish"
        else:
            return "Neutral"

