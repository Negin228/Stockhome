import config
import argparse

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--excluded", type=str, default="",
                        help="Comma-separated list of tickers to exclude")
    parser.add_argument("--email-type", type=str, default="second")
    args = parser.parse_args()

    excluded = set(args.excluded.split(",")) if args.excluded else set()
    tickers_to_run = [t for t in config.tickers if t not in excluded]

    import Signal
    # Assuming Signal.py exposes job or main function accepting tickers list and email_type
    buy_tickers = Signal.job(tickers_to_run)

    # Similar emailing and tracking logic in Signal.py main applies here

if __name__ == "__main__":
    main()
