import os
import time
import requests
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY")

TOPICS = ["economy_macro", "economy_monetary", "economy_fiscal", "technology"]

for topic in TOPICS:
    print(f"Fetching {topic}...")
    url = f"https://www.alphavantage.co/query?function=NEWS_SENTIMENT&topics={topic}&apikey={API_KEY}"
    response = requests.get(url)
    data = response.json()
    
    for article in data["feed"][:3]:
     time.sleep(2)
     print(article["title"])