//+------------------------------------------------------------------+
//|                                          VolatilityScalper.mq5   |
//|                                                                  |
//|  A 24/7 volatility-gated scalper built for TRADE SHAPE, not for  |
//|  a headline win rate: many small wins, the occasional small loss.|
//|                                                                  |
//|  DESIGN NOTES (full reasoning in docs/VOLATILITY_SCALPER_DESIGN) |
//|                                                                  |
//|  1. Mean reversion, not momentum. High win rates come from       |
//|     fading over-extension (price usually reverts); momentum      |
//|     gives the opposite profile - few wins, large winners. We     |
//|     fade the pullback but only WITH the higher-timeframe trend,  |
//|     so the reversion has a tailwind instead of fighting one.     |
//|                                                                  |
//|  2. The loss distribution is truncated deliberately. A partial   |
//|     at TP1 plus an immediate move to break-even converts a large |
//|     share of would-be losers into scratches. That, not a tight   |
//|     take-profit, is what produces the "lots of small wins" shape.|
//|                                                                  |
//|  3. Volatility is gated in a BAND, not a floor. Too little and   |
//|     there is nothing to capture; too much and it is news/panic - |
//|     spreads gap and stops slip. Both tails are filtered out.     |
//|                                                                  |
//|  4. Runs continuously and lets the gates pick the hours. The     |
//|     baseline is measured across all hours over several days, so  |
//|     dead Asian hours cannot look "volatile relative to Asia".    |
//|                                                                  |
//|  5. Stops and targets are attached at order-send, so the broker  |
//|     honours them even if the terminal disconnects. The EA only   |
//|     manages break-even, the trail, and the time stop.            |
//|                                                                  |
//|  6. The edge a scalper must supply over a coin flip is           |
//|     cost/(TP+SL) - so targets are sized in ATR, never in pips or |
//|     dollars, and never tighter than the stop.                    |
//|                                                                  |
//|  Start with InpDryRun = true. It evaluates and logs every signal |
//|  without sending a single order.                                 |
//+------------------------------------------------------------------+
#property copyright "Franks Ecosystem"
#property version   "1.00"
#property strict

#include <Trade\Trade.mqh>

//==================================================================//
//  INPUTS                                                          //
//==================================================================//
input group "=== General ==="
input ulong  InpMagic         = 20260819;   // Magic number
input string InpComment       = "VolScalp"; // Order comment
input bool   InpDryRun        = true;       // Log signals only, place NO orders
input bool   InpVerboseLog    = true;       // Log why each bar was rejected

input group "=== Timeframes & EMAs ==="
input ENUM_TIMEFRAMES InpTrendTF  = PERIOD_H1;  // Trend EMA timeframe (directional bias)
input int    InpTrendEma      = 50;         // Trend EMA period - decides which side is allowed
input ENUM_TIMEFRAMES InpZoneTF   = PERIOD_M5;  // Close EMA / structure timeframe
input int    InpCloseEma      = 21;         // Close EMA period - price must pull back past this
input ENUM_TIMEFRAMES InpEntryTF  = PERIOD_M1;  // Trigger timeframe (rejection confirmation)

input group "=== Volatility gate (the permission filter) ==="
input int    InpAtrPeriod     = 14;         // ATR period
input int    InpBaselineDays  = 5;          // Days of all-hours history for the ATR baseline
input double InpVolMin        = 0.80;       // Min ATR / baseline - below this there is nothing to catch
input double InpVolMax        = 2.50;       // Max ATR / baseline - above this it is news, spreads gap
input double InpMaxSpreadAtr  = 0.25;       // Reject if spread > this x ATR(zone TF)
input double InpMaxSpreadPips = 3.0;        // Absolute spread ceiling (pips)

input group "=== Regime classifier ==="
input int    InpErPeriod      = 20;         // Bars for the Kaufman Efficiency Ratio
input double InpErTrend       = 0.35;       // ER above this = trending -> pullback mode
input double InpErRange       = 0.15;       // ER below this = clean range -> fade mode
                                            // between the two = chop -> stand down
input double InpTrendSlopeAtr = 0.15;       // Min |EMA slope| over 10 bars, in ATR, to call it a trend

input group "=== Entry ==="
input int    InpRsiPeriod     = 7;          // RSI period on the entry TF (over-extension)
input double InpRsiLong       = 35.0;       // Long needs RSI below this (pullback is stretched)
input double InpRsiShort      = 65.0;       // Short needs RSI above this
input bool   InpNeedRejection = true;       // Require a rejection bar before firing
input double InpRejWickPct    = 40.0;       // Rejection: wick against trade as % of bar range
input double InpKeltnerMult   = 1.6;        // Range-mode band width (x ATR from the close EMA)
input int    InpLadderLegs    = 3;          // Orders per batch (netting accounts force 1)
input double InpLadderDepthAtr= 0.45;       // Ladder spread across this much ATR

input group "=== Exits ==="
input double InpStopAtr       = 1.30;       // Stop distance (x ATR on the zone TF)
input double InpTp1Atr        = 1.00;       // First target (x ATR) - the "small win"
input double InpTp2Atr        = 2.50;       // Runner target (x ATR)
input int    InpTp1Legs       = 2;          // How many of the ladder legs take the early TP1
input bool   InpUseBreakEven  = true;       // Move stop to break-even once TP1 is banked
input double InpBeBufferAtr   = 0.05;       // Break-even buffer (x ATR) beyond entry
input bool   InpUseTrail      = true;       // Trail the runner after break-even
input double InpTrailAtr      = 1.00;       // Trail distance (x ATR)
input int    InpTimeStopMin   = 45;         // Flatten a trade going nowhere after N minutes (0 = off)
input double InpTimeStopMinR  = 0.25;       // "Going nowhere" = below this R when the clock expires

input group "=== Risk & sizing ==="
input double InpRiskPercent   = 0.75;       // Risk per BATCH (% of equity) - split across the legs
input double InpMaxLotCap     = 5.00;       // Absolute lot ceiling per leg
input double InpDailyMaxLossPct = 3.0;      // Stop for the day after this % equity loss (0 = off)
input int    InpMaxConsecLoss = 4;          // Pause after this many losing batches in a row
input int    InpPauseMin      = 60;         // Pause length after the streak (minutes)
input bool   InpUseDerisk     = true;       // Cut risk % as drawdown from the high-water mark grows
input double InpDeriskDD1     = 5.0;        // Beyond this % DD -> half risk
input double InpDeriskDD2     = 10.0;       // Beyond this % DD -> quarter risk
input double InpDeriskStop    = 15.0;       // Beyond this % DD -> stop trading entirely

input group "=== Time gates (server time) ==="
input bool   InpBlockRollover = true;       // Block the daily rollover spread blowout
input int    InpRolloverHour  = 0;          // Server hour of rollover (00:00 on most GMT+2/+3 brokers)
input int    InpRolloverPadMin= 20;         // Block +/- this many minutes around it
input bool   InpBlockWeekend  = true;       // No Friday-close or Sunday-open trading
input int    InpFridayEndHour = 20;         // Stop entries Friday at this server hour
input int    InpSundayStartHr = 2;          // No entries before this server hour on Sunday
input bool   InpUseNewsFilter = true;       // Block around high-impact calendar events
input int    InpNewsMinsBefore= 15;         // Blackout minutes before an event
input int    InpNewsMinsAfter = 15;         // Blackout minutes after an event

//==================================================================//
//  GLOBALS                                                         //
//==================================================================//
CTrade   trade;

int      hTrendEma = INVALID_HANDLE;
int      hCloseEma = INVALID_HANDLE;
int      hAtrZone  = INVALID_HANDLE;
int      hRsiEntry = INVALID_HANDLE;

double   g_pip        = 0.0;      // price change of one pip
double   g_pipValue   = 0.0;      // account currency per pip per 1.0 lot
bool     g_hedging    = false;    // hedging account? (netting collapses the ladder)
long     g_stopsLevel = 0;        // broker minimum stop distance, in points

datetime g_lastBar    = 0;        // last processed entry-TF bar
datetime g_dayStart   = 0;        // start of the current trading day
double   g_dayStartEq = 0.0;      // equity at the start of the day
double   g_highWater  = 0.0;      // account high-water mark
int      g_consecLoss = 0;        // consecutive losing batches
datetime g_pauseUntil = 0;        // paused until this time
double   g_atrBaseline= 0.0;      // cached median ATR
datetime g_baselineAt = 0;        // when the baseline was last rebuilt

// Batch state. A batch is one ladder of legs treated as a single position
// for risk purposes: it is sized as a unit and scored as a unit.
bool     g_batchOpen  = false;
int      g_batchDir   = 0;
double   g_batchEntry = 0.0;      // leg 0 reference price (deeper legs fill better)
double   g_batchRisk  = 0.0;      // stop distance in price for the batch
double   g_batchStartEq = 0.0;    // equity when the batch opened - scores the batch
bool     g_batchBE    = false;    // break-even already applied?

#define MODE_NONE   0
#define MODE_TREND  1
#define MODE_RANGE  2

//==================================================================//
//  INIT / DEINIT                                                   //
//==================================================================//
int OnInit()
{
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetTypeFillingBySymbol(_Symbol);
   trade.SetDeviationInPoints(20);

   hTrendEma = iMA(_Symbol, InpTrendTF, InpTrendEma, 0, MODE_EMA, PRICE_CLOSE);
   hCloseEma = iMA(_Symbol, InpZoneTF,  InpCloseEma, 0, MODE_EMA, PRICE_CLOSE);
   hAtrZone  = iATR(_Symbol, InpZoneTF, InpAtrPeriod);
   hRsiEntry = iRSI(_Symbol, InpEntryTF, InpRsiPeriod, PRICE_CLOSE);

   if(hTrendEma == INVALID_HANDLE || hCloseEma == INVALID_HANDLE ||
      hAtrZone  == INVALID_HANDLE || hRsiEntry == INVALID_HANDLE)
   {
      Print("FATAL: could not create indicator handles");
      return INIT_FAILED;
   }

   // A pip is 10 points on 5/3-digit feeds, 1 point otherwise.
   int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   g_pip = (digits == 5 || digits == 3) ? 10 * _Point : _Point;

   double tickValue = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tickSize  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   g_pipValue = (tickSize > 0.0) ? tickValue * (g_pip / tickSize) : 0.0;
   if(g_pipValue <= 0.0)
   {
      Print("FATAL: could not resolve pip value for ", _Symbol);
      return INIT_FAILED;
   }

   ENUM_ACCOUNT_MARGIN_MODE mm =
      (ENUM_ACCOUNT_MARGIN_MODE)AccountInfoInteger(ACCOUNT_MARGIN_MODE);
   g_hedging = (mm == ACCOUNT_MARGIN_MODE_RETAIL_HEDGING);

   g_stopsLevel = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);

   if(InpStopAtr <= 0.0 || InpTp1Atr <= 0.0 || InpTp2Atr <= 0.0)
   {
      Print("FATAL: InpStopAtr / InpTp1Atr / InpTp2Atr must all be > 0");
      return INIT_FAILED;
   }
   if(InpTp1Atr >= InpStopAtr * 2.5)
      Print("WARNING: TP1 is far beyond the stop - expect a much lower win rate than intended");
   if(InpLadderLegs < 1 || InpTp1Legs < 0 || InpTp1Legs > InpLadderLegs)
   {
      Print("FATAL: need InpLadderLegs >= 1 and 0 <= InpTp1Legs <= InpLadderLegs");
      return INIT_FAILED;
   }

   g_highWater  = AccountInfoDouble(ACCOUNT_EQUITY);
   g_dayStartEq = g_highWater;
   g_dayStart   = TodayStart();

   PrintFormat("VolatilityScalper init | %s | pip=%.5f pipValue=%.2f | %s account | stopsLevel=%d pts%s",
               _Symbol, g_pip, g_pipValue,
               g_hedging ? "HEDGING" : "NETTING (ladder collapses to 1 leg)",
               (int)g_stopsLevel,
               InpDryRun ? " | *** DRY RUN - no orders will be sent ***" : "");
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   if(hTrendEma != INVALID_HANDLE) IndicatorRelease(hTrendEma);
   if(hCloseEma != INVALID_HANDLE) IndicatorRelease(hCloseEma);
   if(hAtrZone  != INVALID_HANDLE) IndicatorRelease(hAtrZone);
   if(hRsiEntry != INVALID_HANDLE) IndicatorRelease(hRsiEntry);
}

//==================================================================//
//  MAIN LOOP                                                       //
//==================================================================//
void OnTick()
{
   RollDay();
   SyncBatchState();

   // Management runs every tick - break-even, trail and the time stop are
   // all time-critical and must not wait for a bar close.
   if(g_batchOpen)
      ManageBatch();

   // Entry logic only runs on a completed entry-TF bar. Evaluating mid-bar
   // means acting on a candle that can still change shape underneath you.
   datetime barTime = iTime(_Symbol, InpEntryTF, 0);
   if(barTime == g_lastBar)
      return;
   g_lastBar = barTime;

   EvaluateEntry();
}

//==================================================================//
//  ENTRY - THE GATE CHAIN                                          //
//==================================================================//
//  Each stage must pass. First failure stands the bar down. Ordered
//  cheapest-and-most-selective first so the common case exits early.
//------------------------------------------------------------------//
void EvaluateEntry()
{
   if(g_batchOpen)                       return;   // one batch at a time
   if(!TimeGateOK())                     return;
   if(!RiskGateOK())                     return;
   if(!SpreadOK())                       return;

   double atr = Ind(hAtrZone, 0, 1);
   if(atr <= 0.0) return;

   //--- Stage 1: is there enough movement to be worth trading? ------
   double baseline = AtrBaseline();
   if(baseline <= 0.0)
      { Reject("not enough history yet to build the ATR baseline"); return; }
   double volRatio = atr / baseline;
   if(volRatio < InpVolMin)
      { Reject(StringFormat("vol %.2f < min %.2f (too quiet)", volRatio, InpVolMin)); return; }
   if(volRatio > InpVolMax)
      { Reject(StringFormat("vol %.2f > max %.2f (news/panic)", volRatio, InpVolMax)); return; }

   //--- Stage 2: is the movement going anywhere? --------------------
   double er = EfficiencyRatio();
   int mode = MODE_NONE;
   if(er >= InpErTrend)      mode = MODE_TREND;
   else if(er <= InpErRange) mode = MODE_RANGE;
   else
      { Reject(StringFormat("ER %.3f is chop (%.2f-%.2f)", er, InpErRange, InpErTrend)); return; }

   //--- Stage 3: direction ------------------------------------------
   int dir = 0;
   double zoneNear = 0.0, zoneFar = 0.0;

   if(mode == MODE_TREND)
   {
      if(!TrendSetup(atr, dir, zoneNear, zoneFar)) return;
   }
   else
   {
      if(!RangeSetup(atr, dir, zoneNear, zoneFar)) return;
   }
   if(dir == 0) return;

   //--- Stage 4: over-extension + rejection -------------------------
   double rsi = Ind(hRsiEntry, 0, 1);
   if(dir > 0 && rsi > InpRsiLong)
      { Reject(StringFormat("RSI %.1f not stretched enough for a long", rsi)); return; }
   if(dir < 0 && rsi < InpRsiShort)
      { Reject(StringFormat("RSI %.1f not stretched enough for a short", rsi)); return; }

   if(InpNeedRejection && !RejectionBar(dir))
      { Reject("no rejection bar - pullback may still be falling"); return; }

   //--- Fire ---------------------------------------------------------
   PlaceBatch(dir, mode, atr, zoneNear, zoneFar, volRatio, er, rsi);
}

//------------------------------------------------------------------//
//  TREND MODE - the sandwich zone                                  |
//                                                                  |
//  LONG:  trendEMA < price < closeEMA   (trend EMA rising)         |
//  SHORT: closeEMA < price < trendEMA   (trend EMA falling)        |
//                                                                  |
//  Both halves are load-bearing. Being past the close EMA means we  |
//  are buying a pullback rather than chasing an extension, which is |
//  where the reward-to-risk comes from. Still being the right side  |
//  of the trend EMA bounds that pullback - "past the close EMA" on  |
//  its own is unbounded and catches falling knives.                 |
//                                                                  |
//  The zone width is the EMA separation, so it widens with trend    |
//  strength and pinches shut as the trend fades. The bot throttles  |
//  itself with no extra rule.                                       |
//------------------------------------------------------------------//
bool TrendSetup(double atr, int &dir, double &zoneNear, double &zoneFar)
{
   double trendNow  = Ind(hTrendEma, 0, 1);
   double trendPrev = Ind(hTrendEma, 0, 11);
   double closeEma  = Ind(hCloseEma, 0, 1);
   if(trendNow <= 0.0 || closeEma <= 0.0) return false;

   // Slope, not just side: price above a FLAT ema is a range, and ranges
   // are where this model gets chopped up. Normalised by ATR so the
   // threshold means the same thing on every symbol.
   double slope = (trendNow - trendPrev) / atr;
   if(MathAbs(slope) < InpTrendSlopeAtr)
      { Reject(StringFormat("trend EMA slope %.3f flat (need %.2f)", slope, InpTrendSlopeAtr)); return false; }

   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   int    d   = (slope > 0) ? 1 : -1;

   if(d > 0)
   {
      if(!(bid < closeEma && bid > trendNow))
         { Reject("long bias but price outside the sandwich zone"); return false; }
      zoneNear = closeEma;    // shallow edge
      zoneFar  = trendNow;    // deep edge
   }
   else
   {
      if(!(bid > closeEma && bid < trendNow))
         { Reject("short bias but price outside the sandwich zone"); return false; }
      zoneNear = closeEma;
      zoneFar  = trendNow;
   }

   // A zone thinner than the spread is not tradeable.
   if(MathAbs(zoneNear - zoneFar) < atr * 0.15)
      { Reject("sandwich zone too thin - trend fading"); return false; }

   dir = d;
   return true;
}

//------------------------------------------------------------------//
//  RANGE MODE - fade the band                                      |
//                                                                  |
//  With ER low the market is genuinely rotating, so the higher-     |
//  probability trade is the fade rather than the breakout. This is  |
//  what keeps the bot useful outside London/NY without forcing      |
//  trend logic onto a market that has no trend.                     |
//------------------------------------------------------------------//
bool RangeSetup(double atr, int &dir, double &zoneNear, double &zoneFar)
{
   double mid = Ind(hCloseEma, 0, 1);
   if(mid <= 0.0) return false;

   double upper = mid + InpKeltnerMult * atr;
   double lower = mid - InpKeltnerMult * atr;
   double bid   = SymbolInfoDouble(_Symbol, SYMBOL_BID);

   if(bid <= lower)
   {
      dir      = 1;
      zoneNear = lower;
      zoneFar  = lower - InpLadderDepthAtr * atr;
   }
   else if(bid >= upper)
   {
      dir      = -1;
      zoneNear = upper;
      zoneFar  = upper + InpLadderDepthAtr * atr;
   }
   else
   {
      Reject("range mode but price is mid-band - no edge here");
      return false;
   }
   return true;
}

//------------------------------------------------------------------//
//  Rejection confirmation                                          |
//                                                                  |
//  Price inside the zone is either a finishing pullback or the      |
//  start of a reversal, and at that moment the two look identical.  |
//  Waiting for the bar to reject costs a pip of entry and removes a |
//  large share of the losers.                                       |
//------------------------------------------------------------------//
bool RejectionBar(int dir)
{
   double o = iOpen (_Symbol, InpEntryTF, 1);
   double h = iHigh (_Symbol, InpEntryTF, 1);
   double l = iLow  (_Symbol, InpEntryTF, 1);
   double c = iClose(_Symbol, InpEntryTF, 1);
   double range = h - l;
   if(range <= 0.0) return false;

   if(dir > 0)
   {
      double lowerWick = MathMin(o, c) - l;
      return (c > o) && (lowerWick / range * 100.0 >= InpRejWickPct);
   }
   double upperWick = h - MathMax(o, c);
   return (c < o) && (upperWick / range * 100.0 >= InpRejWickPct);
}

//==================================================================//
//  ORDER PLACEMENT                                                 //
//==================================================================//
void PlaceBatch(int dir, int mode, double atr,
                double zoneNear, double zoneFar,
                double volRatio, double er, double rsi)
{
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ref = (dir > 0) ? ask : bid;

   double stopDist = InpStopAtr * atr;

   // The stop is structural, not arbitrary: in trend mode it sits beyond the
   // trend EMA, because if that breaks the reason for the trade is gone.
   double sl;
   if(mode == MODE_TREND)
      sl = (dir > 0) ? MathMin(zoneFar - 0.25 * atr, ref - stopDist)
                     : MathMax(zoneFar + 0.25 * atr, ref + stopDist);
   else
      sl = (dir > 0) ? ref - stopDist : ref + stopDist;

   stopDist = MathAbs(ref - sl);
   if(stopDist <= 0.0) return;

   // Respect the broker's minimum stop distance.
   double minDist = g_stopsLevel * _Point;
   if(stopDist < minDist)
      { Reject(StringFormat("stop %.1f pts inside broker stops level %d", stopDist/_Point, (int)g_stopsLevel)); return; }

   int legs = g_hedging ? MathMax(1, InpLadderLegs) : 1;

   double batchLots = CalcLots(stopDist);
   if(batchLots <= 0.0)
      { Reject("sized position rounds to zero - account too small for this stop"); return; }

   double legLots = NormalizeLots(batchLots / legs);
   if(legLots <= 0.0)
      { Reject("per-leg lot rounds to zero - reduce ladder legs or raise risk"); return; }

   PrintFormat("SIGNAL %s %s | vol %.2f ER %.3f RSI %.1f | ATR %.1f pips | stop %.1f pips | %d x %.2f lots",
               dir > 0 ? "LONG" : "SHORT",
               mode == MODE_TREND ? "TREND-PULLBACK" : "RANGE-FADE",
               volRatio, er, rsi, atr / g_pip, stopDist / g_pip, legs, legLots);

   if(InpDryRun)
   {
      Print("   [DRY RUN] no order sent");
      return;
   }

   // Ladder the legs across the zone. A shallow pullback fills leg 1 only;
   // a deep one fills all of them at a better average price. Adverse
   // movement improves the basis instead of being pure drawdown.
   double depth = InpLadderDepthAtr * atr;
   int    filled = 0;

   for(int i = 0; i < legs; i++)
   {
      double offset = (legs > 1) ? depth * ((double)i / (double)(legs - 1)) : 0.0;

      // Leg 0 goes at market so a runaway move is never missed entirely;
      // the deeper legs rest as limits waiting for a deeper pullback.
      // The early/late split IS the leg allocation: the first InpTp1Legs
      // legs bank at TP1 (the frequent small win), the rest run to TP2 and
      // pay for the losing batches.
      double tpDist = (i < InpTp1Legs) ? InpTp1Atr * atr : InpTp2Atr * atr;
      bool ok;

      if(i == 0)
      {
         double tp = (dir > 0) ? ref + tpDist : ref - tpDist;
         ok = (dir > 0) ? trade.Buy (legLots, _Symbol, 0.0, sl, tp, InpComment)
                        : trade.Sell(legLots, _Symbol, 0.0, sl, tp, InpComment);
      }
      else
      {
         double price = (dir > 0) ? ref - offset : ref + offset;
         price = NormalizeDouble(price, _Digits);
         double tp = (dir > 0) ? price + tpDist : price - tpDist;
         ok = (dir > 0) ? trade.BuyLimit (legLots, price, _Symbol, sl, tp, ORDER_TIME_GTC, 0, InpComment)
                        : trade.SellLimit(legLots, price, _Symbol, sl, tp, ORDER_TIME_GTC, 0, InpComment);
      }

      if(ok) filled++;
      else   PrintFormat("   leg %d rejected: %d %s", i, trade.ResultRetcode(), trade.ResultRetcodeDescription());
   }

   if(filled > 0)
   {
      g_batchOpen  = true;
      g_batchDir   = dir;
      g_batchEntry = ref;
      g_batchRisk  = stopDist;
      g_batchBE    = false;
      g_batchStartEq = AccountInfoDouble(ACCOUNT_EQUITY);
   }
}

//------------------------------------------------------------------//
//  Position sizing - fixed fractional off live equity.             |
//                                                                  |
//  This is what makes the lot size grow with the account: no ramp,  |
//  no streak counter, no state machine. Equity up 10% and the next  |
//  trade is 10% bigger, continuously. It also normalises across     |
//  setups - a tight-stop trade and a wide-stop trade risk the same  |
//  money, so stop distance never becomes an accidental position     |
//  sizer.                                                           |
//------------------------------------------------------------------//
double CalcLots(double stopDistPrice)
{
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double risk   = EffectiveRiskPercent();
   if(risk <= 0.0) return 0.0;

   double riskMoney = equity * risk / 100.0;
   double stopPips  = stopDistPrice / g_pip;
   if(stopPips <= 0.0) return 0.0;

   double lots = riskMoney / (stopPips * g_pipValue);
   return NormalizeLots(MathMin(lots, InpMaxLotCap));
}

//  Round DOWN to the lot step. Rounding up would silently over-risk,
//  which at small account sizes is exactly where it does most damage.
double NormalizeLots(double lots)
{
   double minLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double step    = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   if(step <= 0.0) step = 0.01;

   lots = MathFloor(lots / step) * step;
   lots = NormalizeDouble(lots, 2);

   if(lots < minLot) return 0.0;      // too small to express - skip, never round up
   if(lots > maxLot) lots = maxLot;
   return lots;
}

//  Risk is cut as drawdown from the high-water mark deepens. Sizing off raw
//  equity already shrinks positions in a drawdown, but drawdown is
//  asymmetric (down 50% needs +100% back), so the de-risking ladder buys
//  survival through the regime the filters failed to detect.
double EffectiveRiskPercent()
{
   if(!InpUseDerisk) return InpRiskPercent;

   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   if(g_highWater <= 0.0) return InpRiskPercent;

   double ddPct = (g_highWater - equity) / g_highWater * 100.0;
   if(ddPct >= InpDeriskStop) return 0.0;
   if(ddPct >= InpDeriskDD2)  return InpRiskPercent * 0.25;
   if(ddPct >= InpDeriskDD1)  return InpRiskPercent * 0.50;
   return InpRiskPercent;
}

//==================================================================//
//  POSITION MANAGEMENT                                             //
//==================================================================//
//  TP1 and TP2 are attached to the orders themselves, so the broker
//  honours them even if the terminal drops. What is left for the EA
//  is the state that cannot be pre-attached: break-even, the trail,
//  and the time stop.
//------------------------------------------------------------------//
void ManageBatch()
{
   double atr = Ind(hAtrZone, 0, 0);
   if(atr <= 0.0) return;

   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);

   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(!PositionSelectByTicket(ticket)) continue;
      if(PositionGetInteger(POSITION_MAGIC) != (long)InpMagic) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;

      long   type   = PositionGetInteger(POSITION_TYPE);
      int    dir    = (type == POSITION_TYPE_BUY) ? 1 : -1;
      double entry  = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl     = PositionGetDouble(POSITION_SL);
      double price  = (dir > 0) ? bid : ask;
      double moved  = (price - entry) * dir;
      double rMult  = (g_batchRisk > 0.0) ? moved / g_batchRisk : 0.0;

      //--- Time stop. A scalp that has not worked within the window is
      //--- capital and risk sitting idle for no expectancy. Closing it
      //--- also converts a slow bleed into a scratch, which is a large
      //--- part of how the loss distribution stays tight.
      if(InpTimeStopMin > 0)
      {
         datetime opened = (datetime)PositionGetInteger(POSITION_TIME);
         if(TimeCurrent() - opened >= InpTimeStopMin * 60 && rMult < InpTimeStopMinR)
         {
            PrintFormat("time stop: ticket %I64u flat at %.2fR after %d min", ticket, rMult, InpTimeStopMin);
            trade.PositionClose(ticket);
            continue;
         }
      }

      //--- Break-even once TP1 is banked. This is the single mechanism
      //--- doing most of the work on trade shape: it truncates the loss
      //--- side, turning would-be losers into scratches.
      if(InpUseBreakEven && !g_batchBE && rMult >= InpTp1Atr / InpStopAtr)
      {
         double be = entry + dir * InpBeBufferAtr * atr;
         if((dir > 0 && (sl < be)) || (dir < 0 && (sl > be || sl == 0.0)))
         {
            if(ModifyStop(ticket, be))
               PrintFormat("break-even: ticket %I64u stop -> %.5f", ticket, be);
         }
      }

      //--- Trail the runner behind price once it is past break-even.
      if(InpUseTrail && rMult > InpTp1Atr / InpStopAtr)
      {
         double trail = price - dir * InpTrailAtr * atr;
         if((dir > 0 && trail > sl) || (dir < 0 && (trail < sl || sl == 0.0)))
            ModifyStop(ticket, trail);
      }
   }

   if(InpUseBreakEven && !g_batchBE)
   {
      double moved = ((g_batchDir > 0 ? bid : ask) - g_batchEntry) * g_batchDir;
      if(g_batchRisk > 0.0 && moved / g_batchRisk >= InpTp1Atr / InpStopAtr)
         g_batchBE = true;
   }
}

bool ModifyStop(ulong ticket, double newSl)
{
   if(!PositionSelectByTicket(ticket)) return false;
   double tp = PositionGetDouble(POSITION_TP);
   newSl = NormalizeDouble(newSl, _Digits);

   // Never push a stop inside the broker's freeze distance - the request
   // would just be rejected and the loop would retry it every tick.
   double price = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY)
                  ? SymbolInfoDouble(_Symbol, SYMBOL_BID)
                  : SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   if(MathAbs(price - newSl) < g_stopsLevel * _Point) return false;

   return trade.PositionModify(ticket, newSl, tp);
}

//  Detect the batch closing out and score it. Consecutive losses feed the
//  pause; the high-water mark feeds the de-risking ladder.
void SyncBatchState()
{
   if(!g_batchOpen) return;

   int live = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(!PositionSelectByTicket(ticket)) continue;
      if(PositionGetInteger(POSITION_MAGIC) == (long)InpMagic &&
         PositionGetString(POSITION_SYMBOL) == _Symbol)
         live++;
   }
   // Resting ladder legs count as live too - otherwise a batch whose market
   // leg was rejected would look flat and cancel its own pending legs.
   for(int j = OrdersTotal() - 1; j >= 0; j--)
   {
      ulong t = OrderGetTicket(j);
      if(t == 0) continue;
      if(!OrderSelect(t)) continue;
      if(OrderGetInteger(ORDER_MAGIC) == (long)InpMagic &&
         OrderGetString(ORDER_SYMBOL) == _Symbol)
         live++;
   }
   if(live > 0) return;

   // Batch is flat. Cancel any ladder legs still resting unfilled.
   CancelPendings();

   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   bool   winner = (equity >= g_batchStartEq); // scored against this batch's own open

   if(equity > g_highWater) g_highWater = equity;

   if(winner) g_consecLoss = 0;
   else
   {
      g_consecLoss++;
      if(InpMaxConsecLoss > 0 && g_consecLoss >= InpMaxConsecLoss)
      {
         g_pauseUntil = TimeCurrent() + InpPauseMin * 60;
         PrintFormat("%d losing batches in a row - pausing until %s",
                     g_consecLoss, TimeToString(g_pauseUntil));
         g_consecLoss = 0;
      }
   }

   g_batchOpen = false;
   g_batchDir  = 0;
   g_batchBE   = false;
}

void CancelPendings()
{
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      ulong ticket = OrderGetTicket(i);
      if(ticket == 0) continue;
      if(!OrderSelect(ticket)) continue;
      if(OrderGetInteger(ORDER_MAGIC) != (long)InpMagic) continue;
      if(OrderGetString(ORDER_SYMBOL) != _Symbol) continue;
      trade.OrderDelete(ticket);
   }
}

//==================================================================//
//  GATES                                                           //
//==================================================================//
bool SpreadOK()
{
   double spread = SymbolInfoDouble(_Symbol, SYMBOL_ASK) - SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double atr    = Ind(hAtrZone, 0, 1);

   if(spread > InpMaxSpreadPips * g_pip)
      { Reject(StringFormat("spread %.1f pips over cap", spread / g_pip)); return false; }

   // The ATR-relative test is the one that matters: the cost of a trade has
   // to stay small against the move being targeted, whatever the regime.
   if(atr > 0.0 && spread > InpMaxSpreadAtr * atr)
      { Reject(StringFormat("spread %.1f pips is %.0f%% of ATR", spread / g_pip, spread / atr * 100.0)); return false; }

   return true;
}

bool TimeGateOK()
{
   MqlDateTime t;
   TimeToStruct(TimeCurrent(), t);

   // Rollover. Spreads routinely go 10-50 pips wide here and ATR looks
   // completely normal throughout, so the volatility gate cannot catch it.
   if(InpBlockRollover)
   {
      int nowMin  = t.hour * 60 + t.min;
      int rollMin = InpRolloverHour * 60;
      int diff    = MathAbs(nowMin - rollMin);
      diff = MathMin(diff, 1440 - diff);          // wrap around midnight
      if(diff <= InpRolloverPadMin)
         { Reject("rollover window"); return false; }
   }

   if(InpBlockWeekend)
   {
      if(t.day_of_week == 5 && t.hour >= InpFridayEndHour)
         { Reject("Friday close"); return false; }
      if(t.day_of_week == 0 && t.hour < InpSundayStartHr)
         { Reject("Sunday open"); return false; }
      if(t.day_of_week == 6)
         { Reject("Saturday"); return false; }
   }

   if(InpUseNewsFilter && IsNewsTime())
      { Reject("news blackout"); return false; }

   return true;
}

bool RiskGateOK()
{
   if(TimeCurrent() < g_pauseUntil)
      { Reject("paused after losing streak"); return false; }

   if(EffectiveRiskPercent() <= 0.0)
      { Reject("drawdown limit reached - trading halted"); return false; }

   if(InpDailyMaxLossPct > 0.0 && g_dayStartEq > 0.0)
   {
      double equity = AccountInfoDouble(ACCOUNT_EQUITY);
      double lossPct = (g_dayStartEq - equity) / g_dayStartEq * 100.0;
      if(lossPct >= InpDailyMaxLossPct)
         { Reject(StringFormat("daily loss %.2f%% hit", lossPct)); return false; }
   }
   return true;
}

//  MT5 economic calendar. Not populated inside the Strategy Tester, so this
//  gate is inert in backtests - expected, and worth remembering when live
//  results diverge from tested ones around data releases.
bool IsNewsTime()
{
   string base   = SymbolInfoString(_Symbol, SYMBOL_CURRENCY_BASE);
   string profit = SymbolInfoString(_Symbol, SYMBOL_CURRENCY_PROFIT);
   return NewsForCurrency(base) || NewsForCurrency(profit);
}

bool NewsForCurrency(string currency)
{
   if(currency == "") return false;

   datetime from = TimeCurrent() - InpNewsMinsAfter  * 60;
   datetime to   = TimeCurrent() + InpNewsMinsBefore * 60;

   MqlCalendarValue values[];
   int n = CalendarValueHistory(values, from, to, NULL, currency);
   for(int i = 0; i < n; i++)
   {
      MqlCalendarEvent evt;
      if(!CalendarEventById(values[i].event_id, evt)) continue;
      if(evt.importance == CALENDAR_IMPORTANCE_HIGH) return true;
   }
   return false;
}

//==================================================================//
//  INDICATORS & STATISTICS                                         //
//==================================================================//
double Ind(int handle, int buffer, int shift)
{
   double v[];
   ArraySetAsSeries(v, true);
   if(CopyBuffer(handle, buffer, shift, 1, v) < 1) return 0.0;
   return v[0];
}

//  Kaufman Efficiency Ratio: net distance travelled divided by the total
//  path length. ATR cannot separate directional expansion from violent
//  chop - both raise it - and this can. The chop band is where an entry
//  model like this takes its worst losses, so it is the highest-value
//  filter in the chain.
double EfficiencyRatio()
{
   int need = InpErPeriod + 1;
   double closes[];
   ArraySetAsSeries(closes, true);
   if(CopyClose(_Symbol, InpZoneTF, 1, need, closes) < need) return 0.0;

   double net  = MathAbs(closes[0] - closes[need - 1]);
   double path = 0.0;
   for(int i = 0; i < need - 1; i++)
      path += MathAbs(closes[i] - closes[i + 1]);

   return (path > 0.0) ? net / path : 0.0;
}

//  Median ATR across ALL hours over several days.
//
//  Taking the baseline from a short trailing window instead would make it
//  re-centre on whatever session it currently is, so dead Asian hours would
//  read as "volatile relative to Asia" and the gate would open on noise. An
//  all-hours multi-day median keeps the threshold anchored to what is
//  actually worth trading. Rebuilt hourly - it barely moves within an hour.
double AtrBaseline()
{
   if(g_atrBaseline > 0.0 && TimeCurrent() - g_baselineAt < 3600)
      return g_atrBaseline;

   int perDay = (int)(1440 / MathMax(1, PeriodSeconds(InpZoneTF) / 60));
   int count  = perDay * MathMax(1, InpBaselineDays);
   count = MathMin(count, 5000);

   double atrs[];
   ArraySetAsSeries(atrs, false);
   int got = CopyBuffer(hAtrZone, 0, 1, count, atrs);
   if(got < 50) return 0.0;

   ArraySort(atrs);
   g_atrBaseline = atrs[got / 2];
   g_baselineAt  = TimeCurrent();
   return g_atrBaseline;
}

//==================================================================//
//  HOUSEKEEPING                                                    //
//==================================================================//
datetime TodayStart()
{
   MqlDateTime t;
   TimeToStruct(TimeCurrent(), t);
   t.hour = 0; t.min = 0; t.sec = 0;
   return StructToTime(t);
}

void RollDay()
{
   datetime today = TodayStart();
   if(today == g_dayStart) return;
   g_dayStart   = today;
   g_dayStartEq = AccountInfoDouble(ACCOUNT_EQUITY);
   if(g_dayStartEq > g_highWater) g_highWater = g_dayStartEq;
}

void Reject(string reason)
{
   if(InpVerboseLog) Print("  skip: ", reason);
}
//+------------------------------------------------------------------+
