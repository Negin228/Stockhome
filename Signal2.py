# .github/workflows/signals.yml
name: Signals

on:
  schedule:
    - cron: '30 13 * * 1-5'
  workflow_dispatch:

jobs:
  run-signals:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      actions: read

    env:
      PYTHONUNBUFFERED: "1"
      STATE_DIR: state
      # your secrets here
      SMTP_SERVER: smtp.gmail.com
      SMTP_PORT: 587
      EMAIL_SENDER: ${{ secrets.EMAIL_SENDER }}
      EMAIL_PASSWORD: ${{ secrets.EMAIL_PASSWORD }}
      EMAIL_RECEIVER: ${{ secrets.EMAIL_RECEIVER }}
      # any API keys you use:
      FINNHUB_API_KEY: ${{ secrets.FINNHUB_API_KEY }}

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install deps
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      # Restore latest cache snapshot (if any). This pulls data/logs/state from prior runs.
      - name: Restore cache
        id: restore-cache
        uses: actions/cache/restore@v4
        with:
          path: |
            data
            logs
            state
          key: signal-state-${{ runner.os }}-none
          restore-keys: |
            signal-state-${{ runner.os }}-
            signal-state-

      - name: Ensure folders exist
        run: |
          mkdir -p data logs state

      - name: Run the script
        run: |
          python Signal.py --email-type hourly
        # or whatever args you use

      # (Nice to have) See outputs for this run
      - name: Upload artifacts
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: signals-outputs
          path: |
            data
            logs
            state

      # Save a fresh cache snapshot for the *next* run
      - name: Save updated cache
        if: always()
        uses: actions/cache/save@v4
        with:
          path: |
            data
            logs
            state
          key: signal-state-${{ runner.os }}-${{ github.run_id }}
