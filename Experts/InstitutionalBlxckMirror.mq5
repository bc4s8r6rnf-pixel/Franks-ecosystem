//+------------------------------------------------------------------+
//|                                  InstitutionalBlxckMirror.mq5     |
//|                Institutional Trend-Following / Liquidity EA       |
//|                                                                  |
//|  Concept:                                                        |
//|    HTF market structure + EMA order-flow give the daily bias.    |
//|    Price sweeps the PREVIOUS session's liquidity (retail stops), |
//|    then INVERTS the fair-value-gap created by the sweep candle   |
//|    and continues in the institutional trend toward the opposing  |
//|    liquidity pool. This is the "black mirror": retail reads a     |
//|    reversal, institutions read continuation.                     |
//|                                                                  |
//|  Entry  : close through an inversion FVG (IFVG) in bias direction |
//|  Stop   : beyond the liquidity-sweep extreme                      |
//|  Target : opposing liquidity pool                                 |
//|  Manage : TP1 -> take 70%, SL -> behind nearest M1 FVG to TP,     |
//|           trail the runner behind M1 FVGs.                        |
//|                                                                  |
//|  Suggested pair : EURUSD   Suggested TFs: D1/H4 bias, M15 setup,  |
//|                                            M1 refinement.         |
//+------------------------------------------------------------------+
#property copyright "Institutional Blxck Mirror"
#property link      ""
#property version   "1.00"
#property strict
#property description "Institutional trend-following EA: HTF bias + previous-session liquidity sweep + inversion FVG continuation."

#include <Trade/Trade.mqh>
#include <Trade/PositionInfo.mqh>
#include <Trade/SymbolInfo.mqh>

//==================================================================//
//  INPUTS                                                          //
//==================================================================//
input group "=== General ==="
input ulong    InpMagic              = 20260728;   // Magic number
input string   InpTradeComment       = "BlxckMirror";
input bool     InpOnePositionAtATime = true;       // Only one open position per symbol

input group "=== Timeframes ==="
input ENUM_TIMEFRAMES InpBiasTF   = PERIOD_H4;      // HTF bias / market-structure TF
input ENUM_TIMEFRAMES InpHTFTrend = PERIOD_D1;      // Higher trend confirmation TF
input ENUM_TIMEFRAMES InpSetupTF  = PERIOD_M15;     // Setup / sweep / IFVG TF
input ENUM_TIMEFRAMES InpMicroTF  = PERIOD_M1;      // Micro TF for trailing FVGs

input group "=== Bias engine ==="
input int      InpEmaFast          = 50;            // Fast EMA (order-flow) on bias TF
input int      InpEmaSlow          = 200;           // Slow EMA (order-flow) on bias TF
input int      InpStructLookback   = 60;            // Bars to scan for HTF market structure
input int      InpSwingStrength    = 2;             // Fractal strength (bars each side)
input bool     InpRequireEmaAndBOS = true;          // Require EMA + BOS to agree

input group "=== Sessions (broker/server time, 24h) ==="
input int      InpAsiaStart        = 0;             // Asia session start hour
input int      InpAsiaEnd          = 6;             // Asia session end hour
input int      InpLondonStart      = 7;             // London session start hour
input int      InpLondonEnd        = 12;            // London session end hour
input int      InpNYStart          = 13;            // New York session start hour
input int      InpNYEnd            = 20;            // New York session end hour
input bool     InpTradeLondon      = true;          // Allow entries in London killzone
input bool     InpTradeNewYork     = true;          // Allow entries in New York killzone

input group "=== Liquidity & setup ==="
input int      InpSetupLookback    = 120;           // Bars scanned on setup TF
input int      InpSweepMaxBars     = 8;             // Max bars between sweep and IFVG entry
input double   InpSweepMinPips     = 0.5;           // Min penetration beyond liquidity (pips)
input int      InpLiqSwingStrength = 2;             // Fractal strength for liquidity pools
input int      InpMaxLiqPools      = 12;            // Max liquidity pools to track/draw each side

input group "=== FVG / IFVG ==="
input double   InpMinFvgPips       = 0.5;           // Minimum FVG size (pips)
input int      InpMicroFvgScan     = 40;            // Bars scanned on micro TF for trailing FVGs

input group "=== Risk & management ==="
input double   InpRiskPercent      = 0.75;          // Risk per trade (% of balance)
input double   InpFixedLots        = 0.0;           // Fixed lots (0 = use risk %)
input double   InpSlBufferPips     = 1.5;           // Stop buffer beyond sweep (pips)
input double   InpMinRR            = 2.0;           // Minimum reward:risk to accept trade
input double   InpPartialPercent   = 70.0;          // % of position closed at TP1
input bool     InpMoveSlBehindFvg  = true;          // After TP1, SL -> behind nearest M1 FVG to TP
input bool     InpTrailMicroFvg    = true;          // Trail runner behind M1 FVGs
input int      InpMaxSpreadPips    = 3;             // Skip entries if spread wider than this
input int      InpMaxTradesPerDay  = 3;             // Cap trades per day

input group "=== Visuals ==="
input bool     InpShowHeatmap      = true;          // Draw liquidity heatmap
input bool     InpShowDashboard    = true;          // Draw info dashboard
input bool     InpShowFvg          = true;          // Draw FVG / IFVG boxes
input color    InpBuySideColor     = clrTomato;     // Buy-side liquidity (above highs)
input color    InpSellSideColor    = clrDodgerBlue; // Sell-side liquidity (below lows)
input color    InpFvgBullColor     = clrSeaGreen;   // Bullish FVG box
input color    InpFvgBearColor     = clrIndianRed;  // Bearish FVG box

//==================================================================//
//  GLOBALS                                                         //
//==================================================================//
CTrade         trade;
CPositionInfo  posinfo;
CSymbolInfo    syminfo;

int      hEmaFast = INVALID_HANDLE;
int      hEmaSlow = INVALID_HANDLE;

double   g_point;
double   g_pip;          // 1 pip in price terms
int      g_digits;
string   g_obj_prefix = "IBM_";

datetime g_lastSetupBarTime = 0;
datetime g_lastDay          = 0;
int      g_tradesToday      = 0;

// Trade lifecycle state (for the single managed position)
bool     g_tp1Done          = false;
double   g_plannedTP        = 0.0;
double   g_plannedSL        = 0.0;
int      g_posDir           = 0;   // +1 long, -1 short, 0 flat

//------------------------------------------------------------------//
enum BIAS { BIAS_NONE = 0, BIAS_BULL = 1, BIAS_BEAR = -1 };

struct FVG
{
   bool     valid;
   int      dir;        // +1 bullish gap, -1 bearish gap
   double   top;
   double   bottom;
   datetime time;       // time of the middle candle
   bool     inverted;   // has price closed through it (IFVG)?
};

struct LiqPool
{
   bool     valid;
   double   price;
   datetime time;
   int      side;       // +1 buy-side (above high), -1 sell-side (below low)
   int      touches;    // equal-highs/lows weight for heatmap
};

LiqPool  g_buySide[];
LiqPool  g_sellSide[];

//==================================================================//
//  INIT / DEINIT                                                   //
//==================================================================//
int OnInit()
{
   if(!syminfo.Name(_Symbol))
      return(INIT_FAILED);

   g_digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   g_point  = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   // pip = 10 points on 5/3-digit brokers, else 1 point
   g_pip = ((g_digits == 5 || g_digits == 3) ? 10.0 * g_point : g_point);

   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(20);
   trade.SetTypeFillingBySymbol(_Symbol);

   hEmaFast = iMA(_Symbol, InpBiasTF, InpEmaFast, 0, MODE_EMA, PRICE_CLOSE);
   hEmaSlow = iMA(_Symbol, InpBiasTF, InpEmaSlow, 0, MODE_EMA, PRICE_CLOSE);
   if(hEmaFast == INVALID_HANDLE || hEmaSlow == INVALID_HANDLE)
   {
      Print("Failed to create EMA handles");
      return(INIT_FAILED);
   }

   ArrayResize(g_buySide, 0);
   ArrayResize(g_sellSide, 0);

   Print("Institutional Blxck Mirror initialised on ", _Symbol,
         "  pip=", DoubleToString(g_pip, g_digits));
   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason)
{
   if(hEmaFast != INVALID_HANDLE) IndicatorRelease(hEmaFast);
   if(hEmaSlow != INVALID_HANDLE) IndicatorRelease(hEmaSlow);
   ObjectsDeleteAll(0, g_obj_prefix);
   Comment("");
}

//==================================================================//
//  MAIN TICK                                                       //
//==================================================================//
void OnTick()
{
   // Manage any open position on every tick
   ManageOpenPosition();

   // Reset daily trade counter
   datetime today = TodayStart();
   if(today != g_lastDay)
   {
      g_lastDay       = today;
      g_tradesToday   = 0;
   }

   // Only evaluate new setups once per completed setup-TF bar
   datetime curBar = iTime(_Symbol, InpSetupTF, 0);
   if(curBar == g_lastSetupBarTime)
      return;
   g_lastSetupBarTime = curBar;

   // Refresh structural view
   BuildLiquidityPools();
   if(InpShowHeatmap)   DrawHeatmap();
   if(InpShowDashboard) DrawDashboard();

   // Look for a fresh entry
   EvaluateSetup();
}

//==================================================================//
//  BIAS ENGINE                                                     //
//==================================================================//
// EMA order-flow read on the bias TF
int EmaBias()
{
   double fast[2], slow[2];
   if(CopyBuffer(hEmaFast, 0, 0, 2, fast) < 2) return 0;
   if(CopyBuffer(hEmaSlow, 0, 0, 2, slow) < 2) return 0;
   double price = iClose(_Symbol, InpBiasTF, 1);
   if(fast[0] > slow[0] && price > slow[0]) return BIAS_BULL;
   if(fast[0] < slow[0] && price < slow[0]) return BIAS_BEAR;
   return BIAS_NONE;
}

// Market-structure read via last Break of Structure on a TF
int StructureBias(ENUM_TIMEFRAMES tf)
{
   int n = InpStructLookback + InpSwingStrength * 2 + 2;
   MqlRates r[];
   ArraySetAsSeries(r, true);
   if(CopyRates(_Symbol, tf, 0, n, r) < n) return 0;

   // Find the most recent confirmed swing high and swing low
   double lastSwingHigh = 0, lastSwingLow = 0;
   int    idxHigh = -1, idxLow = -1;
   for(int i = InpSwingStrength; i < n - InpSwingStrength; i++)
   {
      if(IsSwingHigh(r, i, InpSwingStrength) && idxHigh < 0)
      { lastSwingHigh = r[i].high; idxHigh = i; }
      if(IsSwingLow(r, i, InpSwingStrength) && idxLow < 0)
      { lastSwingLow = r[i].low; idxLow = i; }
      if(idxHigh >= 0 && idxLow >= 0) break;
   }
   if(idxHigh < 0 || idxLow < 0) return 0;

   double close1 = r[1].close;
   // Bullish BOS: close above last swing high (and that high is the more recent structure point)
   if(close1 > lastSwingHigh) return BIAS_BULL;
   if(close1 < lastSwingLow)  return BIAS_BEAR;
   return BIAS_NONE;
}

// Combined institutional bias
int InstitutionalBias()
{
   int ema  = EmaBias();
   int bos  = StructureBias(InpBiasTF);
   int htf  = StructureBias(InpHTFTrend);

   if(InpRequireEmaAndBOS)
   {
      // EMA and BOS on bias TF must agree; HTF must not oppose
      if(ema == BIAS_BULL && bos == BIAS_BULL && htf != BIAS_BEAR) return BIAS_BULL;
      if(ema == BIAS_BEAR && bos == BIAS_BEAR && htf != BIAS_BULL) return BIAS_BEAR;
      return BIAS_NONE;
   }
   // Softer: majority vote
   int score = ema + bos + htf;
   if(score >= 2)  return BIAS_BULL;
   if(score <= -2) return BIAS_BEAR;
   return BIAS_NONE;
}

//==================================================================//
//  SWING / FRACTAL HELPERS                                         //
//==================================================================//
bool IsSwingHigh(const MqlRates &r[], int i, int strength)
{
   for(int k = 1; k <= strength; k++)
   {
      if(i - k < 0 || i + k >= ArraySize(r)) return false;
      if(r[i].high <= r[i - k].high) return false;
      if(r[i].high <= r[i + k].high) return false;
   }
   return true;
}

bool IsSwingLow(const MqlRates &r[], int i, int strength)
{
   for(int k = 1; k <= strength; k++)
   {
      if(i - k < 0 || i + k >= ArraySize(r)) return false;
      if(r[i].low >= r[i - k].low) return false;
      if(r[i].low >= r[i + k].low) return false;
   }
   return true;
}

//==================================================================//
//  LIQUIDITY POOLS + HEATMAP                                       //
//==================================================================//
void BuildLiquidityPools()
{
   ArrayResize(g_buySide, 0);
   ArrayResize(g_sellSide, 0);

   int n = InpSetupLookback + InpLiqSwingStrength * 2 + 2;
   MqlRates r[];
   ArraySetAsSeries(r, true);
   if(CopyRates(_Symbol, InpSetupTF, 0, n, r) < n) return;

   double tol = g_pip * 1.0; // equal highs/lows tolerance for heatmap weighting

   for(int i = InpLiqSwingStrength; i < n - InpLiqSwingStrength; i++)
   {
      if(IsSwingHigh(r, i, InpLiqSwingStrength))
         AddOrWeightPool(g_buySide, r[i].high, r[i].time, +1, tol);
      if(IsSwingLow(r, i, InpLiqSwingStrength))
         AddOrWeightPool(g_sellSide, r[i].low, r[i].time, -1, tol);
   }

   // Add previous session highs/lows as high-value pools
   double pAsiaH, pAsiaL, pLonH, pLonL;
   if(PreviousSessionRange(InpAsiaStart, InpAsiaEnd, pAsiaH, pAsiaL))
   {
      AddOrWeightPool(g_buySide,  pAsiaH, iTime(_Symbol, InpSetupTF, 1), +1, tol);
      AddOrWeightPool(g_sellSide, pAsiaL, iTime(_Symbol, InpSetupTF, 1), -1, tol);
   }
   if(PreviousSessionRange(InpLondonStart, InpLondonEnd, pLonH, pLonL))
   {
      AddOrWeightPool(g_buySide,  pLonH, iTime(_Symbol, InpSetupTF, 1), +1, tol);
      AddOrWeightPool(g_sellSide, pLonL, iTime(_Symbol, InpSetupTF, 1), -1, tol);
   }

   TrimPools(g_buySide,  InpMaxLiqPools, true);   // keep the highest buy-side
   TrimPools(g_sellSide, InpMaxLiqPools, false);  // keep the lowest sell-side
}

void AddOrWeightPool(LiqPool &arr[], double price, datetime t, int side, double tol)
{
   for(int i = 0; i < ArraySize(arr); i++)
   {
      if(arr[i].valid && MathAbs(arr[i].price - price) <= tol)
      {
         arr[i].touches++;                       // equal highs/lows => heavier liquidity
         if(t > arr[i].time) arr[i].time = t;
         return;
      }
   }
   int sz = ArraySize(arr);
   ArrayResize(arr, sz + 1);
   arr[sz].valid   = true;
   arr[sz].price   = price;
   arr[sz].time    = t;
   arr[sz].side    = side;
   arr[sz].touches = 1;
}

// Keep the N most extreme pools (highest highs / lowest lows are the juiciest)
void TrimPools(LiqPool &arr[], int keep, bool keepHighest)
{
   int sz = ArraySize(arr);
   if(sz <= keep) return;
   // simple selection sort by price
   for(int a = 0; a < sz - 1; a++)
      for(int b = a + 1; b < sz; b++)
      {
         bool swap = keepHighest ? (arr[b].price > arr[a].price)
                                 : (arr[b].price < arr[a].price);
         if(swap)
         {
            LiqPool tmp = arr[a]; arr[a] = arr[b]; arr[b] = tmp;
         }
      }
   ArrayResize(arr, keep);
}

void DrawHeatmap()
{
   // remove previous heatmap objects
   ObjectsDeleteAll(0, g_obj_prefix + "LQ_");

   datetime tEnd   = iTime(_Symbol, InpSetupTF, 0) + PeriodSeconds(InpSetupTF) * 6;
   int maxTouch = 1;
   for(int i = 0; i < ArraySize(g_buySide); i++)  maxTouch = MathMax(maxTouch, g_buySide[i].touches);
   for(int i = 0; i < ArraySize(g_sellSide); i++) maxTouch = MathMax(maxTouch, g_sellSide[i].touches);

   for(int i = 0; i < ArraySize(g_buySide); i++)
      DrawLiqLine(g_buySide[i], tEnd, maxTouch, InpBuySideColor, "BUY");
   for(int i = 0; i < ArraySize(g_sellSide); i++)
      DrawLiqLine(g_sellSide[i], tEnd, maxTouch, InpSellSideColor, "SELL");
}

void DrawLiqLine(const LiqPool &p, datetime tEnd, int maxTouch, color c, string tag)
{
   if(!p.valid) return;
   string name = g_obj_prefix + "LQ_" + tag + "_" + DoubleToString(p.price, g_digits);
   if(ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_TREND, 0, p.time, p.price, tEnd, p.price);
   ObjectSetInteger(0, name, OBJPROP_COLOR, c);
   int width = 1 + (int)MathRound(3.0 * p.touches / MathMax(1, maxTouch)); // heavier = thicker
   ObjectSetInteger(0, name, OBJPROP_WIDTH, width);
   ObjectSetInteger(0, name, OBJPROP_RAY_RIGHT, false);
   ObjectSetInteger(0, name, OBJPROP_BACK, true);
   ObjectSetInteger(0, name, OBJPROP_STYLE, STYLE_SOLID);
   ObjectSetString(0, name, OBJPROP_TOOLTIP,
                   tag + " liquidity  weight=" + IntegerToString(p.touches));
}

//==================================================================//
//  SESSIONS                                                        //
//==================================================================//
datetime TodayStart()
{
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   dt.hour = 0; dt.min = 0; dt.sec = 0;
   return StructToTime(dt);
}

int CurrentHour()
{
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   return dt.hour;
}

bool InKillzone()
{
   int h = CurrentHour();
   if(InpTradeLondon  && h >= InpLondonStart && h < InpLondonEnd) return true;
   if(InpTradeNewYork && h >= InpNYStart     && h < InpNYEnd)     return true;
   return false;
}

// Range of the most recent COMPLETED occurrence of a session (previous session)
bool PreviousSessionRange(int startH, int endH, double &hi, double &lo)
{
   hi = -DBL_MAX; lo = DBL_MAX;
   int scan = 1440 / PeriodMinutesSafe(InpSetupTF) + 5; // ~ one day of setup-TF bars
   scan = MathMax(scan, 30);
   bool found = false;

   // Walk back to the previous fully-formed session block
   int hoursSeen = 0;
   for(int i = 1; i < scan * 2; i++)
   {
      datetime t = iTime(_Symbol, InpSetupTF, i);
      if(t == 0) break;
      MqlDateTime dt; TimeToStruct(t, dt);
      bool inSess = (dt.hour >= startH && dt.hour < endH);
      if(inSess)
      {
         // Only capture the FIRST (most recent) completed session block we encounter
         hi = MathMax(hi, iHigh(_Symbol, InpSetupTF, i));
         lo = MathMin(lo, iLow(_Symbol, InpSetupTF, i));
         found = true;
      }
      else if(found)
      {
         break; // we've stepped out of the most recent session block -> done
      }
   }
   return (found && hi > -DBL_MAX && lo < DBL_MAX);
}

int PeriodMinutesSafe(ENUM_TIMEFRAMES tf)
{
   int s = PeriodSeconds(tf);
   return (s > 0 ? s / 60 : 15);
}

//==================================================================//
//  FVG / IFVG DETECTION                                            //
//==================================================================//
// Scan setup-TF for an FVG on a 3-candle window ending at index i (series).
// Returns bullish FVG if r[i].low > r[i+2].high, bearish if r[i].high < r[i+2].low.
bool FvgAt(const MqlRates &r[], int i, FVG &out)
{
   out.valid = false;
   if(i + 2 >= ArraySize(r)) return false;
   double minSize = g_pip * InpMinFvgPips;

   // bullish gap (space between candle i-2 high and candle i low)
   if(r[i].low - r[i + 2].high >= minSize)
   {
      out.valid   = true;
      out.dir     = +1;
      out.bottom  = r[i + 2].high;
      out.top     = r[i].low;
      out.time    = r[i + 1].time;
      out.inverted = false;
      return true;
   }
   // bearish gap
   if(r[i + 2].low - r[i].high >= minSize)
   {
      out.valid   = true;
      out.dir     = -1;
      out.top     = r[i + 2].low;
      out.bottom  = r[i].high;
      out.time    = r[i + 1].time;
      out.inverted = false;
      return true;
   }
   return false;
}

// Find the IFVG relevant to the trade.
// For a BULLISH bias we want a bearish FVG (created around the down-sweep) that
// price then CLOSES ABOVE -> it inverts to bullish support (IFVG). Vice-versa short.
// sweepIdx = series index of the sweep candle. Search a small window around it.
bool FindInversionFVG(const MqlRates &r[], int bias, int sweepIdx, FVG &ifvg)
{
   int lo = MathMax(0, sweepIdx - InpSweepMaxBars);
   int hi = MathMin(ArraySize(r) - 3, sweepIdx + 2);

   for(int i = hi; i >= lo; i--)
   {
      FVG f;
      if(!FvgAt(r, i, f)) continue;

      if(bias == BIAS_BULL && f.dir == -1)
      {
         // has a later candle (index < i) closed above the bearish gap top?
         for(int j = i - 1; j >= 0; j--)
         {
            if(r[j].close > f.top)
            {
               f.inverted = true;
               ifvg = f;
               return true;
            }
         }
      }
      else if(bias == BIAS_BEAR && f.dir == +1)
      {
         for(int j = i - 1; j >= 0; j--)
         {
            if(r[j].close < f.bottom)
            {
               f.inverted = true;
               ifvg = f;
               return true;
            }
         }
      }
   }
   return false;
}

// Nearest micro-TF (M1) FVG to a given price, on the trade side.
// For a long: nearest bullish FVG below TP. For a short: nearest bearish FVG above TP.
bool NearestMicroFvg(int dir, double refPrice, FVG &out)
{
   MqlRates r[];
   ArraySetAsSeries(r, true);
   int n = InpMicroFvgScan + 3;
   if(CopyRates(_Symbol, InpMicroTF, 0, n, r) < n) return false;

   double best = DBL_MAX;
   bool   got  = false;
   for(int i = 0; i < n - 2; i++)
   {
      FVG f;
      if(!FvgAt(r, i, f)) continue;
      double lvl = (dir > 0 ? f.top : f.bottom);
      double d   = MathAbs(refPrice - lvl);
      if(d < best)
      {
         best = d; out = f; got = true;
      }
   }
   return got;
}

//==================================================================//
//  SWEEP DETECTION                                                 //
//==================================================================//
// A sweep = a recent candle wicks beyond previous-session liquidity against
// the trend, then closes back inside. Returns the sweep candle series index.
//   Bullish bias -> sweep of SELL-side (previous session low) then close back up.
//   Bearish bias -> sweep of BUY-side (previous session high) then close back down.
bool DetectLiquiditySweep(const MqlRates &r[], int bias, double &liqLevel, int &sweepIdx)
{
   sweepIdx = -1;
   double minPen = g_pip * InpSweepMinPips;

   double sessH, sessL;
   // Use the most relevant previous session (Asia for London killzone; London for NY)
   bool haveAsia   = PreviousSessionRange(InpAsiaStart,   InpAsiaEnd,   sessH, sessL);
   double lonH, lonL;
   bool haveLondon = PreviousSessionRange(InpLondonStart, InpLondonEnd, lonH, lonL);

   int h = CurrentHour();
   double targetHigh, targetLow;
   if(h >= InpNYStart && haveLondon) { targetHigh = lonH; targetLow = lonL; }
   else if(haveAsia)                 { targetHigh = sessH; targetLow = sessL; }
   else if(haveLondon)               { targetHigh = lonH; targetLow = lonL; }
   else return false;

   int scan = MathMin(InpSweepMaxBars + 3, ArraySize(r) - 1);

   for(int i = 1; i <= scan; i++)
   {
      if(bias == BIAS_BULL)
      {
         // wick below prev-session low, close back above it
         if(r[i].low < targetLow - minPen && r[i].close > targetLow)
         {
            liqLevel = targetLow;
            sweepIdx = i;
            return true;
         }
      }
      else if(bias == BIAS_BEAR)
      {
         if(r[i].high > targetHigh + minPen && r[i].close < targetHigh)
         {
            liqLevel = targetHigh;
            sweepIdx = i;
            return true;
         }
      }
   }
   return false;
}

//==================================================================//
//  SETUP EVALUATION + ENTRY                                        //
//==================================================================//
void EvaluateSetup()
{
   if(HasOpenPosition()) return;
   if(InpOnePositionAtATime && HasOpenPosition()) return;
   if(!InKillzone()) return;
   if(g_tradesToday >= InpMaxTradesPerDay) return;
   if(SpreadPips() > InpMaxSpreadPips) return;

   int bias = InstitutionalBias();
   if(bias == BIAS_NONE) return;

   int n = InpSetupLookback + 5;
   MqlRates r[];
   ArraySetAsSeries(r, true);
   if(CopyRates(_Symbol, InpSetupTF, 0, n, r) < n) return;

   // 1) previous-session liquidity sweep against the trend
   double liqLevel; int sweepIdx;
   if(!DetectLiquiditySweep(r, bias, liqLevel, sweepIdx)) return;

   // 2) inversion FVG from around the sweep candle, in trend direction
   FVG ifvg;
   if(!FindInversionFVG(r, bias, sweepIdx, ifvg)) return;

   // 3) confirmation: last closed candle must sit on the trend side of the IFVG
   double lastClose = r[1].close;
   if(bias == BIAS_BULL && lastClose <= ifvg.top)    return;
   if(bias == BIAS_BEAR && lastClose >= ifvg.bottom) return;

   // 4) build the trade
   double entry = SymbolInfoDouble(_Symbol, (bias == BIAS_BULL) ? SYMBOL_ASK : SYMBOL_BID);
   double sl, tp;

   double sweepExtreme = (bias == BIAS_BULL) ? r[sweepIdx].low : r[sweepIdx].high;
   double slBuf = g_pip * InpSlBufferPips;

   if(bias == BIAS_BULL)
   {
      sl = sweepExtreme - slBuf;
      tp = OpposingLiquidity(+1, entry);       // nearest buy-side pool above
   }
   else
   {
      sl = sweepExtreme + slBuf;
      tp = OpposingLiquidity(-1, entry);       // nearest sell-side pool below
   }
   if(tp <= 0.0) return;

   double risk   = MathAbs(entry - sl);
   double reward = MathAbs(tp - entry);
   if(risk <= 0.0) return;
   if(reward / risk < InpMinRR) return;

   double lots = CalcLots(risk);
   if(lots <= 0.0) return;

   if(InpShowFvg) DrawFvgBox(ifvg, bias == BIAS_BULL ? InpFvgBullColor : InpFvgBearColor, true);

   bool ok = false;
   if(bias == BIAS_BULL)
      ok = trade.Buy(lots, _Symbol, 0.0, sl, tp, InpTradeComment);   // 0.0 => current Ask
   else
      ok = trade.Sell(lots, _Symbol, 0.0, sl, tp, InpTradeComment);  // 0.0 => current Bid

   if(ok)
   {
      g_tradesToday++;
      g_tp1Done   = false;
      g_plannedTP = tp;
      g_plannedSL = sl;
      g_posDir    = bias;
      PrintFormat("ENTRY %s lots=%.2f entry=%.5f sl=%.5f tp=%.5f RR=%.2f",
                  (bias == BIAS_BULL ? "BUY" : "SELL"), lots, entry, sl, tp, reward / risk);
   }
   else
      PrintFormat("Order failed: %d %s", trade.ResultRetcode(), trade.ResultRetcodeDescription());
}

// Opposing liquidity pool for TP: for a long, nearest buy-side pool above entry.
double OpposingLiquidity(int dir, double entry)
{
   double best = 0.0;
   if(dir > 0)
   {
      double dmin = DBL_MAX;
      for(int i = 0; i < ArraySize(g_buySide); i++)
      {
         if(!g_buySide[i].valid) continue;
         double p = g_buySide[i].price;
         if(p > entry + g_pip && (p - entry) < dmin) { dmin = p - entry; best = p; }
      }
   }
   else
   {
      double dmin = DBL_MAX;
      for(int i = 0; i < ArraySize(g_sellSide); i++)
      {
         if(!g_sellSide[i].valid) continue;
         double p = g_sellSide[i].price;
         if(p < entry - g_pip && (entry - p) < dmin) { dmin = entry - p; best = p; }
      }
   }
   return best;
}

//==================================================================//
//  TRADE MANAGEMENT                                                //
//==================================================================//
void ManageOpenPosition()
{
   if(!HasOpenPosition()) { g_posDir = 0; return; }
   if(!posinfo.SelectByMagic(_Symbol, InpMagic)) return;

   long   type    = posinfo.PositionType();
   double volume  = posinfo.Volume();
   double openp   = posinfo.PriceOpen();
   double curSL   = posinfo.StopLoss();
   double curTP   = posinfo.TakeProfit();
   int    dir     = (type == POSITION_TYPE_BUY) ? +1 : -1;
   g_posDir       = dir;

   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double px  = (dir > 0) ? bid : ask;

   double tpLevel = (g_plannedTP > 0 ? g_plannedTP : curTP);

   // --- TP1: take partial, move stop behind nearest M1 FVG to TP ---
   if(!g_tp1Done && tpLevel > 0.0)
   {
      bool hitTP1 = (dir > 0) ? (px >= tpLevel) : (px <= tpLevel);
      if(hitTP1)
      {
         double closeVol = NormalizeVolume(volume * InpPartialPercent / 100.0);
         if(closeVol > 0.0 && closeVol < volume)
         {
            if(trade.PositionClosePartial(_Symbol, closeVol))
               PrintFormat("TP1 hit: closed %.2f lots (%.0f%%)", closeVol, InpPartialPercent);
         }
         g_tp1Done = true;

         // move SL behind nearest M1 FVG to TP, giving the runner room
         if(InpMoveSlBehindFvg)
         {
            FVG mf;
            double newSL;
            if(NearestMicroFvg(dir, tpLevel, mf))
               newSL = (dir > 0) ? (mf.bottom - g_pip * InpSlBufferPips)
                                 : (mf.top    + g_pip * InpSlBufferPips);
            else
               newSL = openp; // fallback: break-even
            // only tighten in our favour
            if((dir > 0 && newSL > curSL) || (dir < 0 && (curSL == 0 || newSL < curSL)))
               ModifySL(newSL);

            // let the runner target the next pool beyond current TP
            double extTP = OpposingLiquidity(dir, tpLevel);
            if(extTP > 0.0 && ((dir > 0 && extTP > tpLevel) || (dir < 0 && extTP < tpLevel)))
            {
               g_plannedTP = extTP;
               ModifyTP(extTP);
            }
         }
      }
   }

   // --- Trail the runner behind M1 FVGs after TP1 ---
   if(g_tp1Done && InpTrailMicroFvg)
   {
      FVG mf;
      if(NearestMicroFvg(dir, px, mf))
      {
         double trail = (dir > 0) ? (mf.bottom - g_pip * InpSlBufferPips)
                                  : (mf.top    + g_pip * InpSlBufferPips);
         // never trail past current price; only move in profit direction
         if(dir > 0 && trail > curSL && trail < px) ModifySL(trail);
         if(dir < 0 && (curSL == 0 || trail < curSL) && trail > px) ModifySL(trail);
      }
   }
}

void ModifySL(double newSL)
{
   double tp = posinfo.TakeProfit();
   newSL = NormalizeDouble(newSL, g_digits);
   if(!trade.PositionModify(_Symbol, newSL, tp))
      PrintFormat("ModifySL failed: %d", trade.ResultRetcode());
   else
      g_plannedSL = newSL;
}

void ModifyTP(double newTP)
{
   double sl = posinfo.StopLoss();
   newTP = NormalizeDouble(newTP, g_digits);
   if(!trade.PositionModify(_Symbol, sl, newTP))
      PrintFormat("ModifyTP failed: %d", trade.ResultRetcode());
}

//==================================================================//
//  RISK / SIZING HELPERS                                           //
//==================================================================//
double CalcLots(double riskPriceDistance)
{
   if(InpFixedLots > 0.0) return NormalizeVolume(InpFixedLots);

   double balance   = AccountInfoDouble(ACCOUNT_BALANCE);
   double riskMoney = balance * InpRiskPercent / 100.0;

   double tickValue = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tickSize  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tickSize <= 0.0 || tickValue <= 0.0) return 0.0;

   double ticks       = riskPriceDistance / tickSize;
   double moneyPerLot = ticks * tickValue;
   if(moneyPerLot <= 0.0) return 0.0;

   double lots = riskMoney / moneyPerLot;
   return NormalizeVolume(lots);
}

double NormalizeVolume(double lots)
{
   double minLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double stepLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   if(stepLot <= 0.0) stepLot = 0.01;
   lots = MathFloor(lots / stepLot) * stepLot;
   lots = MathMax(minLot, MathMin(maxLot, lots));
   return NormalizeDouble(lots, 2);
}

double SpreadPips()
{
   double spread = (SymbolInfoDouble(_Symbol, SYMBOL_ASK) - SymbolInfoDouble(_Symbol, SYMBOL_BID));
   return spread / g_pip;
}

bool HasOpenPosition()
{
   return posinfo.SelectByMagic(_Symbol, InpMagic);
}

//==================================================================//
//  VISUALS                                                         //
//==================================================================//
void DrawFvgBox(const FVG &f, color c, bool ifvg)
{
   if(!f.valid) return;
   string name = g_obj_prefix + "FVG_" + IntegerToString((int)f.time);
   datetime t2 = f.time + PeriodSeconds(InpSetupTF) * 6;
   if(ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_RECTANGLE, 0, f.time, f.top, t2, f.bottom);
   ObjectSetInteger(0, name, OBJPROP_COLOR, c);
   ObjectSetInteger(0, name, OBJPROP_FILL, true);
   ObjectSetInteger(0, name, OBJPROP_BACK, true);
   ObjectSetString(0, name, OBJPROP_TOOLTIP, ifvg ? "Inversion FVG (entry)" : "FVG");
}

void DrawDashboard()
{
   int bias = InstitutionalBias();
   string sBias = (bias == BIAS_BULL) ? "BULLISH" : (bias == BIAS_BEAR ? "BEARISH" : "NONE");
   string txt =
      "INSTITUTIONAL BLXCK MIRROR\n" +
      "Symbol      : " + _Symbol + "\n" +
      "Bias (" + EnumToString(InpBiasTF) + "): " + sBias + "\n" +
      "EMA bias    : " + BiasStr(EmaBias()) + "\n" +
      "BOS " + EnumToString(InpBiasTF) + " : " + BiasStr(StructureBias(InpBiasTF)) + "\n" +
      "BOS " + EnumToString(InpHTFTrend) + " : " + BiasStr(StructureBias(InpHTFTrend)) + "\n" +
      "Killzone    : " + (InKillzone() ? "OPEN" : "closed") + "\n" +
      "Spread(pips): " + DoubleToString(SpreadPips(), 1) + "\n" +
      "Trades today: " + IntegerToString(g_tradesToday) + "/" + IntegerToString(InpMaxTradesPerDay) + "\n" +
      "Position    : " + (HasOpenPosition() ? (g_posDir > 0 ? "LONG" : "SHORT") : "flat") +
                         (g_tp1Done ? "  [runner]" : "");
   Comment(txt);
}

string BiasStr(int b)
{
   if(b == BIAS_BULL) return "bull";
   if(b == BIAS_BEAR) return "bear";
   return "-";
}
//+------------------------------------------------------------------+
