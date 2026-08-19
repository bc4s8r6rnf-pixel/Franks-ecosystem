# Reference

Geometry of **RXWLES PRO** (© RXWLESfx, MPL-2.0), the indicator that draws the
zones this research targets. Recorded here from the indicator source so the
analyser can be matched to it exactly rather than eyeballed off a chart. Drop
the .pine file in this folder if you want the full source alongside it.

The facts the analyser is matched to:

```pine
srcHigh/srcLow   = the 21:00 New York hourly candle, read closed via [1]
r                = srcHigh - srcLow

Daily Zone Upper = srcHigh + r*2.5  ..  srcHigh + r*2.0
Daily Zone Lower = srcLow  - r*2.0  ..  srcLow  - r*2.5
Enigma Zone      = srcHigh .. srcLow

lane             = 00:00 New York the following day -> 00:00 the day after
```

So the projection is anchored on the **range boundaries**, not the midpoint
(`InpZoneMode = 2`), and the day the zones govern starts at midnight — two
hours after the source candle closes, not at the candle's close.
