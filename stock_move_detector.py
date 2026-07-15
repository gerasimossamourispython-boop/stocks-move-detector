# stock_move_detector.py
# GitHub Actions compatible version of Colab Stock Move Detector

import os
import sys
import logging
import urllib.parse
from datetime import datetime

import pandas as pd
import numpy as np
import yfinance as yf
import feedparser
import requests


# =========================
# LOGGING
# =========================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("stock_detector.log")
    ]
)

logger = logging.getLogger(__name__)


# =========================
# CONFIG
# =========================

DAILY_STD_DEV_MULTIPLIER = 3
VOLUME_AVG_MULTIPLIER = 2

HISTORY_PERIOD = "1y"
INTRADAY_INTERVAL = "5m"
NEWS_PER_TICKER = 3

DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")


# =========================
# WATCHLIST
# =========================

def get_exhaustive_watchlist():

    tickers = ["LCID"]

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    try:
        us_url = (
            "https://raw.githubusercontent.com/"
            "rreichel3/US-Stock-Symbols/main/all/all_tickers.txt"
        )

        response = requests.get(
            us_url,
            headers=headers,
            timeout=20
        )

        all_us = [
            t.strip().upper()
            for t in response.text.split("\n")
            if t.strip()
        ]

        tickers.extend(all_us)

        logger.info(
            f"Loaded {len(all_us)} US tickers"
        )

    except Exception as e:
        logger.warning(
            f"US ticker download failed: {e}"
        )


    try:
        ftse_url = (
            "https://en.wikipedia.org/wiki/FTSE_100_Index"
        )

        html = requests.get(
            ftse_url,
            headers=headers,
            timeout=20
        ).text


        ftse = pd.read_html(html)[4]["EPIC"].tolist()

        tickers.extend(
            [
                f"{t}.L"
                for t in ftse
            ]
        )

        logger.info(
            f"Loaded {len(ftse)} FTSE tickers"
        )

    except Exception as e:
        logger.warning(
            f"FTSE download failed: {e}"
        )


    tickers.extend(
        [
            "^FTSE",
            "^N225",
            "DIA",
            "QQQ",
            "SPY"
        ]
    )


    return list(set(tickers))



WATCHLIST = get_exhaustive_watchlist()


# =========================
# STOCK SCANNER
# =========================

def scan_watchlist(tickers=WATCHLIST):

    rows = []

    logger.info(
        f"Scanning {len(tickers)} tickers..."
    )


    for tkr in tickers:

        try:

            t = yf.Ticker(tkr)

            info = t.info


            hist_data = t.history(
                period=HISTORY_PERIOD
            )


            if hist_data.empty:
                continue


            hist_data["Daily_Return"] = (
                hist_data["Close"]
                .pct_change()
            )


            std_dev_returns = (
                hist_data["Daily_Return"]
                .std()
            )


            avg_volume = (
                hist_data["Volume"]
                .mean()
            )


            current_intraday_data = t.history(
                period="1d",
                interval=INTRADAY_INTERVAL
            )


            if current_intraday_data.empty:
                continue


            prev_close = info.get(
                "previousClose"
            )


            if prev_close is None:

                prev_close = float(
                    current_intraday_data["Close"]
                    .iloc[0]
                )


            last_price = float(
                current_intraday_data["Close"]
                .iloc[-1]
            )


            daily_pct = (
                last_price - prev_close
            ) / prev_close


            current_volume = (
                current_intraday_data["Volume"]
                .sum()
            )


            if (
                std_dev_returns > 0
                and abs(daily_pct)
                >= DAILY_STD_DEV_MULTIPLIER
                * std_dev_returns

                and avg_volume > 0
                and current_volume
                >= VOLUME_AVG_MULTIPLIER
                * avg_volume
            ):


                rows.append(

                    {
                        "ticker": tkr,

                        "mkt_cap":
                            f"{info.get('marketCap',0):,.0f}",

                        "pe_ratio":
                            round(
                                info.get(
                                    "trailingPE",
                                    0
                                ),
                                2
                            ),

                        "ev_ebitda":
                            round(
                                info.get(
                                    "enterpriseToEbitda",
                                    0
                                ),
                                2
                            ),

                        "last_price":
                            round(
                                last_price,
                                2
                            ),

                        "pct_daily":
                            round(
                                daily_pct * 100,
                                2
                            ),

                        "current_volume":
                            int(current_volume),

                        "avg_volume":
                            int(avg_volume),

                        "std_dev_daily_return":
                            round(
                                std_dev_returns * 100,
                                2
                            ),

                        "flag":
                            "volatility_volume"
                    }

                )


                logger.info(
                    f"FLAGGED {tkr}"
                )


        except Exception as e:

            logger.warning(
                f"{tkr} failed: {e}"
            )

            continue


    return pd.DataFrame(rows)
  # =========================
# NEWS FUNCTIONS
# =========================

def get_news_google(query, max_results=NEWS_PER_TICKER):

    try:

        url = (
            "https://news.google.com/rss/search?"
            f"q={urllib.parse.quote(query)}"
            "&hl=en-US&gl=US&ceid=US:en"
        )


        feed = feedparser.parse(url)


        articles = []


        for entry in feed.entries[:max_results]:

            articles.append(
                {
                    "title": entry.get("title"),
                    "link": entry.get("link"),
                    "published": entry.get("published"),
                    "source": "Google News"
                }
            )


        return articles


    except Exception as e:

        logger.warning(
            f"Google News error for {query}: {e}"
        )

        return []



def get_news_yfinance(ticker, max_results=NEWS_PER_TICKER):

    articles = []


    try:

        raw = yf.Ticker(ticker).news or []


        for item in raw[:max_results]:

            content = item.get(
                "content",
                item
            )


            link = None


            if isinstance(
                content.get("clickThroughUrl"),
                dict
            ):

                link = (
                    content["clickThroughUrl"]
                    .get("url")
                )


            link = (
                link
                or content.get("link")
            )


            articles.append(
                {
                    "title":
                        content.get("title"),

                    "link":
                        link,

                    "published":
                        content.get("pubDate")
                        or item.get(
                            "providerPublishTime"
                        ),

                    "source":
                        "Yahoo Finance"
                }
            )


    except Exception as e:

        logger.warning(
            f"{ticker} Yahoo news error: {e}"
        )


    return articles



# =========================
# DISCORD
# =========================

def send_discord(message):

    if not DISCORD_WEBHOOK:

        logger.warning(
            "Discord webhook missing"
        )

        return


    try:

        response = requests.post(
            DISCORD_WEBHOOK,
            json={
                "content": message
            },
            timeout=15
        )


        if response.status_code >= 300:

            logger.warning(
                f"Discord failed: {response.text}"
            )


        else:

            logger.info(
                "Discord message sent"
            )


    except Exception as e:

        logger.error(
            f"Discord error: {e}"
        )



# =========================
# REPORT BUILDER
# =========================

def build_report(tickers=WATCHLIST):

    flagged = scan_watchlist(tickers)


    if flagged.empty:

        logger.info(
            "No stocks crossed thresholds"
        )

        send_discord(
            f"📊 Stock Move Detector\n"
            f"{datetime.now()}\n\n"
            "No stocks crossed thresholds."
        )

        return flagged



    logger.info(
        f"{len(flagged)} stocks detected"
    )


    message = (
        "🚨 **Stock Move Detector Alert** 🚨\n"
        f"Time: {datetime.now()}\n\n"
    )


    for _, row in flagged.iterrows():


        ticker = row["ticker"]


        message += (

            f"📈 **{ticker}**\n"
            f"Price: ${row['last_price']}\n"
            f"Daily Move: {row['pct_daily']}%\n"
            f"Volume: {row['current_volume']:,}\n"
            f"Average Volume: {row['avg_volume']:,}\n"
            f"Std Dev Move: {row['std_dev_daily_return']}%\n\n"

        )


        articles = (
            get_news_google(ticker)
            or
            get_news_yfinance(ticker)
        )


        if articles:

            message += "📰 News:\n"


            for article in articles:

                message += (

                    f"• {article['title']}\n"
                    f"{article['link']}\n"

                )


        else:

            message += (
                "No recent news found.\n"
            )


        message += "\n"


    send_discord(message)


    return flagged

# =========================
# MAIN EXECUTION
# =========================

if __name__ == "__main__":

    try:

        logger.info(
            "Starting Stock Move Detector"
        )


        report = build_report(
            WATCHLIST
        )


        logger.info(
            "Scan completed successfully"
        )


        if not report.empty:

            logger.info(
                report.to_string()
            )


        logger.info(
            f"Total companies scanned: {len(WATCHLIST)}"
        )


    except Exception as e:

        logger.exception(
            f"Fatal error: {e}"
        )

        sys.exit(1)
