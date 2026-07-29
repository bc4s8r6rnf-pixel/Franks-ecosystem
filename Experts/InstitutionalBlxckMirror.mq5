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
//|  Default inputs below are PRE-OPTIMISED FOR GBPUSD M15 - attach   |
//|  and go with no .set file needed. Suggested TFs: D1/H4 bias,      |
//|  M15 setup, M1 refinement. (EURUSD users: load presets/EURUSD.set)|
//+------------------------------------------------------------------+
#property copyright "Institutional Blxck Mirror"
#property link      ""
#property version   "1.00"
#property strict
#property description "Institutional trend-following EA (defaults pre-tuned for GBPUSD M15): HTF bias + BOS/CHoC swing detection + dynamic OTE entry."

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
input ENUM_TIMEFRAMES InpSetupTF  = PERIOD_M30;     // Structure/swing TF, less noise = more significant swings (entry/tap still on InpMicroTF)
input ENUM_TIMEFRAMES InpMicroTF  = PERIOD_M1;      // Micro TF for trailing FVGs

input group "=== Bias engine ==="
input int      InpEmaFast          = 50;            // Fast EMA (order-flow) on bias TF
input int      InpEmaSlow          = 200;           // Slow EMA (order-flow) on bias TF
input int      InpStructLookback   = 60;            // Bars to scan for HTF market structure
input int      InpSwingStrength    = 2;             // Fractal strength (bars each side)
// Bias strictness: 0 = strict (EMA+BOS+D1 must all agree, fewest signals),
// 1 = majority (2 of 3 agree), 2 = lean (any net agreement - most signals)
input int      InpBiasMode          = 0;            // Bias mode (0 strict / 1 majority / 2 lean)

input group "=== Sessions (defined in NEW YORK time, 24h) ==="
// Session hours below are in NEW YORK time. The EA converts server->NY using
// the offset. Example: broker GMT+3, NY EDT = GMT-4  =>  NY = server - 7  =>  offset = -7.
input int      InpServerToNYOffset = -7;            // Hours to add to SERVER time to get NY time
input int      InpAsiaStart        = 19;            // Asia session start hour (NY)
input int      InpAsiaEnd          = 0;             // Asia session end hour (NY, 0 = midnight)
input int      InpLondonStart      = 1;             // London session start hour (NY)
input int      InpLondonEnd        = 5;             // London session end hour (NY)
input int      InpNYStart          = 7;             // New York session start hour (NY)
input int      InpNYEnd            = 11;            // New York session end hour (NY)
input bool     InpTradeLondon      = true;          // Allow entries in London killzone
input bool     InpTradeNewYork     = true;          // Allow entries in New York killzone
input bool     InpTradeAsia        = false;         // Allow entries in Asia killzone (sweeps prior NY session)

input group "=== High-probability entry windows (NY time, decimal hours) ==="
// The swing/OTE can arm and track any time within the broader killzone above -
// but the actual OTE tap that fires an entry statistically clusters in a much
// tighter window each session. This restricts ENTRY (not arming/tracking) to
// those windows so noise trades outside them are cut out. Asia has no defined
// prime window and is unrestricted whenever InpTradeAsia is on.
// Widened to the full London/NY killzone - now that a tap can only ever fire
// fresh and live (see the staleness fix in TryEnterArmed), there's no longer a
// reason to miss a genuine reaction just because it lands outside a narrow
// sub-window. Narrow this back down only if you want fewer, more selective fires.
input bool     InpUsePrimeWindow    = true;          // Only fire entries inside the prime sub-window
input double   InpLondonPrimeStart  = 1.0;           // London prime window start (NY hour, decimal)
input double   InpLondonPrimeEnd    = 5.0;           // London prime window end (NY hour, decimal)
input double   InpNYPrimeStart      = 7.0;           // New York prime window start (NY hour, decimal)
input double   InpNYPrimeEnd        = 11.0;          // New York prime window end (NY hour, decimal)

input group "=== Liquidity & setup ==="
input int      InpSetupLookback    = 120;           // Bars scanned on setup TF
input int      InpSweepMaxBars     = 8;             // Max bars between sweep and IFVG entry
input double   InpSweepMinPips     = 1.0;           // Min penetration beyond liquidity (pips)
input int      InpLiqSwingStrength = 2;             // Fractal strength for liquidity pools
input int      InpMaxLiqPools      = 16;            // Max liquidity pools to track/draw each side

input group "=== FVG / IFVG ==="
input double   InpMinFvgPips       = 1.0;           // Minimum FVG size (pips)
input int      InpMicroFvgScan     = 40;            // Bars scanned on micro TF for trailing FVGs

input group "=== Risk & management ==="
input double   InpRiskPercent      = 1.0;           // Risk per trade (% of balance) - CalcLots() sizes adaptively off current balance + stop distance every trade
input double   InpFixedLots        = 0.0;           // Fixed lots (0 = use risk %)
input double   InpSlBufferPips     = 2.5;           // Stop buffer beyond sweep (pips)
input double   InpMinRR            = 2.5;           // Minimum reward:risk to accept trade
input double   InpTP1_RR            = 2.0;          // First partial at this reward:risk (0 = off)
input double   InpFirstPartialPct   = 50.0;         // % of position closed at the 1:R first partial
input double   InpPartialPercent   = 70.0;          // % of REMAINING closed at the -2.0 SD target
input bool     InpMoveSlBehindFvg  = true;          // After TP1, SL -> behind nearest M1 FVG to TP
input bool     InpTrailMicroFvg    = false;         // Trail runner behind M1 FVGs (off by default - M1 FVGs form on normal noise and were stopping runners out before the real target; a straight win/break-even beats a small win)
input int      InpMaxSpreadPips    = 4;             // Skip entries if spread wider than this
input int      InpMaxTradesPerDay  = 3;             // Cap trades per day (room for one London + one NY + a retry)
input double   InpMaxStopPips       = 0.0;          // Reject if stop distance > this (0 = off)

input group "=== ATR stop fallback ==="
input bool     InpUseAtrStop       = true;          // Enforce a minimum ATR-based stop distance
input int      InpAtrPeriod        = 14;            // ATR period (setup TF)
input double   InpAtrMultSL        = 1.3;           // ATR multiple for the fallback stop

input group "=== News filter (MT5 economic calendar) ==="
input bool     InpUseNewsFilter    = true;          // Block entries around high-impact news
input int      InpNewsImportance   = 2;             // 1 = moderate+, 2 = high only
input int      InpNewsMinsBefore    = 15;           // Block this many minutes BEFORE an event
input int      InpNewsMinsAfter     = 15;           // Block this many minutes AFTER an event

input group "=== Win-rate boosters ==="
input bool     InpUseDisplacement  = true;          // Require a strong displacement entry candle
input double   InpMinBodyPct        = 55.0;         // Min body/range % of the entry candle
input double   InpDisplaceAtrMult   = 0.6;          // Min entry-candle body vs ATR
input bool     InpUseOTE            = true;          // Premium/discount (only buy discount, sell premium)
// Break-even triggers once price has covered this % of the distance to the REAL
// first-partial target (-0.27 SD) - NOT a fixed R-multiple. A fixed R trigger is
// decoupled from the setup's actual scale: too low (e.g. 1R) clamps every trade
// to scratch long before the real move starts (measured: this cratered win rate
// vs. loss size); too high (e.g. 6R) removes the early save entirely and lets
// every failed setup run to the full stop (measured: this made every loser as
// big as a full stop-loss with zero relief). Scaling it to THIS setup's own
// measured distance avoids both failure modes.
input bool     InpUseBreakEven      = true;         // Move SL to break-even after this much progress to the first partial
input double   InpBreakEvenProgressPct = 35.0;      // % of the way to the -0.27 SD target before locking break-even
input double   InpBreakEvenBufferPips= 1.5;         // Buffer beyond entry for break-even
input bool     InpCloseAtSessionEnd  = true;        // Close any open trade at NY session end
input double   InpDailyMaxLossPct    = 3.0;         // Stop for the day after this % equity loss (0=off)
input double   InpDailyTargetPct     = 0.0;         // Stop for the day after this % equity gain (0=off)
input int      InpCooldownMin        = 30;          // Minutes to pause after a losing trade

input group "=== OTE entry model (dynamic) ==="
input bool     InpUseOTEModel      = true;          // Use dynamic OTE model (else legacy IFVG entry)
input double   InpOTELow            = 0.62;         // OTE zone near edge (fib)
input double   InpOTEHigh           = 0.79;         // OTE zone far edge (fib)
// Entry trigger: 0 = OTE tap only, 1 = OTE + (displacement OR IFVG), 2 = OTE + IFVG required
// Continuation (BOS) is just a pullback re-entry into an already-established trend -
// the tap itself is enough. Reversal (CHoC) is fighting the immediately-prior
// momentum, so it needs real proof order flow shifted before entering.
input int      InpConfirmModeBOS     = 1;           // Confirmation for continuation/BOS setups
input int      InpConfirmModeCHoC    = 1;           // Confirmation for reversal/CHoC setups (needs solid proof)
input double   InpMinDisplaceLeg     = 1.0;         // Min displacement leg vs ATR to arm a setup
// Real swing/CHoC detection - the manipulation (1.0) and CHoC structure point are
// genuine swing pivots, not an artificial fixed-bar sweep window. This is what lets
// the EA see the same swings a trader draws fibs from, however many bars they span.
input int      InpChocSwingStrength  = 3;           // Fractal strength for CHoC swings (bigger = fewer, more real)
input int      InpChocLookback       = 150;         // Bars scanned on setup TF (150 x M30 = 300 x M15 - same ~3-day calendar coverage)
input double   InpChocMinRangeATR    = 1.5;         // Min swing-high-to-swing-low range (x ATR) to count as real structure
input double   InpMinStopPips        = 8.0;         // Reject if computed stop distance is below this (guards against oversized lots)
input double   InpAnchorCooldownMin  = 240;          // Don't re-arm the same failed swing anchor for this many minutes
input double   InpAnchorCooldownPips = 15.0;        // "Same anchor" tolerance (pips)
input double   InpFirstTP_SD         = 0.27;        // First partial at this SD level (~1:2)
input string   InpFinalSDs           = "2.0,2.5,3.0"; // Final-target SD candidates (confluence-picked)
input double   InpTP1_SD             = 2.0;         // Fallback final SD if none has confluence
input double   InpRunnerSD           = 3.0;         // (reserved) legacy runner SD level

input group "=== Execution & stop precision ==="
// Entry: 0 = market on confirmation (guaranteed fill), 1 = limit at OTE (best price)
input int      InpEntryExec         = 0;            // 0 = market on tap (always filled), 1 = limit at OTE
input double   InpOTEEntryFib        = 0.705;       // Fib level for the OTE limit (when InpEntryExec=1)
// Stop: 0 = beyond 1.0 manip anchor (widest), 1 = beyond 0.79 OTE edge, 2 = M1 confirmation swing (tightest)
input int      InpStopMode           = 0;           // Stop placement (0 = behind the real swing/manip anchor)
input int      InpPendingExpiryBars  = 4;           // Cancel unfilled OTE limit after N setup bars
input int      InpMicroSwingLB        = 25;         // M1 bars scanned for the confirmation swing
input int      InpMicroSwingStr       = 2;          // M1 fractal strength for the stop swing
input bool     InpMicroEntry          = false;      // Sniper: refine entry+stop to M1 FVG (for confirm mode >= 1)
input double   InpMicroPad            = 1.0;        // Extra pad (pips) around the OTE zone for the M1 FVG

input group "=== Standard-deviation projections (Asian range) ==="
input bool     InpUseSDProjection  = true;          // Project SD levels from the Asian range
input string   InpSDMultiples      = "0.5,1.0,1.5,2.0,2.5,3.0"; // Range multiples to project
input double   InpSDAlignPips       = 15.0;         // Snap SD level to liquidity within this (pips)
// Target selection: 0=liquidity only, 1=SD projection, 2=confluence (SD aligned to liquidity)
input int      InpTargetMode        = 2;            // TP mode (0 liq, 1 SD, 2 confluence)
input bool     InpShowSDLevels      = true;         // Draw SD projection lines + Asia box

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
int      hATR     = INVALID_HANDLE;

double   g_point;
double   g_pip;          // 1 pip in price terms
int      g_digits;
string   g_obj_prefix = "IBM_";

datetime g_lastSetupBarTime = 0;
datetime g_lastDay          = 0;
int      g_tradesToday      = 0;
double   g_dayStartBalance  = 0.0;
datetime g_lastLossTime     = 0;
bool     g_hadPosition      = false;

// Anchor-failure memory: don't re-fight the identical swing anchor right after
// it just stopped us out (e.g. re-taking the same broken level 40 min later).
double   g_activeAnchor     = 0.0;   // anchor the currently-open trade came from
int      g_activeDir        = 0;
double   g_lastFailedAnchor = 0.0;
int      g_lastFailedDir    = 0;
datetime g_lastFailedTime   = 0;

// Trade lifecycle state (for the single managed position)
bool     g_tp1Done          = false;
bool     g_firstDone        = false;   // first (1:R) partial taken?
bool     g_beDone           = false;
double   g_plannedTP        = 0.0;
double   g_plannedSL        = 0.0;
double   g_initRisk         = 0.0;   // initial stop distance (price terms)
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

// Standard-deviation projection state (from the Asian range)
double   g_sdMult[];        // parsed multiples
double   g_asiaHigh = 0.0;
double   g_asiaLow  = 0.0;
double   g_asiaRange = 0.0;

enum TARGET_MODE { TGT_LIQUIDITY = 0, TGT_SD = 1, TGT_CONFLUENCE = 2 };

// Dynamic OTE setup tracker. manipAnchor (the "1") is fixed once armed; the
// "0" extreme trails the displacement until price retraces into the OTE zone.
struct SetupState
{
   bool     active;
   bool     tapped;       // has price entered the OTE zone yet?
   int      dir;          // +1 long, -1 short
   double   manipAnchor;  // fib 1.0 = end of manipulation / start of displacement
   double   extreme;      // fib 0.0 = running displacement extreme (dynamic)
   datetime armedTime;
   int      pattern;      // 0 = BOS continuation, 1 = CHoC reversal
};
SetupState g_setup;
double   g_runnerTP = 0.0;   // final runner target (SD projection)
double   g_firstTP  = 0.0;   // first-partial target (-0.27 SD)
double   g_finalSDs[];       // parsed final-target SD candidates
int      hAtrMicro  = INVALID_HANDLE;
datetime g_lastMicroBar = 0;
double   g_pdHigh = 0.0, g_pdLow = 0.0;   // previous day high/low (DOL)

enum SWING_PATTERN { PATTERN_BOS = 0, PATTERN_CHOC = 1 };

// Pending (limit) order tracking for OTE execution
ulong    g_pendingTicket = 0;
datetime g_pendingExpiry = 0;
int      g_pendingDir    = 0;

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

   hEmaFast  = iMA(_Symbol, InpBiasTF, InpEmaFast, 0, MODE_EMA, PRICE_CLOSE);
   hEmaSlow  = iMA(_Symbol, InpBiasTF, InpEmaSlow, 0, MODE_EMA, PRICE_CLOSE);
   hATR      = iATR(_Symbol, InpSetupTF, InpAtrPeriod);
   hAtrMicro = iATR(_Symbol, InpMicroTF, InpAtrPeriod);
   if(hEmaFast == INVALID_HANDLE || hEmaSlow == INVALID_HANDLE ||
      hATR == INVALID_HANDLE || hAtrMicro == INVALID_HANDLE)
   {
      Print("Failed to create indicator handles");
      return(INIT_FAILED);
   }

   g_dayStartBalance = AccountInfoDouble(ACCOUNT_BALANCE);
   ArrayResize(g_buySide, 0);
   ArrayResize(g_sellSide, 0);
   ParseSDMultiples();
   ParseFinalSDs();

   Print("Institutional Blxck Mirror initialised on ", _Symbol,
         "  pip=", DoubleToString(g_pip, g_digits));
   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason)
{
   if(hEmaFast != INVALID_HANDLE) IndicatorRelease(hEmaFast);
   if(hEmaSlow != INVALID_HANDLE) IndicatorRelease(hEmaSlow);
   if(hATR      != INVALID_HANDLE) IndicatorRelease(hATR);
   if(hAtrMicro != INVALID_HANDLE) IndicatorRelease(hAtrMicro);
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

   // Manage any resting OTE limit order (expiry / killzone cancel)
   ManagePendingOrder();

   // Detect a just-closed position (for the loss cooldown)
   bool hasPos = HasOpenPosition();
   if(g_hadPosition && !hasPos)
   {
      CheckClosedResult();
      g_tp1Done = false; g_firstDone = false; g_beDone = false; g_posDir = 0;
      g_plannedTP = 0.0; g_initRisk = 0.0; g_runnerTP = 0.0; g_firstTP = 0.0;
      g_setup.active = false;
   }
   g_hadPosition = hasPos;

   // Reset daily counters at the start of a new day
   datetime today = TodayStart();
   if(today != g_lastDay)
   {
      g_lastDay         = today;
      g_tradesToday     = 0;
      g_dayStartBalance = AccountInfoDouble(ACCOUNT_BALANCE);
   }

   // Fast lane: once a setup is armed, hunt the entry on every new M1 bar so the
   // shallow 0.62-tap-and-go movers are caught on the M1 IFVG, not 15 min late.
   if(InpUseOTEModel && g_setup.active)
   {
      datetime mb = iTime(_Symbol, InpMicroTF, 0);
      if(mb != g_lastMicroBar)
      {
         g_lastMicroBar = mb;
         TryEnterArmed();
      }
   }

   // Only arm / trail setups once per completed setup-TF bar
   datetime curBar = iTime(_Symbol, InpSetupTF, 0);
   if(curBar == g_lastSetupBarTime)
      return;
   g_lastSetupBarTime = curBar;

   // Refresh structural view
   BuildLiquidityPools();
   BuildSDProjections();
   if(InpShowHeatmap)   DrawHeatmap();
   if(InpUseSDProjection && InpShowSDLevels) DrawSDLevels();
   if(InpShowDashboard) DrawDashboard();

   // Arm / trail (OTE) or one-shot entry (legacy)
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

   int score = ema + bos + htf;

   if(InpBiasMode <= 0)
   {
      // Strict: EMA and BOS on bias TF must agree; HTF must not oppose
      if(ema == BIAS_BULL && bos == BIAS_BULL && htf != BIAS_BEAR) return BIAS_BULL;
      if(ema == BIAS_BEAR && bos == BIAS_BEAR && htf != BIAS_BULL) return BIAS_BEAR;
      return BIAS_NONE;
   }
   if(InpBiasMode == 1)
   {
      // Majority: 2 of 3 signals agree, third may be neutral but not opposing enough to flip
      if(score >= 2)  return BIAS_BULL;
      if(score <= -2) return BIAS_BEAR;
      return BIAS_NONE;
   }
   // Lean (mode 2): any net agreement counts - loosest, most frequent
   if(score > 0) return BIAS_BULL;
   if(score < 0) return BIAS_BEAR;
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

   // Previous day's high/low (DOL) - the strongest draws on liquidity
   g_pdHigh = iHigh(_Symbol, PERIOD_D1, 1);
   g_pdLow  = iLow(_Symbol,  PERIOD_D1, 1);
   if(g_pdHigh > 0) { AddOrWeightPool(g_buySide,  g_pdHigh, iTime(_Symbol, InpSetupTF, 1), +1, tol);
                      WeightPool(g_buySide,  g_pdHigh, tol, 2); }
   if(g_pdLow  > 0) { AddOrWeightPool(g_sellSide, g_pdLow,  iTime(_Symbol, InpSetupTF, 1), -1, tol);
                      WeightPool(g_sellSide, g_pdLow,  tol, 2); }

   TrimPools(g_buySide,  InpMaxLiqPools, true);   // keep the highest buy-side
   TrimPools(g_sellSide, InpMaxLiqPools, false);  // keep the lowest sell-side
}

// Bump the weight of the pool nearest a price (used to mark DOL levels heavier).
void WeightPool(LiqPool &arr[], double price, double tol, int addWeight)
{
   for(int i = 0; i < ArraySize(arr); i++)
      if(arr[i].valid && MathAbs(arr[i].price - price) <= tol) { arr[i].touches += addWeight; return; }
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

// Convert a server timestamp to a NEW YORK hour (0..23)
int ToNYHour(datetime t)
{
   MqlDateTime dt;
   TimeToStruct(t, dt);
   int h = dt.hour + InpServerToNYOffset;
   h = ((h % 24) + 24) % 24;
   return h;
}

int CurrentNYHour()
{
   return ToNYHour(TimeCurrent());
}

// Session membership in NY time, with wrap-around past midnight support.
// end == start => empty; end <= start => the window wraps midnight.
bool InSessionNY(int h, int startH, int endH)
{
   if(startH == endH) return false;
   if(startH < endH)  return (h >= startH && h < endH);
   return (h >= startH || h < endH); // wraps midnight
}

bool InKillzone()
{
   int h = CurrentNYHour();
   if(InpTradeLondon  && InSessionNY(h, InpLondonStart, InpLondonEnd)) return true;
   if(InpTradeNewYork && InSessionNY(h, InpNYStart,     InpNYEnd))     return true;
   if(InpTradeAsia    && InSessionNY(h, InpAsiaStart,   InpAsiaEnd))   return true;
   return false;
}

// Current NY time as a decimal hour (e.g. 9:30 -> 9.5) for prime-window checks.
double NYDecimalHourNow()
{
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   int totalMin = (dt.hour + InpServerToNYOffset) * 60 + dt.min;
   totalMin = ((totalMin % 1440) + 1440) % 1440;
   return totalMin / 60.0;
}

bool InRangeDec(double h, double startH, double endH)
{
   if(startH == endH) return false;
   if(startH < endH) return (h >= startH && h < endH);
   return (h >= startH || h < endH); // wraps midnight
}

// Restricts ENTRY (not arming/tracking) to the tight sub-window each session's
// OTE tap statistically clusters in. Setups can still arm and trail any time
// within the broader killzone; this only gates whether we're allowed to fire.
bool InPrimeWindow()
{
   if(!InpUsePrimeWindow) return true;
   int h = CurrentNYHour();

   if(InpTradeAsia && InSessionNY(h, InpAsiaStart, InpAsiaEnd))
      return true; // no prime sub-window defined for Asia - unrestricted

   double hd = NYDecimalHourNow();
   if(InpTradeLondon && InSessionNY(h, InpLondonStart, InpLondonEnd))
      return InRangeDec(hd, InpLondonPrimeStart, InpLondonPrimeEnd);
   if(InpTradeNewYork && InSessionNY(h, InpNYStart, InpNYEnd))
      return InRangeDec(hd, InpNYPrimeStart, InpNYPrimeEnd);

   return true; // shouldn't be reached - InKillzone() already gates this
}

// Range of the most recent COMPLETED occurrence of a session (previous session),
// evaluated in NY time. Walks back to the first in-session block and captures it.
bool PreviousSessionRange(int startH, int endH, double &hi, double &lo)
{
   hi = -DBL_MAX; lo = DBL_MAX;
   int scan = 1440 / PeriodMinutesSafe(InpSetupTF) + 5; // ~ one day of setup-TF bars
   scan = MathMax(scan, 30);
   bool found = false;

   for(int i = 1; i < scan * 3; i++)
   {
      datetime t = iTime(_Symbol, InpSetupTF, i);
      if(t == 0) break;
      bool inSess = InSessionNY(ToNYHour(t), startH, endH);
      if(inSess)
      {
         // Capture the FIRST (most recent) completed session block we encounter
         hi = MathMax(hi, iHigh(_Symbol, InpSetupTF, i));
         lo = MathMin(lo, iLow(_Symbol, InpSetupTF, i));
         found = true;
      }
      else if(found)
      {
         break; // stepped out of the most recent session block -> done
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
// ---- Real swing/CHoC detection (replaces the fixed-bar-window sweep guess) ----
// Finds the most recent GENUINE change-of-character: a confirmed swing pivot that
// gets manipulated (wicked through) followed by a close through the opposing
// structural swing point. The leg can span any number of bars - it is anchored to
// real price structure, not an arbitrary lookback window.
//   dir = BIAS_BEAR: H = last confirmed swing high (the liquidity), L = the swing
//                    low preceding it (the higher-low structure CHoC must break).
//   dir = BIAS_BULL: mirrored (L = swept low, H = swing high structure to break).
// manipAnchor (fib 1.0) = the true extreme reached while sweeping H/L (a wick can,
// and usually does, exceed the old fractal price itself).
// extreme (fib 0.0) = the running extreme of the impulsive CHoC leg so far - this
// keeps being trailed bar-by-bar by the existing dynamic OTE logic until tapped.
bool FindCHoC(const MqlRates &r[], int dir, double &manipAnchor, double &extreme, int &sweepIdx)
{
   int n = ArraySize(r);
   int strength = InpChocSwingStrength;
   int bound = MathMin(InpChocLookback, n - strength);
   if(bound <= strength + 2) return false;
   double atr = AtrValue();

   if(dir == BIAS_BEAR)
   {
      for(int iH = strength; iH < bound; iH++)
      {
         if(!IsSwingHigh(r, iH, strength)) continue;

         int iL = -1;
         for(int j = iH + 1; j < bound; j++)
            if(IsSwingLow(r, j, strength)) { iL = j; break; }
         if(iL < 0) continue;

         double Hh = r[iH].high, Ll = r[iL].low;
         if(atr > 0.0 && (Hh - Ll) < InpChocMinRangeATR * atr) continue; // too small - noise, not real structure

         // manipulation: does a later (more recent) bar wick beyond H?
         int sIdx = -1; double manipExt = Hh;
         for(int k = iH - 1; k >= 1; k--)
            if(r[k].high > manipExt) { manipExt = r[k].high; sIdx = k; }
         if(sIdx < 0) continue; // H hasn't been swept yet

         // CHoC confirmation: a close beyond L after the sweep
         bool choc = false;
         for(int m = sIdx - 1; m >= 0; m--)
            if(r[m].close < Ll) { choc = true; break; }
         if(!choc) continue;

         double lo = DBL_MAX;
         for(int p = sIdx; p >= 1; p--) lo = MathMin(lo, r[p].low);

         manipAnchor = manipExt;
         extreme     = lo;
         sweepIdx    = sIdx;
         return true;
      }
      return false;
   }
   else // BIAS_BULL (mirrored)
   {
      for(int iL = strength; iL < bound; iL++)
      {
         if(!IsSwingLow(r, iL, strength)) continue;

         int iH = -1;
         for(int j = iL + 1; j < bound; j++)
            if(IsSwingHigh(r, j, strength)) { iH = j; break; }
         if(iH < 0) continue;

         double Ll = r[iL].low, Hh = r[iH].high;
         if(atr > 0.0 && (Hh - Ll) < InpChocMinRangeATR * atr) continue;

         int sIdx = -1; double manipExt = Ll;
         for(int k = iL - 1; k >= 1; k--)
            if(r[k].low < manipExt) { manipExt = r[k].low; sIdx = k; }
         if(sIdx < 0) continue;

         bool choc = false;
         for(int m = sIdx - 1; m >= 0; m--)
            if(r[m].close > Hh) { choc = true; break; }
         if(!choc) continue;

         double hi = -DBL_MAX;
         for(int p = sIdx; p >= 1; p--) hi = MathMax(hi, r[p].high);

         manipAnchor = manipExt;
         extreme     = hi;
         sweepIdx    = sIdx;
         return true;
      }
      return false;
   }
}

// ---- Continuation pattern: clean Break Of Structure, no manipulation needed ----
// dir = BIAS_BULL: H = last confirmed swing high; a later bar CLOSES beyond it
// (BOS - the trend simply extends). anchor (fib 1.0) = the swing LOW that started
// that impulsive leg (the base); extreme (fib 0.0) = the new high made since the
// break, trailing further exactly like the CHoC case. Mirrored for BIAS_BEAR.
bool FindBOS(const MqlRates &r[], int dir, double &anchor, double &extreme, int &breakIdx)
{
   int n = ArraySize(r);
   int strength = InpChocSwingStrength;
   int bound = MathMin(InpChocLookback, n - strength);
   if(bound <= strength + 2) return false;
   double atr = AtrValue();

   if(dir == BIAS_BULL)
   {
      for(int iH = strength; iH < bound; iH++)
      {
         if(!IsSwingHigh(r, iH, strength)) continue;

         int iL = -1;
         for(int j = iH + 1; j < bound; j++)
            if(IsSwingLow(r, j, strength)) { iL = j; break; }
         if(iL < 0) continue;

         double Hh = r[iH].high, Ll = r[iL].low;
         if(atr > 0.0 && (Hh - Ll) < InpChocMinRangeATR * atr) continue;

         // BOS: the most recent bar whose CLOSE broke above H (clean continuation)
         int bIdx = -1;
         for(int k = iH - 1; k >= 1; k--)
            if(r[k].close > Hh) bIdx = k;
         if(bIdx < 0) continue;

         double hi = -DBL_MAX;
         for(int p = bIdx; p >= 1; p--) hi = MathMax(hi, r[p].high);

         anchor   = Ll;
         extreme  = hi;
         breakIdx = bIdx;
         return true;
      }
      return false;
   }
   else // BIAS_BEAR (mirrored)
   {
      for(int iL = strength; iL < bound; iL++)
      {
         if(!IsSwingLow(r, iL, strength)) continue;

         int iH = -1;
         for(int j = iL + 1; j < bound; j++)
            if(IsSwingHigh(r, j, strength)) { iH = j; break; }
         if(iH < 0) continue;

         double Ll = r[iL].low, Hh = r[iH].high;
         if(atr > 0.0 && (Hh - Ll) < InpChocMinRangeATR * atr) continue;

         int bIdx = -1;
         for(int k = iL - 1; k >= 1; k--)
            if(r[k].close < Ll) bIdx = k;
         if(bIdx < 0) continue;

         double lo = DBL_MAX;
         for(int p = bIdx; p >= 1; p--) lo = MathMin(lo, r[p].low);

         anchor   = Hh;
         extreme  = lo;
         breakIdx = bIdx;
         return true;
      }
      return false;
   }
}

// Map the market generically: try both patterns and take whichever's triggering
// event (break/sweep) is most recent - "whichever is the most obvious major
// swing point," not a pattern-type preference.
bool FindSwingLeg(const MqlRates &r[], int dir, double &anchor, double &extreme, int &evIdx, int &pattern)
{
   double aB = 0, eB = 0; int iB = -1;
   double aC = 0, eC = 0; int iC = -1;
   bool hasBos  = FindBOS(r, dir, aB, eB, iB);
   bool hasChoc = FindCHoC(r, dir, aC, eC, iC);

   if(!hasBos && !hasChoc) return false;
   if(hasBos && (!hasChoc || iB <= iC))
   { anchor = aB; extreme = eB; evIdx = iB; pattern = PATTERN_BOS; return true; }

   anchor = aC; extreme = eC; evIdx = iC; pattern = PATTERN_CHOC;
   return true;
}

bool DetectLiquiditySweep(const MqlRates &r[], int bias, double &liqLevel, int &sweepIdx)
{
   sweepIdx = -1;
   double minPen = g_pip * InpSweepMinPips;

   double sessH, sessL;
   // Use the most relevant previous session (Asia for London killzone; London for NY)
   bool haveAsia   = PreviousSessionRange(InpAsiaStart,   InpAsiaEnd,   sessH, sessL);
   double lonH, lonL;
   bool haveLondon = PreviousSessionRange(InpLondonStart, InpLondonEnd, lonH, lonL);

   int h = CurrentNYHour();
   bool inNY     = InSessionNY(h, InpNYStart,     InpNYEnd);
   bool inLondon = InSessionNY(h, InpLondonStart, InpLondonEnd);
   bool inAsia   = InSessionNY(h, InpAsiaStart,   InpAsiaEnd);

   double targetHigh, targetLow;
   bool haveTarget = false;

   if(inNY && haveLondon)          { targetHigh = lonH;  targetLow = lonL;  haveTarget = true; } // NY -> sweep London
   else if(inLondon && haveAsia)   { targetHigh = sessH; targetLow = sessL; haveTarget = true; } // London -> sweep Asia
   else if(inAsia)
   {
      double nyH, nyL;
      if(PreviousSessionRange(InpNYStart, InpNYEnd, nyH, nyL))         // Asia -> sweep prior NY session
      { targetHigh = nyH; targetLow = nyL; haveTarget = true; }
   }

   if(!haveTarget)
   {
      // fallback: whichever prior session range is available
      if(haveLondon)     { targetHigh = lonH;  targetLow = lonL;  }
      else if(haveAsia)  { targetHigh = sessH; targetLow = sessL; }
      else return false;
   }

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
//  DYNAMIC OTE ENTRY MODEL                                         //
//==================================================================//
// Price at a fib level of the manipulation leg. level 1 = manipAnchor,
// level 0 = extreme, negatives = SD projections beyond the extreme.
double OTEPrice(double level)
{
   return g_setup.extreme + level * (g_setup.manipAnchor - g_setup.extreme);
}

// Displacement candle closing back in the trend direction.
bool DisplacementConfirms(const MqlRates &r[], int dir)
{
   if(!IsDisplacement(r, 1)) return false;
   return (dir > 0) ? (r[1].close > r[1].open) : (r[1].close < r[1].open);
}

// Is there an inversion FVG (order-flow shift) in the trend direction recently?
bool IFVGConfirms(const MqlRates &r[], int dir)
{
   int scan = MathMin(InpSweepMaxBars + 2, ArraySize(r) - 3);
   for(int i = 1; i <= scan; i++)
   {
      FVG f;
      if(!FvgAt(r, i, f)) continue;
      if(dir > 0 && f.dir == -1)
         for(int j = i - 1; j >= 0; j--) if(r[j].close > f.top) return true;
      if(dir < 0 && f.dir == +1)
         for(int j = i - 1; j >= 0; j--) if(r[j].close < f.bottom) return true;
   }
   return false;
}

void ResetSetup()
{
   g_setup.active = false;
   g_setup.dir    = 0;
   ObjectsDeleteAll(0, g_obj_prefix + "OTE_");
}

// Minimum valid stop distance (broker stops level + spread + small cushion).
double MinStopDistance()
{
   long lvl = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
   double d = (lvl > 0 ? lvl * g_point : 0.0);
   double spread = SymbolInfoDouble(_Symbol, SYMBOL_ASK) - SymbolInfoDouble(_Symbol, SYMBOL_BID);
   return d + spread + g_pip * 0.5;
}

double EnforceMinStop(int dir, double entry, double sl)
{
   double m = MinStopDistance();
   if(dir > 0 && (entry - sl) < m) sl = entry - m;
   if(dir < 0 && (sl - entry) < m) sl = entry + m;
   return sl;
}

// Most recent M1 swing extreme on the correct side of the entry (tight structural stop).
double MicroSwingStop(int dir, double entry)
{
   MqlRates m[];
   ArraySetAsSeries(m, true);
   int n = InpMicroSwingLB + InpMicroSwingStr * 2 + 2;
   if(CopyRates(_Symbol, InpMicroTF, 0, n, m) < n) return 0.0;
   for(int i = InpMicroSwingStr; i < n - InpMicroSwingStr; i++)
   {
      if(dir > 0 && IsSwingLow(m, i, InpMicroSwingStr)  && m[i].low  < entry) return m[i].low;
      if(dir < 0 && IsSwingHigh(m, i, InpMicroSwingStr) && m[i].high > entry) return m[i].high;
   }
   return 0.0;
}

// Structural stop per InpStopMode. ATR floor only applies to the widest mode.
double ComputeStop(int dir, double entry)
{
   double buf = g_pip * InpSlBufferPips;
   double s;
   if(InpStopMode == 2)
   {
      double sw = MicroSwingStop(dir, entry);
      if(sw > 0.0) s = (dir > 0) ? (sw - buf) : (sw + buf);
      else         s = (dir > 0) ? (g_setup.manipAnchor - buf) : (g_setup.manipAnchor + buf);
   }
   else if(InpStopMode == 1)
   {
      double edge = OTEPrice(InpOTEHigh);
      s = (dir > 0) ? (edge - buf) : (edge + buf);
   }
   else
   {
      s = (dir > 0) ? (g_setup.manipAnchor - buf) : (g_setup.manipAnchor + buf);
      double atr = AtrValue();
      if(InpUseAtrStop && atr > 0.0)
         s = (dir > 0) ? MathMin(s, entry - atr * InpAtrMultSL)
                       : MathMax(s, entry + atr * InpAtrMultSL);
   }
   return EnforceMinStop(dir, entry, s);
}

// Sniper refinement: nearest M1 FVG whose proximal edge sits inside the OTE zone,
// in the trade direction. Entry = proximal edge; stop = just beyond the far edge.
// Returns the tightest structural entry/stop available after confirmation.
bool MicroEntryRefine(int dir, double zLo, double zHi, double &entryOut, double &slOut)
{
   MqlRates m[];
   ArraySetAsSeries(m, true);
   int cnt = InpMicroFvgScan + 3;
   if(CopyRates(_Symbol, InpMicroTF, 0, cnt, m) < cnt) return false;

   double pad = InpMicroPad * g_pip;
   double lo  = zLo - pad, hi = zHi + pad;
   double ref = (zLo + zHi) / 2.0;
   double buf = g_pip * InpSlBufferPips;

   bool   got = false;
   double best = DBL_MAX, e = 0.0, s = 0.0;

   for(int i = 0; i < cnt - 2; i++)
   {
      FVG f;
      if(!FvgAt(m, i, f)) continue;

      if(dir > 0 && f.dir == +1)          // bullish M1 FVG for a long
      {
         double prox = f.top;             // first edge price touches on the way down
         if(prox < lo || prox > hi) continue;
         double d = MathAbs(prox - ref);
         if(d < best) { best = d; e = f.top; s = f.bottom - buf; got = true; }
      }
      else if(dir < 0 && f.dir == -1)     // bearish M1 FVG for a short
      {
         double prox = f.bottom;
         if(prox < lo || prox > hi) continue;
         double d = MathAbs(prox - ref);
         if(d < best) { best = d; e = f.bottom; s = f.top + buf; got = true; }
      }
   }
   if(got) { entryOut = e; slOut = EnforceMinStop(dir, e, s); }
   return got;
}

// Cancel a resting OTE limit if it expires or the killzone closes.
void ManagePendingOrder()
{
   if(g_pendingTicket == 0) return;
   if(!OrderSelect(g_pendingTicket)) { g_pendingTicket = 0; return; } // filled or already gone

   bool cancel = (!InKillzone()) || (TimeCurrent() >= g_pendingExpiry);
   if(cancel)
   {
      trade.OrderDelete(g_pendingTicket);
      g_pendingTicket = 0;
      g_plannedTP = 0.0; g_runnerTP = 0.0; g_initRisk = 0.0;
      ObjectsDeleteAll(0, g_obj_prefix + "OTE_");
   }
}

void ParseFinalSDs()
{
   ArrayResize(g_finalSDs, 0);
   string parts[];
   int c = StringSplit(InpFinalSDs, ',', parts);
   for(int i = 0; i < c; i++)
   {
      string s = parts[i];
      StringTrimLeft(s); StringTrimRight(s);
      double v = StringToDouble(s);
      if(v > 0.0) { int sz = ArraySize(g_finalSDs); ArrayResize(g_finalSDs, sz + 1); g_finalSDs[sz] = v; }
   }
   if(ArraySize(g_finalSDs) == 0) { ArrayResize(g_finalSDs, 1); g_finalSDs[0] = InpTP1_SD; }
}

double MicroAtrValue()
{
   if(hAtrMicro == INVALID_HANDLE) return 0.0;
   double a[1];
   if(CopyBuffer(hAtrMicro, 0, 0, 1, a) < 1) return 0.0;
   return a[0];
}

// Displacement bar on an arbitrary TF's rates, using that TF's ATR.
bool DispConfirmTF(const MqlRates &r[], int dir, double atr)
{
   double range = r[1].high - r[1].low;
   if(range <= 0.0) return false;
   double body = MathAbs(r[1].close - r[1].open);
   if(body / range * 100.0 < InpMinBodyPct) return false;
   if(atr > 0.0 && body < InpDisplaceAtrMult * atr) return false;
   return (dir > 0) ? (r[1].close > r[1].open) : (r[1].close < r[1].open);
}

// Is an Asian-range SD level near this price? (confluence booster)
bool AsiaSDNear(int dir, double price, double tol)
{
   if(g_asiaRange <= 0.0) return false;
   for(int i = 0; i < ArraySize(g_sdMult); i++)
   {
      double lvl = SDLevel(dir, g_sdMult[i]);
      if(lvl > 0.0 && MathAbs(lvl - price) <= tol) return true;
   }
   return false;
}

// Is a key liquidity level (session pool or previous-day high/low) near this price?
bool KeyLevelNear(int dir, double price, double tol)
{
   if(LiquidityNear(dir, price, tol)) return true;
   if(dir > 0 && g_pdHigh > 0.0 && MathAbs(price - g_pdHigh) <= tol) return true;
   if(dir < 0 && g_pdLow  > 0.0 && MathAbs(price - g_pdLow)  <= tol) return true;
   return false;
}

// Weight of the liquidity pool nearest this price (its touches count - equal
// highs/lows and DOL score higher). 0 if nothing matches within tolerance.
int PoolWeight(int dir, double price, double tol)
{
   int w = 0;
   if(dir > 0)
   {
      for(int i = 0; i < ArraySize(g_buySide); i++)
         if(g_buySide[i].valid && MathAbs(g_buySide[i].price - price) <= tol)
            w = MathMax(w, g_buySide[i].touches);
   }
   else
   {
      for(int i = 0; i < ArraySize(g_sellSide); i++)
         if(g_sellSide[i].valid && MathAbs(g_sellSide[i].price - price) <= tol)
            w = MathMax(w, g_sellSide[i].touches);
   }
   return w;
}

// Choose the final target: the swing point with the most liquidity AND a key
// level that lines up with an SD zone - not just any SD projection. Score stacks:
// base + Asia-range SD alignment + liquidity-pool weight (DOL/equal-highs score
// higher the more "touches" they carry).
double ChooseFinalTarget(int dir, double entry)
{
   double tol = InpSDAlignPips * g_pip;
   double best = 0.0; double bestScore = -1.0; double bestDist = DBL_MAX;
   for(int i = 0; i < ArraySize(g_finalSDs); i++)
   {
      double price = OTEPrice(-g_finalSDs[i]);
      if(price <= 0.0) continue;

      double score = 1.0;
      if(AsiaSDNear(dir, price, tol)) score += 1.0;             // aligns with Asia-range deviation
      int pw = PoolWeight(dir, price, tol);
      if(pw > 0)                        score += 2.0 + pw;      // real liquidity here - heavier pool ranks higher
      else if(KeyLevelNear(dir, price, tol)) score += 2.0;       // fallback key-level check

      double dist = MathAbs(price - entry);
      if(score > bestScore || (score == bestScore && dist < bestDist))
      { bestScore = score; bestDist = dist; best = price; }
   }
   if(best <= 0.0) best = OTEPrice(-InpTP1_SD);
   return best;
}

// ---- M15: arm the setup and trail the dynamic OTE leg (no entry here) ----
void EvaluateOTESetup()
{
   if(HasOpenPosition()) { ResetSetup(); return; }
   if(g_pendingTicket != 0) return;   // an OTE limit is already resting

   int n = MathMax(InpSetupLookback, InpChocLookback) + InpChocSwingStrength * 2 + 10;
   MqlRates r[];
   ArraySetAsSeries(r, true);
   if(CopyRates(_Symbol, InpSetupTF, 0, n, r) < n) return;

   bool inKZ = InKillzone();

   if(!g_setup.active)
   {
      if(!inKZ) return;
      if(g_tradesToday >= InpMaxTradesPerDay) return;
      if(DailyGuardBlocked() || InCooldown() || IsNewsTime()) return;

      int bias = InstitutionalBias();
      if(bias == BIAS_NONE) return;

      // Map the market generically: try both a continuation BOS and a reversal
      // CHoC in the bias direction, take whichever's triggering event is most
      // recent - the most obvious major swing right now, of either type, on
      // real structure of any length (not a fixed-bar window).
      double manip, ext; int evIdx; int pattern;
      if(!FindSwingLeg(r, bias, manip, ext, evIdx, pattern)) return;
      if(AnchorRecentlyFailed(bias, manip)) return; // don't re-arm a swing that just failed

      double atr = AtrValue();
      if(atr > 0.0 && MathAbs(ext - manip) < InpMinDisplaceLeg * atr) return; // no real displacement

      g_setup.active      = true;
      g_setup.tapped      = false;
      g_setup.dir         = bias;
      g_setup.manipAnchor = manip;
      g_setup.extreme     = ext;
      g_setup.armedTime   = TimeCurrent();
      g_setup.pattern     = pattern;
      return;
   }

   int dir = g_setup.dir;
   if(!inKZ) { ResetSetup(); return; }
   if(dir > 0 && r[1].close < g_setup.manipAnchor) { ResetSetup(); return; }
   if(dir < 0 && r[1].close > g_setup.manipAnchor) { ResetSetup(); return; }

   // trail the "0" extreme only until price taps the OTE; after a tap the leg is
   // locked (we stop re-anchoring and wait for the entry confirmation).
   if(!g_setup.tapped)
   {
      if(dir > 0) g_setup.extreme = MathMax(g_setup.extreme, r[1].high);
      else        g_setup.extreme = MathMin(g_setup.extreme, r[1].low);
   }

   if(InpShowSDLevels) DrawOTE();
}

// ---- M1: hunt the entry once armed (catches shallow 0.62-tap-and-go movers) ----
void TryEnterArmed()
{
   if(!g_setup.active) return;
   if(HasOpenPosition() || g_pendingTicket != 0) return;
   if(!InKillzone()) { ResetSetup(); return; }
   if(g_tradesToday >= InpMaxTradesPerDay) return;
   if(DailyGuardBlocked() || InCooldown() || IsNewsTime()) return;
   if(SpreadPips() > InpMaxSpreadPips) return;

   int dir = g_setup.dir;
   MqlRates m[];
   ArraySetAsSeries(m, true);
   int cnt = MathMax(InpMicroFvgScan + 3, InpMicroSwingLB + InpMicroSwingStr * 2 + 3);
   if(CopyRates(_Symbol, InpMicroTF, 0, cnt, m) < cnt) return;

   // Re-anchor the "0" extreme ONLY until price first taps the OTE. Once tapped,
   // the leg is locked and we simply wait for the confirmation to enter (a 0.62
   // tap-and-reject is a valid entry, not a reason to re-anchor). This trailing
   // happens regardless of the prime window - the underlying swing can keep
   // developing all session.
   if(!g_setup.tapped)
   {
      if(dir > 0) g_setup.extreme = MathMax(g_setup.extreme, m[1].high);
      else        g_setup.extreme = MathMin(g_setup.extreme, m[1].low);
   }

   // invalidation on an M1 close beyond the manipulation anchor
   if(dir > 0 && m[1].close < g_setup.manipAnchor) { ResetSetup(); return; }
   if(dir < 0 && m[1].close > g_setup.manipAnchor) { ResetSetup(); return; }

   // The tap+confirmation that fires a trade only counts INSIDE the prime window
   // - not just the order placement. Without this, a setup that tapped+confirmed
   // hours earlier (waiting for the window) fires blind the instant the window
   // opens, on a price that may have already run well away from the real OTE
   // reaction. Backtest evidence: 31% of trades fired at the exact literal
   // window-open tick, and several of the fastest, cleanest stop-outs were
   // exactly these stale fires. So a tap outside the window is never allowed to
   // persist into it - it must tap+confirm again, live, once we're inside.
   if(!InPrimeWindow())
   {
      g_setup.tapped = false;
      return;
   }

   double zA = OTEPrice(InpOTELow), zB = OTEPrice(InpOTEHigh);
   double zHi = MathMax(zA, zB), zLo = MathMin(zA, zB);

   // register the OTE tap (0.62 edge counts) - only meaningful once inside the window
   if(!g_setup.tapped && m[1].low <= zHi && m[1].high >= zLo) g_setup.tapped = true;
   if(!g_setup.tapped) return;

   // confirmation on M1 (this is the M1 IFVG entry for the shallow-reject movers) -
   // continuation (BOS) and reversal (CHoC) get their own confirmation bar
   double atrM1 = MicroAtrValue();
   bool disp = DispConfirmTF(m, dir, atrM1);
   bool ifvg = IFVGConfirms(m, dir);
   int confMode = (g_setup.pattern == PATTERN_BOS) ? InpConfirmModeBOS : InpConfirmModeCHoC;
   bool confirmed;
   if(confMode <= 0)      confirmed = true;
   else if(confMode == 1) confirmed = (disp || ifvg);
   else                   confirmed = ifvg;
   if(!confirmed) return;

   // Don't re-fight the same swing anchor that just failed (see AnchorRecentlyFailed)
   if(AnchorRecentlyFailed(dir, g_setup.manipAnchor)) { ResetSetup(); return; }

   PlaceOTEOrder(dir, zLo, zHi);
}

// Build and place the OTE trade (limit at OTE / M1-FVG with market fallback).
void PlaceOTEOrder(int dir, double zLo, double zHi)
{
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double market = (dir > 0) ? ask : bid;
   double minGap = MinStopDistance();

   bool   useLimit = (InpEntryExec == 1);
   double desired  = useLimit ? OTEPrice(InpOTEEntryFib) : market;

   // Sniper: refine entry+stop to the M1 FVG inside the OTE zone.
   bool   haveMicro = false;
   double microEntry = 0.0, microSL = 0.0;
   if(InpMicroEntry && MicroEntryRefine(dir, zLo, zHi, microEntry, microSL))
   {
      haveMicro = true;
      if(useLimit) desired = microEntry;
   }

   if(useLimit)
   {
      if(dir > 0 && !(desired < ask - minGap)) useLimit = false;
      if(dir < 0 && !(desired > bid + minGap)) useLimit = false;
   }
   double entryPrice = useLimit ? desired : market;

   double sl = (haveMicro && useLimit) ? EnforceMinStop(dir, entryPrice, microSL)
                                       : ComputeStop(dir, entryPrice);
   double risk = MathAbs(entryPrice - sl);
   if(risk <= 0.0) { ResetSetup(); return; }
   // Guard against a degenerate/stale setup producing a suspiciously tiny stop,
   // which forces an oversized position for the same % risk (seen in backtest:
   // several trades sized 3-8x normal off a freak-tight stop distance).
   if(risk / g_pip < InpMinStopPips) { ResetSetup(); return; }

   double firstTP = OTEPrice(-InpFirstTP_SD);           // -0.27 SD (~1:2)
   double finalTP = ChooseFinalTarget(dir, entryPrice); // -2/-2.5/-3 SD by confluence
   double reward  = MathAbs(finalTP - entryPrice);
   if(reward / risk < InpMinRR) { ResetSetup(); return; }
   if(InpMaxStopPips > 0.0 && risk / g_pip > InpMaxStopPips) { ResetSetup(); return; }

   double lots = CalcLots(risk);
   if(lots <= 0.0) { ResetSetup(); return; }

   double slN = NormalizeDouble(sl, g_digits);
   double tpN = NormalizeDouble(finalTP, g_digits);
   bool ok = false;
   string cmt = BuildTradeComment(dir);

   if(useLimit)
   {
      double pxN = NormalizeDouble(entryPrice, g_digits);
      ok = (dir > 0) ? trade.BuyLimit(lots, pxN, _Symbol, slN, tpN, ORDER_TIME_GTC, 0, cmt)
                     : trade.SellLimit(lots, pxN, _Symbol, slN, tpN, ORDER_TIME_GTC, 0, cmt);
      if(ok)
      {
         g_pendingTicket = trade.ResultOrder();
         g_pendingExpiry = TimeCurrent() + (long)InpPendingExpiryBars * PeriodSeconds(InpSetupTF);
         g_pendingDir    = dir;
      }
   }
   else
   {
      ok = (dir > 0) ? trade.Buy(lots, _Symbol, 0.0, slN, tpN, cmt)
                     : trade.Sell(lots, _Symbol, 0.0, slN, tpN, cmt);
   }

   if(ok)
   {
      g_tradesToday++;
      g_tp1Done   = false;
      g_beDone    = false;
      g_firstDone = false;
      g_firstTP   = firstTP;
      g_plannedTP = finalTP;
      g_runnerTP  = finalTP;
      g_plannedSL = sl;
      g_initRisk  = risk;
      g_posDir    = dir;
      g_activeAnchor = g_setup.manipAnchor;
      g_activeDir    = dir;
      PrintFormat("OTE [%s] %s %s lots=%.2f @ %.5f sl=%.5f (%.1f pips) first=%.5f final=%.5f RR=%.2f",
                  (g_setup.pattern == PATTERN_BOS ? "BOS" : "CHoC"),
                  (useLimit ? "LIMIT" : "MARKET"), (dir > 0 ? "BUY" : "SELL"),
                  lots, entryPrice, sl, risk / g_pip, firstTP, finalTP, reward / risk);
   }
   else
      PrintFormat("OTE order failed: %d %s", trade.ResultRetcode(), trade.ResultRetcodeDescription());

   ResetSetup();
}

// Draw the live OTE zone + SD target ladder for the armed setup.
void DrawOTE()
{
   ObjectsDeleteAll(0, g_obj_prefix + "OTE_");
   if(!g_setup.active) return;

   int dir = g_setup.dir;
   datetime t1 = g_setup.armedTime;
   datetime t2 = iTime(_Symbol, InpSetupTF, 0) + PeriodSeconds(InpSetupTF) * 6;

   // OTE zone box
   double zA = OTEPrice(InpOTELow), zB = OTEPrice(InpOTEHigh);
   string zone = g_obj_prefix + "OTE_ZONE";
   ObjectCreate(0, zone, OBJ_RECTANGLE, 0, t1, zA, t2, zB);
   ObjectSetInteger(0, zone, OBJPROP_COLOR, clrMediumPurple);
   ObjectSetInteger(0, zone, OBJPROP_FILL, true);
   ObjectSetInteger(0, zone, OBJPROP_BACK, true);
   ObjectSetString(0, zone, OBJPROP_TOOLTIP, "OTE 0.62-0.79 entry zone");

   // key levels: manip anchor (1), extreme (0), entry, TP, runner
   DrawOTELine("OTE_ANCHOR", g_setup.manipAnchor, t1, t2, clrGray,   "manipulation (1.0)");
   DrawOTELine("OTE_EXT",    g_setup.extreme,     t1, t2, clrGray,   "extreme (0.0)");
   DrawOTELine("OTE_ENTRY",  OTEPrice(InpOTEEntryFib), t1, t2, clrDeepSkyBlue,
               StringFormat("entry limit (%.3f)", InpOTEEntryFib));
   DrawOTELine("OTE_FIRST",  OTEPrice(-InpFirstTP_SD), t1, t2, clrOrange,
               StringFormat("first partial -%.2f SD", InpFirstTP_SD));
   // final-target candidates; the confluence pick is highlighted
   double tol = InpSDAlignPips * g_pip;
   for(int i = 0; i < ArraySize(g_finalSDs); i++)
   {
      double lvl = OTEPrice(-g_finalSDs[i]);
      bool key = KeyLevelNear(dir, lvl, tol);
      bool asd = AsiaSDNear(dir, lvl, tol);
      color c  = key ? clrGold : (asd ? clrYellow : clrGreen);
      DrawOTELine("OTE_FIN" + DoubleToString(g_finalSDs[i], 1), lvl, t1, t2, c,
                  StringFormat("final -%.1f SD%s%s", g_finalSDs[i],
                               key ? "  +DOL/liquidity" : "", asd ? "  +Asia-SD" : ""));
   }
}

void DrawOTELine(string tag, double price, datetime t1, datetime t2, color c, string tip)
{
   string nm = g_obj_prefix + tag;
   ObjectCreate(0, nm, OBJ_TREND, 0, t1, price, t2, price);
   ObjectSetInteger(0, nm, OBJPROP_COLOR, c);
   ObjectSetInteger(0, nm, OBJPROP_STYLE, STYLE_DOT);
   ObjectSetInteger(0, nm, OBJPROP_RAY_RIGHT, false);
   ObjectSetInteger(0, nm, OBJPROP_BACK, true);
   ObjectSetString(0, nm, OBJPROP_TOOLTIP, tip);
}

//==================================================================//
//  SETUP EVALUATION + ENTRY (legacy IFVG model)                    //
//==================================================================//
void EvaluateSetup()
{
   if(InpUseOTEModel) { EvaluateOTESetup(); return; }
   if(HasOpenPosition()) return;
   if(!InKillzone()) return;
   if(g_tradesToday >= InpMaxTradesPerDay) return;
   if(SpreadPips() > InpMaxSpreadPips) return;
   if(DailyGuardBlocked()) return;
   if(InCooldown()) return;
   if(IsNewsTime()) return;

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

   // 3b) displacement filter: the confirmation candle must be a strong, intentional move
   if(InpUseDisplacement && !IsDisplacement(r, 1)) return;

   // 3c) premium/discount (OTE): only buy from discount, only sell from premium
   if(InpUseOTE && !PassesOTE(r, bias)) return;

   // 4) build the trade
   double entry = SymbolInfoDouble(_Symbol, (bias == BIAS_BULL) ? SYMBOL_ASK : SYMBOL_BID);
   double sl, tp;

   double sweepExtreme = (bias == BIAS_BULL) ? r[sweepIdx].low : r[sweepIdx].high;
   double slBuf = g_pip * InpSlBufferPips;
   double atr   = AtrValue();

   if(bias == BIAS_BULL)
   {
      sl = sweepExtreme - slBuf;
      // ATR fallback: never risk a stop tighter than ATR * mult from entry
      if(InpUseAtrStop && atr > 0.0) sl = MathMin(sl, entry - atr * InpAtrMultSL);
   }
   else
   {
      sl = sweepExtreme + slBuf;
      if(InpUseAtrStop && atr > 0.0) sl = MathMax(sl, entry + atr * InpAtrMultSL);
   }

   double risk = MathAbs(entry - sl);
   if(risk <= 0.0) return;

   // Target: liquidity, Asian-range SD projection, or their confluence
   tp = ChooseTarget(bias, entry, risk);
   if(tp <= 0.0) return;

   double reward = MathAbs(tp - entry);
   if(reward / risk < InpMinRR) return;
   if(InpMaxStopPips > 0.0 && risk / g_pip > InpMaxStopPips) return;

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
      g_beDone    = false;
      g_plannedTP = tp;
      g_plannedSL = sl;
      g_initRisk  = risk;
      g_posDir    = bias;
      PrintFormat("ENTRY %s lots=%.2f entry=%.5f sl=%.5f tp=%.5f RR=%.2f",
                  (bias == BIAS_BULL ? "BUY" : "SELL"), lots, entry, sl, tp, reward / risk);
   }
   else
      PrintFormat("Order failed: %d %s", trade.ResultRetcode(), trade.ResultRetcodeDescription());
}

//==================================================================//
//  FILTERS: ATR, displacement, OTE, news, cooldown, daily guard    //
//==================================================================//
double AtrValue()
{
   if(hATR == INVALID_HANDLE) return 0.0;
   double a[1];
   if(CopyBuffer(hATR, 0, 0, 1, a) < 1) return 0.0;
   return a[0];
}

// Strong-body candle at series index idx (a displacement / intent candle)
bool IsDisplacement(const MqlRates &r[], int idx)
{
   double range = r[idx].high - r[idx].low;
   if(range <= 0.0) return false;
   double body = MathAbs(r[idx].close - r[idx].open);
   if(body / range * 100.0 < InpMinBodyPct) return false;
   double atr = AtrValue();
   if(atr > 0.0 && body < atr * InpDisplaceAtrMult) return false;
   return true;
}

// Premium/discount filter using the recent dealing range on the setup TF.
bool PassesOTE(const MqlRates &r[], int bias)
{
   int look = MathMin(ArraySize(r) - 1, InpSetupLookback);
   double hh = -DBL_MAX, ll = DBL_MAX;
   for(int i = 1; i <= look; i++)
   {
      hh = MathMax(hh, r[i].high);
      ll = MathMin(ll, r[i].low);
   }
   if(hh <= ll) return true;
   double eq = (hh + ll) / 2.0;               // equilibrium (50%)
   double price = r[1].close;
   if(bias == BIAS_BULL) return (price <= eq); // buy only in discount
   return (price >= eq);                       // sell only in premium
}

bool InCooldown()
{
   if(InpCooldownMin <= 0 || g_lastLossTime == 0) return false;
   return (TimeCurrent() - g_lastLossTime < (long)InpCooldownMin * 60);
}

bool DailyGuardBlocked()
{
   if(g_dayStartBalance <= 0.0) return false;
   double eq  = AccountInfoDouble(ACCOUNT_EQUITY);
   double pct = (eq - g_dayStartBalance) / g_dayStartBalance * 100.0;
   if(InpDailyMaxLossPct > 0.0 && pct <= -InpDailyMaxLossPct) return true;
   if(InpDailyTargetPct  > 0.0 && pct >=  InpDailyTargetPct)  return true;
   return false;
}

// Record the time of a losing close so the cooldown can kick in.
void CheckClosedResult()
{
   if(!HistorySelect(TimeCurrent() - 6 * 3600, TimeCurrent() + 60)) return;
   int deals = HistoryDealsTotal();
   for(int i = deals - 1; i >= 0; i--)
   {
      ulong ticket = HistoryDealGetTicket(i);
      if(ticket == 0) continue;
      if((ulong)HistoryDealGetInteger(ticket, DEAL_MAGIC) != InpMagic) continue;
      if(HistoryDealGetString(ticket, DEAL_SYMBOL) != _Symbol) continue;
      if(HistoryDealGetInteger(ticket, DEAL_ENTRY) != DEAL_ENTRY_OUT) continue;
      double profit = HistoryDealGetDouble(ticket, DEAL_PROFIT)
                    + HistoryDealGetDouble(ticket, DEAL_SWAP)
                    + HistoryDealGetDouble(ticket, DEAL_COMMISSION);
      if(profit < 0.0)
      {
         g_lastLossTime = TimeCurrent();
         if(g_activeAnchor > 0.0)
         {
            g_lastFailedAnchor = g_activeAnchor;
            g_lastFailedDir    = g_activeDir;
            g_lastFailedTime   = TimeCurrent();
         }
      }
      break; // most recent close-out deal only
   }
}

// Don't re-arm/re-enter the identical swing anchor that just failed - e.g.
// re-taking the same broken level 40 minutes later on a fresh cooldown timer.
bool AnchorRecentlyFailed(int dir, double anchor)
{
   if(g_lastFailedTime == 0 || InpAnchorCooldownMin <= 0) return false;
   if(dir != g_lastFailedDir) return false;
   if(TimeCurrent() - g_lastFailedTime >= (long)InpAnchorCooldownMin * 60) return false;
   return (MathAbs(anchor - g_lastFailedAnchor) <= InpAnchorCooldownPips * g_pip);
}

// High-impact news filter via the MT5 economic calendar.
// Gracefully allows trading when the calendar is unavailable (e.g. Strategy Tester).
bool IsNewsTime()
{
   if(!InpUseNewsFilter) return false;
   string base = SymbolInfoString(_Symbol, SYMBOL_CURRENCY_BASE);
   string prof = SymbolInfoString(_Symbol, SYMBOL_CURRENCY_PROFIT);
   if(NewsForCurrency(base)) return true;
   if(prof != base && NewsForCurrency(prof)) return true;
   return false;
}

bool NewsForCurrency(string currency)
{
   if(currency == "") return false;
   datetime now  = TimeCurrent();
   datetime from = now - (long)PeriodSeconds(PERIOD_D1);
   datetime to   = now + (long)PeriodSeconds(PERIOD_D1);

   MqlCalendarValue values[];
   int count = CalendarValueHistory(values, from, to, NULL, currency);
   if(count <= 0) return false;

   ENUM_CALENDAR_EVENT_IMPORTANCE threshold =
      (InpNewsImportance >= 2) ? CALENDAR_IMPORTANCE_HIGH : CALENDAR_IMPORTANCE_MODERATE;

   for(int i = 0; i < count; i++)
   {
      if(values[i].time == 0) continue;
      MqlCalendarEvent ev;
      if(!CalendarEventById(values[i].event_id, ev)) continue;
      if(ev.importance < threshold) continue;
      datetime et = values[i].time;
      if(et >= now - (long)InpNewsMinsAfter * 60 && et <= now + (long)InpNewsMinsBefore * 60)
         return true;
   }
   return false;
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
//  STANDARD-DEVIATION PROJECTIONS (Asian range)                    //
//==================================================================//
void ParseSDMultiples()
{
   ArrayResize(g_sdMult, 0);
   string parts[];
   int c = StringSplit(InpSDMultiples, ',', parts);
   for(int i = 0; i < c; i++)
   {
      string s = parts[i];
      StringTrimLeft(s); StringTrimRight(s);
      double v = StringToDouble(s);
      if(v > 0.0)
      {
         int sz = ArraySize(g_sdMult);
         ArrayResize(g_sdMult, sz + 1);
         g_sdMult[sz] = v;
      }
   }
}

// Capture the most recent completed Asian session range (the projection origin).
void BuildSDProjections()
{
   double ah, al;
   if(!InpUseSDProjection || !PreviousSessionRange(InpAsiaStart, InpAsiaEnd, ah, al))
   {
      g_asiaRange = 0.0;
      return;
   }
   g_asiaHigh  = ah;
   g_asiaLow   = al;
   g_asiaRange = ah - al;
}

// SD projection price for a given multiple and direction (dir>0 up, dir<0 down).
// 1.0 = one Asian range beyond the range boundary, as on the RXWLES-style tool.
double SDLevel(int dir, double m)
{
   if(g_asiaRange <= 0.0) return 0.0;
   return (dir > 0) ? (g_asiaHigh + m * g_asiaRange)
                    : (g_asiaLow  - m * g_asiaRange);
}

// Is there a liquidity pool within tolPrice of the given price on the trade side?
bool LiquidityNear(int dir, double price, double tolPrice)
{
   if(dir > 0)
   {
      for(int i = 0; i < ArraySize(g_buySide); i++)
         if(g_buySide[i].valid && MathAbs(g_buySide[i].price - price) <= tolPrice) return true;
   }
   else
   {
      for(int i = 0; i < ArraySize(g_sellSide); i++)
         if(g_sellSide[i].valid && MathAbs(g_sellSide[i].price - price) <= tolPrice) return true;
   }
   return false;
}

// Master target chooser. minTP enforces the RR floor up-front.
double ChooseTarget(int dir, double entry, double risk)
{
   double liq   = OpposingLiquidity(dir, entry);
   if(InpTargetMode == TGT_LIQUIDITY || !InpUseSDProjection || g_asiaRange <= 0.0)
      return liq;

   double minTP = entry + dir * risk * InpMinRR;
   double tol   = InpSDAlignPips * g_pip;

   double nearest = 0.0, nearestDist = DBL_MAX;
   double aligned = 0.0, alignedDist = DBL_MAX;

   for(int i = 0; i < ArraySize(g_sdMult); i++)
   {
      double lvl = SDLevel(dir, g_sdMult[i]);
      if(lvl <= 0.0) continue;
      bool beyond = (dir > 0) ? (lvl >= minTP) : (lvl <= minTP);
      if(!beyond) continue;
      double d = MathAbs(lvl - entry);
      if(d < nearestDist) { nearestDist = d; nearest = lvl; }
      if(LiquidityNear(dir, lvl, tol) && d < alignedDist) { alignedDist = d; aligned = lvl; }
   }

   if(InpTargetMode == TGT_SD)
      return (nearest > 0.0 ? nearest : liq);

   // TGT_CONFLUENCE: prefer an SD level that lines up with a key liquidity level
   if(aligned > 0.0) return aligned;
   if(nearest > 0.0) return nearest;
   return liq;
}

void DrawSDLevels()
{
   ObjectsDeleteAll(0, g_obj_prefix + "SD_");
   if(g_asiaRange <= 0.0) return;

   datetime t1 = iTime(_Symbol, InpSetupTF, 0) - PeriodSeconds(InpSetupTF) * 40;
   datetime t2 = iTime(_Symbol, InpSetupTF, 0) + PeriodSeconds(InpSetupTF) * 8;

   // Asian range box
   string box = g_obj_prefix + "SD_BOX";
   ObjectCreate(0, box, OBJ_RECTANGLE, 0, t1, g_asiaHigh, t2, g_asiaLow);
   ObjectSetInteger(0, box, OBJPROP_COLOR, clrSlateGray);
   ObjectSetInteger(0, box, OBJPROP_BACK, true);
   ObjectSetInteger(0, box, OBJPROP_FILL, false);
   ObjectSetInteger(0, box, OBJPROP_STYLE, STYLE_DOT);
   ObjectSetString(0, box, OBJPROP_TOOLTIP, "Asian range (SD origin)");

   for(int dir = -1; dir <= 1; dir += 2)
      for(int i = 0; i < ArraySize(g_sdMult); i++)
      {
         double lvl = SDLevel(dir, g_sdMult[i]);
         if(lvl <= 0.0) continue;
         string nm = g_obj_prefix + "SD_" + (dir > 0 ? "U" : "D") + DoubleToString(g_sdMult[i], 1);
         ObjectCreate(0, nm, OBJ_TREND, 0, t1, lvl, t2, lvl);
         color c = LiquidityNear(dir, lvl, InpSDAlignPips * g_pip) ? clrGold : clrDimGray;
         ObjectSetInteger(0, nm, OBJPROP_COLOR, c);
         ObjectSetInteger(0, nm, OBJPROP_STYLE, STYLE_DASH);
         ObjectSetInteger(0, nm, OBJPROP_WIDTH, 1);
         ObjectSetInteger(0, nm, OBJPROP_RAY_RIGHT, false);
         ObjectSetInteger(0, nm, OBJPROP_BACK, true);
         ObjectSetString(0, nm, OBJPROP_TOOLTIP,
            StringFormat("%.1f SD %s%s", g_sdMult[i], (dir > 0 ? "up" : "down"),
                         LiquidityNear(dir, lvl, InpSDAlignPips * g_pip) ? "  (confluence)" : ""));
      }
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

   // --- Session-end close: don't carry the trade past the NY session ---
   if(InpCloseAtSessionEnd)
   {
      int h = CurrentNYHour();
      if(h >= InpNYEnd && h < InpNYEnd + 3)
      {
         if(trade.PositionClose(_Symbol))
            Print("Closed at NY session end");
         return;
      }
   }

   // --- First partial (-0.27 SD, ~1:2) -> bank profit and move to break-even ---
   double firstTgt = (g_firstTP > 0.0) ? g_firstTP
                    : ((InpTP1_RR > 0.0 && g_initRisk > 0.0) ? openp + dir * g_initRisk * InpTP1_RR : 0.0);
   if(!g_firstDone && firstTgt > 0.0 && g_initRisk > 0.0)
   {
      bool hitFirst = (dir > 0) ? (px >= firstTgt) : (px <= firstTgt);
      if(hitFirst)
      {
         double closeVol = NormalizeVolume(volume * InpFirstPartialPct / 100.0);
         if(closeVol > 0.0 && closeVol < volume)
         {
            if(trade.PositionClosePartial(_Symbol, closeVol))
               PrintFormat("First partial: closed %.2f lots (%.0f%%) at %.5f -> break-even",
                           closeVol, InpFirstPartialPct, firstTgt);
         }
         // Tighten to just behind the candle that broke through the 0.27 level -
         // usually much better than flat break-even, locking most trades in at
         // roughly 2:1+ if later stopped out, while still giving the runner room.
         double tightSL = 0.0;
         MqlRates m1[];
         ArraySetAsSeries(m1, true);
         if(CopyRates(_Symbol, InpMicroTF, 0, 2, m1) >= 2)
         {
            double lvl = (dir > 0) ? m1[0].low : m1[0].high;
            tightSL = (dir > 0) ? (lvl - g_pip * InpBreakEvenBufferPips)
                                : (lvl + g_pip * InpBreakEvenBufferPips);
            tightSL = EnforceMinStop(dir, px, tightSL);
         }
         double be = openp + dir * g_pip * InpBreakEvenBufferPips;
         // never worse than break-even, even if the breaking candle overshot
         double newSL = (tightSL > 0.0) ? ((dir > 0) ? MathMax(tightSL, be) : MathMin(tightSL, be)) : be;
         if((dir > 0 && newSL > curSL) || (dir < 0 && (curSL == 0 || newSL < curSL)))
            ModifySL(newSL);
         g_firstDone = true;
         g_beDone    = true;
      }
   }

   // --- Break-even: safety net once price has covered InpBreakEvenProgressPct% of
   // the distance to the REAL first-partial target - this scales with the actual
   // measured swing instead of a generic R-multiple that's decoupled from it (a
   // fixed R trigger either fires on every trade before the real move starts, or
   // -if raised too far- removes the early save entirely and lets every failed
   // setup run to full stop; tying it to the setup's own scale avoids both).
   if(InpUseBreakEven && !g_beDone && !g_tp1Done && g_initRisk > 0.0)
   {
      double moved = (dir > 0) ? (px - openp) : (openp - px);
      double beTrigger = (g_firstTP > 0.0)
                       ? MathAbs(g_firstTP - openp) * (InpBreakEvenProgressPct / 100.0)
                       : 1.5 * g_initRisk; // legacy (non-OTE) model fallback
      if(moved >= beTrigger)
      {
         double be = openp + dir * g_pip * InpBreakEvenBufferPips;
         if((dir > 0 && be > curSL) || (dir < 0 && (curSL == 0 || be < curSL)))
         {
            ModifySL(be);
            g_beDone = true;
         }
      }
   }

   // --- (Legacy model only) TP1: take partial, move stop behind nearest M1 FVG ---
   // OTE mode lets the remainder ride to the confluence final target (the order TP)
   // with M1-FVG trailing, so this intermediate 70% partial is skipped there.
   if(!InpUseOTEModel && !g_tp1Done && tpLevel > 0.0)
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

            // extend the runner: SD runner target (OTE model) or next liquidity pool
            double extTP = (g_runnerTP > 0.0) ? g_runnerTP : OpposingLiquidity(dir, tpLevel);
            if(extTP > 0.0 && ((dir > 0 && extTP > tpLevel) || (dir < 0 && extTP < tpLevel)))
            {
               g_plannedTP = extTP;
               ModifyTP(extTP);
            }
         }
      }
   }

   // --- Trail the runner behind M1 FVGs (OTE: after first partial; legacy: after TP1) ---
   bool trailOn = InpTrailMicroFvg &&
                  ((InpUseOTEModel && g_firstDone) || (!InpUseOTEModel && g_tp1Done));
   if(trailOn)
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
   double eq  = AccountInfoDouble(ACCOUNT_EQUITY);
   double pct = (g_dayStartBalance > 0 ? (eq - g_dayStartBalance) / g_dayStartBalance * 100.0 : 0.0);
   string block = "-";
   if(IsNewsTime())            block = "NEWS";
   else if(InCooldown())       block = "COOLDOWN";
   else if(DailyGuardBlocked())block = "DAILY GUARD";

   string txt =
      "INSTITUTIONAL BLXCK MIRROR\n" +
      "Symbol      : " + _Symbol + "\n" +
      "NY hour     : " + IntegerToString(CurrentNYHour()) + ":00\n" +
      "Bias (" + EnumToString(InpBiasTF) + "): " + sBias + "\n" +
      "EMA bias    : " + BiasStr(EmaBias()) + "\n" +
      "BOS " + EnumToString(InpBiasTF) + " : " + BiasStr(StructureBias(InpBiasTF)) + "\n" +
      "BOS " + EnumToString(InpHTFTrend) + " : " + BiasStr(StructureBias(InpHTFTrend)) + "\n" +
      "Killzone    : " + (InKillzone() ? "OPEN" : "closed") + "\n" +
      "Prime window: " + (InPrimeWindow() ? "OPEN" : "closed (armed setups wait)") + "\n" +
      "OTE setup   : " + (g_setup.active ? (g_setup.dir > 0 ? "ARMED long" : "ARMED short") +
                          " [" + (g_setup.pattern == PATTERN_BOS ? "BOS" : "CHoC") + "]" +
                          (g_setup.tapped ? " [tapped-await M1 conf]" : " [await retrace]") : "none") + "\n" +
      "OTE limit   : " + (g_pendingTicket != 0 ? "RESTING (await fill)" : "none") + "\n" +
      "Blocked by  : " + block + "\n" +
      "Spread(pips): " + DoubleToString(SpreadPips(), 1) + "\n" +
      "Day P/L     : " + DoubleToString(pct, 2) + "%\n" +
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

// Single-letter bias code for compact trade-comment tagging (U/D/N).
string BiasLetter(int b)
{
   if(b > 0) return "U";
   if(b < 0) return "D";
   return "N";
}

// Self-documenting order comment: pattern + direction + the three bias
// sub-votes (EMA / H4 BOS / D1 BOS) at the moment of entry, e.g. "BOSB-UUN".
// Lets a future backtest report be cross-analysed for "was bias actually
// wrong" without needing raw price bars or extra log exports.
string BuildTradeComment(int dir)
{
   string patTag = (g_setup.pattern == PATTERN_BOS) ? "BOS" : "CHC";
   string dirTag = (dir > 0) ? "B" : "S";
   string biasTag = BiasLetter(EmaBias()) + BiasLetter(StructureBias(InpBiasTF)) + BiasLetter(StructureBias(InpHTFTrend));
   return patTag + dirTag + "-" + biasTag;
}
//+------------------------------------------------------------------+
