def job(tickers):
    buy_alerts = []
    sell_alerts = []
    buy_symbols = []
    prices = {}
    failed = []
    total = skipped = 0

    for symbol in tickers:
        total += 1
        try:
            hist = fetch_history(symbol)
            if hist.empty:
                logger.info(f"No historical data for {symbol}, skipping.")
                skipped += 1
                continue
        except Exception as e:
            msg = str(e).lower()
            if any(k in msg for k in ["rate limit", "too many requests", "429"]):
                logger.warning(f"Rate limited on fetching history for {symbol}, retry delayed.")
                failed.append(symbol)
                continue
            if any(k in msg for k in ["delisted", "no data", "not found"]):
                logger.info(f"{symbol} delisted or no data, skipping.")
                skipped += 1
                continue
            logger.error(f"Error fetching history for {symbol}: {e}")
            skipped += 1
            continue

        hist = calculate_indicators(hist)
        sig, reason = generate_signal(hist)
        if not sig:
            continue

        try:
            rt_price = fetch_quote(symbol)
        except Exception as e:
            msg = str(e).lower()
            if any(k in msg for k in ["rate limit", "too many requests", "429"]):
                logger.warning(f"Rate limit on price for {symbol}, waiting then retrying.")
                time.sleep(60)
                try:
                    rt_price = fetch_quote(symbol)
                except Exception as e2:
                    logger.error(f"Failed second price fetch for {symbol}: {e2}")
                    rt_price = None
            else:
                logger.error(f"Error fetching price for {symbol}: {e}")
                rt_price = None

        if rt_price is None or rt_price != rt_price or rt_price <= 0:
            rt_price = hist["Close"].iloc[-1] if not hist.empty else None
        if rt_price is None or rt_price != rt_price or rt_price <= 0:
            logger.warning(f"Invalid price for {symbol}, skipping.")
            skipped += 1
            continue

        pe, mcap = fetch_fundamentals_safe(symbol)
        iv_hist = fetch_puts(symbol)
        iv_rank = iv_pct = None
        if iv_hist:
            iv_rank, iv_pct = calc_iv_rank_percentile(pd.Series([p["premium"] for p in iv_hist if p.get("premium") is not None]))

        cap_str = format_market_cap(mcap)
        pe_str = f"{pe:.1f}" if pe else "N/A"
        parts = [
            f"{symbol}: {sig} at ${rt_price:.2f}",
            reason,
            f"PE={pe_str}",
            f"MarketCap={cap_str}",
        ]
        if iv_rank is not None:
            parts.append(f"IV Rank={iv_rank:.2f}")
        if iv_pct is not None:
            parts.append(f"IV Percentile={iv_pct:.2f}")
        alert_line = ", ".join(parts)

        alert_data = {
            "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "ticker": symbol,
            "signal": sig,
            "price": rt_price,
            "rsi": hist["rsi"].iloc[-1] if "rsi" in hist.columns else None,
            "pe_ratio": pe,
            "market_cap": mcap,
            "iv_rank": iv_rank,
            "iv_percentile": iv_pct,
        }
        log_alert(alert_data)

        if sig == "BUY":
            buy_alerts.append(alert_line)
            buy_symbols.append(symbol)
            prices[symbol] = rt_price
            logger.info(f"Buy signal: {symbol}")
        else:
            sell_alerts.append(alert_line)
            logger.info(f"Sell signal: {symbol}")

    # Process options puts for buy signals with updated filtering logic
    puts_dir = "puts_data"
    os.makedirs(puts_dir, exist_ok=True)

    for sym in buy_symbols:
        puts_list = fetch_puts(sym)
        price = prices.get(sym)
        puts_list = calculate_custom_metrics(puts_list, price)

        filtered_puts = [
            p for p in puts_list
            if p.get("strike") is not None
               and price
               and p["strike"] < price
               and p.get("custom_metric")
               and p["custom_metric"] >= 10
        ]

        grouped = defaultdict(list)
        for put in filtered_puts:
            grouped[put["expiration"]].append(put)

        selected_puts = []
        for exp, group in grouped.items():
            max_premium_put = max(group, key=lambda x: x.get("premium_percent", -float('inf')))
            max_metric_put = max(group, key=lambda x: x.get("custom_metric", -float('inf')))
            if max_premium_put == max_metric_put:
                selected_puts.append(max_premium_put)
            else:
                selected_puts.extend([max_premium_put, max_metric_put])

        puts_texts = []
        for p in selected_puts:
            strike = f"{p['strike']:.1f}" if isinstance(p['strike'], (int, float)) else "N/A"
            premium = f"{p['premium']:.2f}" if isinstance(p['premium'], (int, float)) else "N/A"
            metric = f"{p['custom_metric']:.1f}%" if p.get('custom_metric') else "N/A"
            delta = f"{p.get('delta_percent', 'N/A'):.1f}%" if p.get('delta_percent') else "N/A"
            prem_pct = f"{p.get('premium_percent', 'N/A'):.1f}%" if p.get('premium_percent') else "N/A"
            puts_texts.append(
                f"expiration={p['expiration']}, strike={strike}, premium={premium}, stock_price={price:.2f}, "
                f"custom_metric={metric}, delta_percent={delta}, premium_percent={prem_pct}"
            )

        puts_block = "\n" + "\n------\n".join(puts_texts)

        for idx, alert_line in enumerate(buy_alerts):
            if alert_line.startswith(sym):
                buy_alerts[idx] += puts_block
                break

        puts_json_path = os.path.join(puts_dir, f"{sym}_puts_7weeks.json")
        try:
            with open(puts_json_path, "w") as fp:
                json.dump(selected_puts, fp, indent=2)
            logger.info(f"Saved puts data for {sym}")
        except Exception as e:
            logger.error(f"Failed to save puts json for {sym}: {e}")

    return buy_symbols, buy_alerts, sell_alerts, failed
