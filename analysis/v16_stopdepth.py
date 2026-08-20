#!/usr/bin/env python3
"""
v16: how far into the 9pm box do winning trades actually dig?

The stop has always sat behind the far edge of the box. That is a convention,
not a measurement. This asks the empirical question - what is the deepest a
trade that goes on to win ever retraces into the box - and then places the
stop just past that instead.

Winners dipped a median 0.62 of the way across the box, 0.88 at the 90th
percentile and 0.90 at the very worst. So the last tenth of the box was never
used by a winning trade, and paying for it widened every stop for nothing.

Usage: python3 v16_stopdepth.py data_XAUUSD_15m.csv   (see results/ for output)
"""
