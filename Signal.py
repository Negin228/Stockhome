def job():
    buy_alerts = []
    sell_alerts = []
    buy_tickers = []
    total, skipped = 0, 0

    for symbol in tickers:
        total += 1
        hist = fetch_cached_history(symbol)
        if hist.empty:
            skipped += 1
            continue

        hist = calculate_indicators(hist)
        sig, reason, rsi, price = generate_rsi_signal(hist)

        try:
            rt_price = finnhub_client.quote(symbol).get("c", price)
        except Exception:
            rt_price = price

        pe, mcap = fetch_fundamentals(symbol)
        iv_hist = fetch_option_iv_history(symbol)
        iv_rank, iv_pct = (None, None)
        if not iv_hist.empty:
            iv_rank, iv_pct = calc_iv_rank_percentile(iv_hist["IV"])

        if sig:
            line_parts = [
                f"{symbol}: {sig} at ${rt_price:.2f}",
                reason,
                f"PE={pe if pe else 'N/A'}",
                f"MarketCap={mcap if mcap else 'N/A'}"
            ]
            if iv_rank is not None:
                line_parts.append(f"IV Rank={iv_rank}")
                line_parts.append(f"IV Percentile={iv_pct}")

            line = ", ".join(line_parts)

            alert_entry = {
                "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "ticker": symbol,
                "signal": sig,
                "price": rt_price,
                "rsi": round(rsi, 2) if rsi else None,
                "pe_ratio": pe,
                "market_cap": mcap,
                "iv_rank": iv_rank,
                "iv_percentile": iv_pct,
            }
            log_alert(alert_entry)

            if sig == "BUY":
                buy_alerts.append(line)
                buy_tickers.append(symbol)
                logger.info(f"Added buy ticker: {symbol}")  # Debug log
            else:
                sell_alerts.append(line)

    logger.info(f"Total buy tickers collected: {len(buy_tickers)}")
    if buy_tickers:
        buy_file_path = os.path.join(config.DATA_DIR, "buy_signals.txt")
        try:
            with open(buy_file_path, "w") as file:
                for ticker in buy_tickers:
                    file.write(ticker + "\n")
            logger.info(f"Saved buy tickers to {buy_file_path}")
        except Exception as e:
            logger.error(f"Failed to save buy_signals.txt: {e}")
    else:
        logger.info("No buy tickers found to save.")

    if not buy_alerts and not sell_alerts:
        logger.info("No alerts. Processed=%d, Skipped=%d, Alerts=0", total, skipped)
        print("No alerts found.")
        return

    email_body = "RSI Alerts Summary:\n\n"
    if buy_alerts:
        email_body += f"🔹 Buy Signals (RSI < {config.RSI_OVERSOLD}):\n"
        email_body += "\n".join(f"  - {alert}" for alert in buy_alerts) + "\n\n"
    if sell_alerts:
        email_body += f"🔸 Sell Signals (RSI > {config.RSI_OVERBOUGHT}):\n"
        email_body += "\n".join(f"  - {alert}" for alert in sell_alerts) + "\n"

    logger.info("SUMMARY: Processed=%d, Skipped=%d, Alerts=%d", total, skipped, len(buy_alerts) + len(sell_alerts))

    print(email_body)
    send_email("StockHome Trading Alerts", email_body)
