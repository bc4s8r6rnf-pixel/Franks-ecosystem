//+------------------------------------------------------------------+
//|                              CandleRangeZoneSequence.mq5          |
//|            9pm anchor-candle deviation zones - sequence analyser  |
//|                                                                  |
//|  What this measures:                                             |
//|    The 21:00 (9pm) H1 candle sets a range R. Deviation zones are  |
//|    projected above and below it (default 2.0-2.5 R). Price then   |
//|    spends the following session bouncing between them. This       |
//|    script walks every session in history and records, per day:    |
//|      - which zone was tapped FIRST, and at what NY hour           |
//|      - whether the OTHER zone was tapped later the same session   |
//|      - which zone price was closest to at the NY reference hour   |
//|      - how far price ran, in deviation units                      |
//|                                                                  |
//|  It then answers the only question that matters: given what the   |
//|  PREVIOUS sessions did, which zone is favoured today? That is a   |
//|  conditional-probability table, not an opinion - the script       |
//|  prints the sample count next to every number so you can see      |
//|  which rows are real and which are noise.                         |
//|                                                                  |
//|  Finally it simulates five pre-specified entry models on the same |
//|  data so the "when and where to enter" question is answered with  |
//|  expectancy in R, not a hunch.                                    |
//|                                                                  |
//|  Output: Experts log + MQL5/Files/<symbol>_zone_sequence.txt      |
//|          and a per-session CSV you can pivot yourself.            |
//+------------------------------------------------------------------+
#property copyright "Institutional Blxck Mirror"
#property link      ""
#property version   "1.00"
#property strict
#property script_show_inputs
#property description "Measures the 9pm-candle deviation-zone sequence: which zone is hit first, whether both are hit, and what yesterday predicts about today."

//==================================================================//
//  INPUTS                                                          //
//==================================================================//
input group "=== Symbols & history ==="
input string InpSymbols          = "";   // Symbols to analyse (comma list). Blank = chart symbol
input int    InpLookbackDays     = 400;  // Calendar days of H1 history to scan

input group "=== The anchor candle (ALL hours are NEW YORK time, 24h) ==="
// Same convention as the EA: broker GMT+3, NY EDT = GMT-4  =>  NY = server - 7.
// Get this wrong and every session is shifted an hour - check the first few
// rows of the CSV against your chart before you trust any of the numbers.
// RXWLES PRO resolves in America/New_York with DST. Mode 0 reproduces that
// from the broker's clock; mode 1 is a flat offset if your broker is exotic.
input int    InpTimeMode         = 0;    // 0 = auto (US+EU daylight saving), 1 = fixed offset
input int    InpServerGMTWinter  = 2;    // Broker GMT offset in WINTER (EET brokers = 2)
input bool   InpServerEuroDST    = true; // Broker clock shifts with European daylight saving
input int    InpServerToNYOffset = -7;   // Fixed offset, mode 1 only: hours to ADD to server time

input int    InpAnchorHourNY     = 21;   // Enigma source hour (RXWLES default 21 = 9pm)
input int    InpNYRefHourNY      = 9;    // "NY open" reference hour for the proximity read
// RXWLES PRO draws each day's zones from 00:00 NY to 00:00 NY the next day -
// the lane opens two hours AFTER the 21:00 source candle closes, and the 22:00
// -> 00:00 gap is not part of it. Set the start hour to 22 to include that gap.
input int    InpSessionStartHourNY = 0;  // Zone lane opens at this NY hour, the day after the anchor
input int    InpSessionHours       = 24; // Lane length in hours (RXWLES = 24)

input group "=== Zone geometry - match this to your RXWLES boxes ==="
// Mode 2 is what RXWLES PRO draws, confirmed against the indicator source:
//   Daily Zone Upper  = srcHigh + r*2.0  ..  srcHigh + r*2.5
//   Daily Zone Lower  = srcLow  - r*2.0  ..  srcLow  - r*2.5
// where r is the 21:00 candle's own range. The other two modes are kept only
// so a differently-anchored indicator can be matched.
// 0 = MIDPOINT : up = mid  + N*R,  dn = mid  - N*R
// 1 = OPPOSITE : up = low  + N*R,  dn = high - N*R
// 2 = BOUNDARY : up = high + N*R,  dn = low  - N*R   <-- RXWLES PRO
input int    InpZoneMode         = 2;    // Zone anchor mode (2 = RXWLES PRO)
input double InpDevNear          = 2.0;  // Zone Level 1 - inner boundary, in deviations
input double InpDevFar           = 2.5;  // Zone Level 2 - outer boundary, in deviations
input bool   InpBookIncludeEnigma = true; // Also treat the Enigma range (the 21:00 candle high/low) as levels

input group "=== Carry-forward zones (older days' zones stay live) ==="
// A zone that was never reached on its own session does not expire at the
// close - it sits there as an untouched level. This is the "blasted through
// today's zone but respected the one from two days ago" behaviour.
input int    InpCarryDays         = 5;    // How many prior sessions' zones stay in play
input double InpReactR            = 1.00; // Retrace from the tap extreme that counts as a "respect", in range multiples

input group "=== Zone book (the multi-day ordering engine) ==="
input int    InpBookDays          = 10;   // How many prior sessions of untouched zones form the live book
input double InpClusterTolR       = 0.25; // Zones within this (range multiples) count as one stacked cluster
input int    InpBookRefPoint      = 0;    // Reference price: 0 = 9pm anchor close, 1 = NY reference bar open

input group "=== Entry models (all pre-specified, none fitted to the data) ==="
input double InpStopR            = 1.0;  // Models 1/3/4/5 stop, in range multiples
input double InpFadeStopR        = 0.25; // Model 2 stop beyond the far edge of the tapped zone
input double InpMinGapR          = 0.50; // Model 4 minimum proximity edge, in range multiples
input bool   InpSkipPreNY        = true; // Skip the session if a zone was tapped before the NY ref hour

input group "=== Output ==="
input bool   InpWriteCSV         = true; // Write the per-session CSV
input bool   InpWriteReport      = true; // Write the report as a .txt alongside the log

//==================================================================//
//  TYPES                                                           //
//==================================================================//
// Outcome of a session, i.e. what the two zones did between the anchor
// candle closing and the session end hour the next day.
#define OC_NONE       0
#define OC_UP_ONLY    1
#define OC_DN_ONLY    2
#define OC_UP_THEN_DN 3
#define OC_DN_THEN_UP 4
#define OC_COUNT      5

string OutcomeName(const int oc)
{
   switch(oc)
   {
      case OC_UP_ONLY:    return "UP only    ";
      case OC_DN_ONLY:    return "DOWN only  ";
      case OC_UP_THEN_DN: return "UP then DN ";
      case OC_DN_THEN_UP: return "DN then UP ";
   }
   return "neither    ";
}

struct SessionRec
{
   datetime anchorTime;      // open time of the 9pm H1 candle
   int      anchorIdx;       // its index in the rates array
   int      endIdx;          // last bar index of the session
   double   rHigh, rLow, rMid, range;
   double   u1, u2;          // upper zone: u1 = near edge, u2 = far edge
   double   l1, l2;          // lower zone: l2 = near edge, l1 = far edge
   bool     hasNY;
   int      nyIdx;
   double   nyPrice;         // open of the NY reference-hour bar
   double   distUp, distDn;  // deviations from nyPrice to each zone's near edge
   double   gap;             // |distUp - distDn| - how lopsided the proximity read is
   int      nearSide;        // +1 upper nearer, -1 lower nearer
   int      firstHit;        // +1 upper, -1 lower, 0 none
   int      firstHitIdx;
   int      firstHitHour;    // NY hour of the first tap
   int      secondHit;
   int      secondHitHour;
   bool     ambiguous;       // one bar tapped both zones - order inferred from the candle
   bool     upFilled, dnFilled;   // reached the FAR edge, not just the near edge
   bool     preNYHit;        // a zone was already tapped before the NY reference hour
   int      outcome;
   double   maxDevUp, maxDevDn;   // furthest excursion each way, in deviations
   int      laneStartIdx;            // first bar of the 00:00 NY lane
   int      upTouchIdx, dnTouchIdx;  // first bar EVER to reach each near edge (-1 = never), searched
                                     // across later sessions too - this is what makes a zone "virgin"
   int      enHiTouchIdx, enLoTouchIdx;   // same, for the Enigma range's own high and low
};

struct SimRes
{
   int    n, wins, losses, timeouts, ambig, skipped;
   double totalR;
};

struct Summary
{
   string sym;
   int    sessions;
   double pctBoth, pctUpOnly, pctDnOnly, pctNone;
   double nearestAcc;        // how often the zone nearest at NY open was tapped first
   double oppositeNext;      // after a single-sided day, how often the OTHER side goes first
   double m1R, m2R, m3R, m4R, m5R;
   int    m1n, m2n, m3n, m4n, m5n;
   double m1win, m2win, m3win, m4win, m5win;
};

//==================================================================//
//  GLOBALS                                                         //
//==================================================================//
int g_rep = INVALID_HANDLE;

void Out(const string s)
{
   Print(s);
   if(g_rep != INVALID_HANDLE) FileWrite(g_rep, s);
}

void Rule() { Out("------------------------------------------------------------------------------"); }

//------------------------------------------------------------------
// The indicator resolves everything in America/New_York with daylight
// saving included. A fixed hour offset does not - it drifts an hour twice a
// year, which silently picks the 20:00 or 22:00 candle instead of the 21:00
// one for months at a time. So the DST rules are implemented properly here.
//------------------------------------------------------------------
int DaysInMonth(const int y, const int m)
{
   int d[12] = {31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
   if(m == 2 && ((y % 4 == 0 && y % 100 != 0) || y % 400 == 0)) return 29;
   return d[m - 1];
}

// Midnight UTC of the nth given weekday of a month (dow: 0 = Sunday).
datetime NthDow(const int y, const int m, const int dow, const int nth)
{
   datetime first = StringToTime(StringFormat("%04d.%02d.01 00:00", y, m));
   MqlDateTime d; TimeToStruct(first, d);
   int delta = (dow - d.day_of_week + 7) % 7;
   return (datetime)((long)first + (long)(delta + (nth - 1) * 7) * 86400);
}

datetime LastDow(const int y, const int m, const int dow)
{
   datetime last = StringToTime(StringFormat("%04d.%02d.%02d 00:00", y, m, DaysInMonth(y, m)));
   MqlDateTime d; TimeToStruct(last, d);
   int back = (d.day_of_week - dow + 7) % 7;
   return (datetime)((long)last - (long)back * 86400);
}

// US: second Sunday of March 02:00 EST (07:00 UTC) -> first Sunday of
// November 02:00 EDT (06:00 UTC).
bool IsUSDST(const datetime utc)
{
   MqlDateTime d; TimeToStruct(utc, d);
   datetime s = (datetime)((long)NthDow(d.year, 3, 0, 2) + 7 * 3600);
   datetime e = (datetime)((long)NthDow(d.year, 11, 0, 1) + 6 * 3600);
   return (utc >= s && utc < e);
}

// EU: last Sunday of March 01:00 UTC -> last Sunday of October 01:00 UTC.
bool IsEUDST(const datetime utc)
{
   MqlDateTime d; TimeToStruct(utc, d);
   datetime s = (datetime)((long)LastDow(d.year, 3,  0) + 3600);
   datetime e = (datetime)((long)LastDow(d.year, 10, 0) + 3600);
   return (utc >= s && utc < e);
}

datetime NYTime(const datetime serverTime)
{
   if(InpTimeMode == 1)   // manual override
      return (datetime)((long)serverTime + (long)InpServerToNYOffset * 3600);

   datetime utc = (datetime)((long)serverTime - (long)InpServerGMTWinter * 3600);
   if(InpServerEuroDST && IsEUDST(utc)) utc = (datetime)((long)utc - 3600);
   return (datetime)((long)utc + (IsUSDST(utc) ? -4 : -5) * 3600);
}

int NYHour(const datetime serverTime)
{
   MqlDateTime dt;
   TimeToStruct(NYTime(serverTime), dt);
   return dt.hour;
}

string NYStamp(const datetime serverTime)
{
   return TimeToString(NYTime(serverTime), TIME_DATE | TIME_MINUTES);
}

double Pct(const int part, const int whole)
{
   if(whole <= 0) return 0.0;
   return 100.0 * (double)part / (double)whole;
}

//==================================================================//
//  SESSION BUILDER                                                 //
//==================================================================//
// Walk the H1 history and turn every 9pm candle into one session record:
// the zones it projects, and everything price did with them afterwards.
int BuildSessions(const MqlRates &r[], const int n, SessionRec &out[])
{
   ArrayResize(out, 0);
   int count = 0;

   for(int i = 0; i < n - 2; i++)
   {
      if(NYHour(r[i].time) != InpAnchorHourNY) continue;

      SessionRec s;
      ZeroMemory(s);
      s.anchorTime = r[i].time;
      s.anchorIdx  = i;
      s.rHigh      = r[i].high;
      s.rLow       = r[i].low;
      s.range      = s.rHigh - s.rLow;
      s.rMid       = 0.5 * (s.rHigh + s.rLow);
      if(s.range <= 0.0) continue;   // dead candle, no range to project from

      // Project the zones off whichever anchor matches the user's indicator.
      double baseUp, baseDn;
      if(InpZoneMode == 0)      { baseUp = s.rMid;  baseDn = s.rMid;  }
      else if(InpZoneMode == 2) { baseUp = s.rHigh; baseDn = s.rLow;  }
      else                      { baseUp = s.rLow;  baseDn = s.rHigh; }   // classic

      s.u1 = baseUp + InpDevNear * s.range;
      s.u2 = baseUp + InpDevFar  * s.range;
      s.l2 = baseDn - InpDevNear * s.range;
      s.l1 = baseDn - InpDevFar  * s.range;

      // The lane the indicator actually draws: 00:00 NY of the day AFTER the
      // anchor candle, running 24 hours to the following midnight.
      datetime nyAnchor = NYTime(r[i].time);
      MqlDateTime da; TimeToStruct(nyAnchor, da);
      datetime nyMidnight  = (datetime)((long)nyAnchor - (long)(da.hour * 3600 + da.min * 60 + da.sec) + 86400);
      datetime laneStartNY = (datetime)((long)nyMidnight  + (long)InpSessionStartHourNY * 3600);
      datetime laneEndNY   = (datetime)((long)laneStartNY + (long)InpSessionHours * 3600);

      s.endIdx      = i;
      s.laneStartIdx = -1;
      s.maxDevUp    = -99.0;
      s.maxDevDn    = -99.0;
      int barCount  = 0;

      // Scan the lane bar by bar, in time order.
      for(int j = i + 1; j < n; j++)
      {
         datetime nyj = NYTime(r[j].time);
         if(nyj <  laneStartNY) continue;   // the 22:00 -> 00:00 gap, not part of the lane
         if(nyj >= laneEndNY)   break;

         if(s.laneStartIdx < 0) s.laneStartIdx = j;
         s.endIdx = j;
         barCount++;
         MqlDateTime dj; TimeToStruct(nyj, dj);
         int hr = dj.hour;

         // The proximity read, taken once, at the NY reference hour.
         if(!s.hasNY && hr == InpNYRefHourNY)
         {
            s.hasNY    = true;
            s.nyIdx    = j;
            s.nyPrice  = r[j].open;
            s.distUp   = (s.u1 - s.nyPrice) / s.range;
            s.distDn   = (s.nyPrice - s.l2) / s.range;
            s.gap      = MathAbs(s.distUp - s.distDn);
            s.nearSide = (s.distUp < s.distDn) ? 1 : -1;
            s.preNYHit = (s.firstHit != 0);
         }

         // Excursion in deviation units, using the same anchor as the zones.
         double devUp = InpDevNear + (r[j].high - s.u1) / s.range;
         double devDn = InpDevNear + (s.l2 - r[j].low) / s.range;
         if(devUp > s.maxDevUp) s.maxDevUp = devUp;
         if(devDn > s.maxDevDn) s.maxDevDn = devDn;

         bool tUp = (r[j].high >= s.u1);
         bool tDn = (r[j].low  <= s.l2);
         if(r[j].high >= s.u2) s.upFilled = true;
         if(r[j].low  <= s.l1) s.dnFilled = true;

         if(s.firstHit == 0)
         {
            if(tUp && tDn)
            {
               // One H1 bar reached both zones. H1 gives no ordering, so infer
               // it from the candle's direction and flag the row - an up candle
               // most likely dipped first, then ran.
               s.ambiguous     = true;
               int firstGuess  = (r[j].close >= r[j].open) ? -1 : 1;
               s.firstHit      = firstGuess;
               s.secondHit     = -firstGuess;
               s.firstHitIdx   = j;
               s.firstHitHour  = hr;
               s.secondHitHour = hr;
            }
            else if(tUp || tDn)
            {
               s.firstHit     = tUp ? 1 : -1;
               s.firstHitIdx  = j;
               s.firstHitHour = hr;
            }
         }
         else if(s.secondHit == 0)
         {
            if((s.firstHit > 0 && tDn) || (s.firstHit < 0 && tUp))
            {
               s.secondHit     = -s.firstHit;
               s.secondHitHour = hr;
            }
         }
      }

      // A holiday, a half-session, or the session still in progress at the right
      // edge of the chart would otherwise be recorded as "neither zone reached"
      // and quietly poison every base rate below.
      if(barCount < 8) continue;
      if(NYTime(r[s.endIdx].time) < laneEndNY - 7200) continue;   // history ends mid-lane

      if(s.firstHit == 0)                        s.outcome = OC_NONE;
      else if(s.secondHit == 0)                  s.outcome = (s.firstHit > 0) ? OC_UP_ONLY : OC_DN_ONLY;
      else                                       s.outcome = (s.firstHit > 0) ? OC_UP_THEN_DN : OC_DN_THEN_UP;

      ArrayResize(out, count + 1);
      out[count] = s;
      count++;
   }
   return count;
}

//==================================================================//
//  ENTRY MODELS                                                    //
//==================================================================//
// Walk a trade forward bar by bar from entryIdx to the session end.
// Returns the realised R. Unresolved trades are closed at the session
// end, which is how the EA already handles the NY close.
double WalkTrade(const MqlRates &r[], const SessionRec &s, const int entryIdx,
                 const int dir, const double entry, const double tp, const double sl,
                 int &result)   // +1 win, -1 loss, 0 timeout
{
   double risk = MathAbs(entry - sl);
   if(risk <= 0.0) { result = 0; return 0.0; }

   for(int j = entryIdx; j <= s.endIdx; j++)
   {
      bool hitTP = (dir > 0) ? (r[j].high >= tp) : (r[j].low  <= tp);
      bool hitSL = (dir > 0) ? (r[j].low  <= sl) : (r[j].high >= sl);

      // Same-bar TP and SL: assume the stop, never the target. Optimism here
      // is how backtests lie.
      if(hitSL) { result = -1; return -1.0; }
      if(hitTP) { result =  1; return MathAbs(tp - entry) / risk; }
   }

   result = 0;
   double last = r[s.endIdx].close;
   return dir * (last - entry) / risk;
}

void AddTrade(SimRes &sr, const double rMult, const int result)
{
   sr.n++;
   sr.totalR += rMult;
   if(result > 0)      sr.wins++;
   else if(result < 0) sr.losses++;
   else                sr.timeouts++;
}

// Models 1, 3, 4 and 5 all enter at the NY reference bar and differ only in
// which side they pick and which sessions they are allowed to take.
// mode: 1 = nearest zone, 3 = nearest AND opposite of yesterday's single side,
//       4 = nearest AND a decisive proximity gap, 5 = opposite of yesterday,
//           ignoring proximity entirely (the control for model 3).
SimRes RunNYModel(const MqlRates &r[], const SessionRec &s[], const int ns, const int mode)
{
   SimRes sr;
   ZeroMemory(sr);

   for(int i = 0; i < ns; i++)
   {
      if(!s[i].hasNY)                        { sr.skipped++; continue; }
      if(InpSkipPreNY && s[i].preNYHit)      { sr.skipped++; continue; }

      int dir = s[i].nearSide;

      if(mode == 3 || mode == 5)
      {
         if(i == 0)                          { sr.skipped++; continue; }
         int prev = s[i-1].outcome;
         if(prev != OC_UP_ONLY && prev != OC_DN_ONLY) { sr.skipped++; continue; }
         int prevSide = (prev == OC_UP_ONLY) ? 1 : -1;
         if(mode == 5) dir = -prevSide;                              // control: ignore proximity
         else if(dir != -prevSide)           { sr.skipped++; continue; }   // must agree
      }
      if(mode == 4 && s[i].gap < InpMinGapR) { sr.skipped++; continue; }

      double entry = s[i].nyPrice;
      double tp    = (dir > 0) ? s[i].u1 : s[i].l2;
      double sl    = entry - dir * InpStopR * s[i].range;

      // Price is already past the zone edge - there is no trade to take.
      if((dir > 0 && tp <= entry) || (dir < 0 && tp >= entry)) { sr.skipped++; continue; }

      int res = 0;
      double rMult = WalkTrade(r, s[i], s[i].nyIdx, dir, entry, tp, sl, res);
      AddTrade(sr, rMult, res);
   }
   return sr;
}

// Model 2: the mean-reversion trade. A zone gets tapped; fade it back toward
// the opposite zone. Entry is assumed filled at the near edge of the tapped
// zone, stop sits beyond its far edge.
SimRes RunFadeModel(const MqlRates &r[], const SessionRec &s[], const int ns)
{
   SimRes sr;
   ZeroMemory(sr);

   for(int i = 0; i < ns; i++)
   {
      if(s[i].firstHit == 0) { sr.skipped++; continue; }
      if(s[i].ambiguous)     { sr.ambig++;   continue; }   // no reliable fill order on H1

      int dir      = -s[i].firstHit;
      double entry = (s[i].firstHit > 0) ? s[i].u1 : s[i].l2;
      double tp    = (s[i].firstHit > 0) ? s[i].l2 : s[i].u1;
      double sl    = (s[i].firstHit > 0) ? s[i].u2 + InpFadeStopR * s[i].range
                                         : s[i].l1 - InpFadeStopR * s[i].range;

      int res = 0;
      double rMult = WalkTrade(r, s[i], s[i].firstHitIdx, dir, entry, tp, sl, res);
      AddTrade(sr, rMult, res);
   }
   return sr;
}

void ReportModel(const string name, const SimRes &sr)
{
   if(sr.n == 0) { Out(StringFormat("  %-46s no qualifying sessions (%d skipped)", name, sr.skipped)); return; }
   Out(StringFormat("  %-46s n=%-4d  win %5.1f%%  avgR %+6.2f  totR %+8.1f  (timeouts %d, skipped %d)",
                    name, sr.n, Pct(sr.wins, sr.n), sr.totalR / sr.n, sr.totalR, sr.timeouts, sr.skipped));
}

//==================================================================//
//  STATISTICS                                                      //
//==================================================================//
void PrintSequenceTables(const SessionRec &s[], const int ns)
{
   // --- base rates -------------------------------------------------
   int oc[OC_COUNT];
   ArrayInitialize(oc, 0);
   int ambig = 0;
   for(int i = 0; i < ns; i++) { oc[s[i].outcome]++; if(s[i].ambiguous) ambig++; }

   Rule();
   Out("BASE RATES - what a session does at all");
   Rule();
   for(int k = 0; k < OC_COUNT; k++)
      Out(StringFormat("  %s  %4d   %5.1f%%", OutcomeName(k), oc[k], Pct(oc[k], ns)));
   int both = oc[OC_UP_THEN_DN] + oc[OC_DN_THEN_UP];
   int one  = oc[OC_UP_ONLY] + oc[OC_DN_ONLY];
   Out("");
   Out(StringFormat("  BOTH zones tapped        %4d   %5.1f%%", both, Pct(both, ns)));
   Out(StringFormat("  ONE zone only            %4d   %5.1f%%", one,  Pct(one,  ns)));
   Out(StringFormat("  NEITHER zone reached     %4d   %5.1f%%", oc[OC_NONE], Pct(oc[OC_NONE], ns)));
   Out(StringFormat("  (%d sessions tapped both zones inside one H1 bar - order inferred)", ambig));

   // --- the transition matrix: the actual "sequence" ---------------
   int mk[OC_COUNT][OC_COUNT];
   for(int a = 0; a < OC_COUNT; a++)
      for(int b = 0; b < OC_COUNT; b++) mk[a][b] = 0;
   for(int i = 1; i < ns; i++) mk[s[i-1].outcome][s[i].outcome]++;

   Out("");
   Rule();
   Out("SEQUENCE - yesterday's outcome (row) vs today's outcome (column)");
   Out("Read across a row. A row with n < 20 is noise, not a pattern.");
   Rule();
   Out("  yesterday ->    neither    UP only   DN only   UP>DN     DN>UP       n");
   for(int a = 0; a < OC_COUNT; a++)
   {
      int rowN = 0;
      for(int b = 0; b < OC_COUNT; b++) rowN += mk[a][b];
      string line = StringFormat("  %s ", OutcomeName(a));
      for(int b = 0; b < OC_COUNT; b++) line += StringFormat("  %5.1f%%  ", Pct(mk[a][b], rowN));
      line += StringFormat("  %4d", rowN);
      Out(line);
   }

   // --- which side goes first, given yesterday ---------------------
   Out("");
   Rule();
   Out("FIRST TAP - which zone goes first today, given yesterday");
   Out("This is the row you trade off. The last column is the edge over a coin flip.");
   Rule();
   Out("  yesterday ->      UP first   DN first   neither      n     skew");
   for(int a = 0; a < OC_COUNT; a++)
   {
      int up = 0, dn = 0, none = 0;
      for(int i = 1; i < ns; i++)
      {
         if(s[i-1].outcome != a) continue;
         if(s[i].firstHit > 0)      up++;
         else if(s[i].firstHit < 0) dn++;
         else                       none++;
      }
      int rowN    = up + dn + none;
      int decided = up + dn;
      double skew = (decided > 0) ? MathAbs(Pct(up, decided) - 50.0) : 0.0;
      Out(StringFormat("  %s   %5.1f%%    %5.1f%%    %5.1f%%    %4d   %+5.1f pts",
                       OutcomeName(a), Pct(up, rowN), Pct(dn, rowN), Pct(none, rowN), rowN, skew));
   }

   // --- the user's core hypothesis, tested -------------------------
   Out("");
   Rule();
   Out("HYPOTHESIS 1 - after a one-sided day, does the OTHER side go first next day?");
   Rule();
   {
      int nTot = 0, nOpp = 0;
      for(int i = 1; i < ns; i++)
      {
         int prev = s[i-1].outcome;
         if(prev != OC_UP_ONLY && prev != OC_DN_ONLY) continue;
         if(s[i].firstHit == 0) continue;
         int prevSide = (prev == OC_UP_ONLY) ? 1 : -1;
         nTot++;
         if(s[i].firstHit == -prevSide) nOpp++;
      }
      Out(StringFormat("  Other side tapped first:  %d / %d  =  %.1f%%   (coin flip = 50.0%%)",
                       nOpp, nTot, Pct(nOpp, nTot)));
      Out("  Above ~57% with n > 60 is a real edge. 45-55% means the rotation idea is a story.");
   }

   // --- proximity at NY open ---------------------------------------
   Out("");
   Rule();
   Out("HYPOTHESIS 2 - does price go to the zone it is NEAREST at the NY reference hour?");
   Rule();
   {
      int nTot = 0, nHit = 0;
      for(int i = 0; i < ns; i++)
      {
         if(!s[i].hasNY || s[i].firstHit == 0) continue;
         if(InpSkipPreNY && s[i].preNYHit) continue;
         nTot++;
         if(s[i].firstHit == s[i].nearSide) nHit++;
      }
      Out(StringFormat("  Nearest zone tapped first: %d / %d  =  %.1f%%", nHit, nTot, Pct(nHit, nTot)));
   }

   // Split by how lopsided the proximity read is. If the effect is real, the
   // accuracy should climb as the gap widens. A flat column kills the idea.
   Out("");
   Out("  Split by proximity gap (how much closer one zone is, in range multiples):");
   Out("    gap band        nearest first      n");
   {
      double lo[4] = {0.00, 0.25, 0.75, 1.50};
      double hi[4] = {0.25, 0.75, 1.50, 99.0};
      for(int b = 0; b < 4; b++)
      {
         int nTot = 0, nHit = 0;
         for(int i = 0; i < ns; i++)
         {
            if(!s[i].hasNY || s[i].firstHit == 0) continue;
            if(InpSkipPreNY && s[i].preNYHit) continue;
            if(s[i].gap < lo[b] || s[i].gap >= hi[b]) continue;
            nTot++;
            if(s[i].firstHit == s[i].nearSide) nHit++;
         }
         Out(StringFormat("    %.2f - %.2f R        %5.1f%%        %4d", lo[b], hi[b], Pct(nHit, nTot), nTot));
      }
   }

   // --- streaks ----------------------------------------------------
   Out("");
   Rule();
   Out("HYPOTHESIS 3 - do same-side runs exhaust? (streak of N one-sided days -> next day)");
   Rule();
   Out("  streak    same side again   other side      n");
   {
      for(int len = 1; len <= 4; len++)
      {
         int nTot = 0, nSame = 0;
         for(int i = 0; i < ns; i++)
         {
            // Need exactly `len` consecutive one-sided days of the same side ending at i-1.
            if(i - len < 0) continue;
            int side = 0;
            bool ok  = true;
            for(int k = 1; k <= len; k++)
            {
               int oc2 = s[i-k].outcome;
               if(oc2 != OC_UP_ONLY && oc2 != OC_DN_ONLY) { ok = false; break; }
               int sd = (oc2 == OC_UP_ONLY) ? 1 : -1;
               if(side == 0) side = sd;
               else if(sd != side) { ok = false; break; }
            }
            if(!ok || s[i].firstHit == 0) continue;
            nTot++;
            if(s[i].firstHit == side) nSame++;
         }
         Out(StringFormat("  %d day     %6.1f%%           %6.1f%%       %4d",
                          len, Pct(nSame, nTot), Pct(nTot - nSame, nTot), nTot));
      }
   }

   // --- timing -----------------------------------------------------
   Out("");
   Rule();
   Out("TIMING - NY hour of the FIRST tap (this is when to be at the screen)");
   Rule();
   {
      int hist[24];
      ArrayInitialize(hist, 0);
      int tot = 0;
      for(int i = 0; i < ns; i++)
         if(s[i].firstHit != 0) { hist[s[i].firstHitHour]++; tot++; }

      // Print in session order, starting at the anchor hour.
      for(int k = 0; k < 24; k++)
      {
         int h = (InpAnchorHourNY + 1 + k) % 24;
         if(hist[h] == 0) continue;
         int bars = (int)MathRound(Pct(hist[h], tot) / 2.0);
         string bar = "";
         for(int z = 0; z < bars; z++) bar += "#";
         Out(StringFormat("  %02d:00 NY  %5.1f%%  %4d  %s", h, Pct(hist[h], tot), hist[h], bar));
      }
   }

   // --- how far price runs -----------------------------------------
   Out("");
   Rule();
   Out("EXCURSION - how far price actually travels, in deviations");
   Rule();
   {
      double sumUp = 0, sumDn = 0;
      int fillUp = 0, fillDn = 0, tapUp = 0, tapDn = 0;
      for(int i = 0; i < ns; i++)
      {
         sumUp += s[i].maxDevUp; sumDn += s[i].maxDevDn;
         if(s[i].maxDevUp >= InpDevNear) tapUp++;
         if(s[i].maxDevDn >= InpDevNear) tapDn++;
         if(s[i].upFilled) fillUp++;
         if(s[i].dnFilled) fillDn++;
      }
      Out(StringFormat("  Mean max excursion   up %.2f dev   down %.2f dev", sumUp / ns, sumDn / ns));
      Out(StringFormat("  Reached %.1f dev      up %5.1f%%      down %5.1f%%", InpDevNear, Pct(tapUp, ns), Pct(tapDn, ns)));
      Out(StringFormat("  Reached %.1f dev      up %5.1f%%      down %5.1f%%", InpDevFar,  Pct(fillUp, ns), Pct(fillDn, ns)));
      Out("  If the far edge is reached far less often than the near edge, take profit at the NEAR edge.");
   }
}


//==================================================================//
//  CARRY-FORWARD ZONES                                             //
//==================================================================//
// A zone is "virgin" while price has never reached its near edge. Virgin
// zones from previous sessions do not stop mattering when the session ends -
// they sit in the book as untouched levels, and price frequently ignores
// today's fresh zone in favour of an older untouched one. This block
// measures exactly that.

#define ZR_UNTOUCHED 0
#define ZR_RESPECTED 1
#define ZR_BLOWN     2
#define ZR_STALLED   3

// What happened when price met this zone during session `s`?
//   dir +1 = upper zone (approached from below), -1 = lower zone.
//   nearEdge is met first, farEdge is the far side of the band.
int EvalZoneInSession(const MqlRates &r[], const SessionRec &s,
                      const double nearEdge, const double farEdge,
                      const int dir, const double zoneRange)
{
   int t = -1;
   for(int j = s.anchorIdx + 1; j <= s.endIdx; j++)
   {
      bool touched = (dir > 0) ? (r[j].high >= nearEdge) : (r[j].low <= nearEdge);
      if(touched) { t = j; break; }
   }
   if(t < 0) return ZR_UNTOUCHED;

   double extreme = (dir > 0) ? r[t].high : r[t].low;
   bool   blown   = (dir > 0) ? (r[t].high >= farEdge) : (r[t].low <= farEdge);

   for(int j = t; j <= s.endIdx; j++)
   {
      if(dir > 0)
      {
         if(r[j].high > extreme) extreme = r[j].high;
         if(r[j].high >= farEdge) blown = true;
         // Retraced far enough back off the level to call it a rejection.
         if(!blown && (extreme - r[j].low) >= InpReactR * zoneRange) return ZR_RESPECTED;
      }
      else
      {
         if(r[j].low < extreme) extreme = r[j].low;
         if(r[j].low <= farEdge) blown = true;
         if(!blown && (r[j].high - extreme) >= InpReactR * zoneRange) return ZR_RESPECTED;
      }
   }
   return blown ? ZR_BLOWN : ZR_STALLED;
}

// Fill in, for every session, the first bar that ever reached each near edge -
// looking forward across the following InpCarryDays sessions, not just its own.
void MapZoneTouches(const MqlRates &r[], const int n, SessionRec &s[], const int ns)
{
   for(int i = 0; i < ns; i++)
   {
      s[i].upTouchIdx   = -1;
      s[i].dnTouchIdx   = -1;
      s[i].enHiTouchIdx = -1;
      s[i].enLoTouchIdx = -1;
      int horizon = (InpBookDays > InpCarryDays) ? InpBookDays : InpCarryDays;
      int last = (i + horizon < ns - 1) ? i + horizon : ns - 1;
      int stop = s[last].endIdx;
      int scanFrom = (s[i].laneStartIdx > 0) ? s[i].laneStartIdx : s[i].anchorIdx + 1;
      for(int j = scanFrom; j <= stop && j < n; j++)
      {
         if(s[i].upTouchIdx   < 0 && r[j].high >= s[i].u1)    s[i].upTouchIdx   = j;
         if(s[i].dnTouchIdx   < 0 && r[j].low  <= s[i].l2)    s[i].dnTouchIdx   = j;
         if(s[i].enHiTouchIdx < 0 && r[j].high >= s[i].rHigh) s[i].enHiTouchIdx = j;
         if(s[i].enLoTouchIdx < 0 && r[j].low  <= s[i].rLow)  s[i].enLoTouchIdx = j;
         if(s[i].upTouchIdx >= 0 && s[i].dnTouchIdx >= 0 &&
            s[i].enHiTouchIdx >= 0 && s[i].enLoTouchIdx >= 0) break;
      }
   }
}

// Is the zone created by session `j` still untouched when session `i` begins?
// kind 0 = the 2.0-2.5 daily zone, kind 1 = the Enigma range's own boundary.
bool IsVirgin(const SessionRec &s[], const int j, const int i, const int dir, const int kind)
{
   int t;
   if(kind == 1) t = (dir > 0) ? s[j].enHiTouchIdx : s[j].enLoTouchIdx;
   else          t = (dir > 0) ? s[j].upTouchIdx   : s[j].dnTouchIdx;
   return (t < 0 || t > s[i].anchorIdx);
}

void PrintCarryTables(const MqlRates &r[], const SessionRec &s[], const int ns)
{
   Out("");
   Rule();
   Out("CARRY-FORWARD - is an OLD untouched zone respected more than today's fresh one?");
   Out("Age 0 = the zone from tonight's anchor candle. Age 2 = the zone from two nights ago,");
   Out("still untouched when today opened. 'respected' = tapped the near edge and rejected");
   Out(StringFormat("without reaching the far edge (>= %.2f R retrace).", InpReactR));
   Rule();
   Out("  age   met   respected   blown through   stalled     respect rate");

   for(int age = 0; age <= InpCarryDays; age++)
   {
      int met = 0, resp = 0, blown = 0, stall = 0;
      for(int i = 0; i < ns; i++)
      {
         int j = i - age;
         if(j < 0) continue;
         for(int d = -1; d <= 1; d += 2)
         {
            // Age 0 is today's own zone, which is virgin by definition at the open.
            if(age > 0 && !IsVirgin(s, j, i, d, 0)) continue;
            double nearE = (d > 0) ? s[j].u1 : s[j].l2;
            double farE  = (d > 0) ? s[j].u2 : s[j].l1;
            int res = EvalZoneInSession(r, s[i], nearE, farE, d, s[j].range);
            if(res == ZR_UNTOUCHED) continue;
            met++;
            if(res == ZR_RESPECTED)  resp++;
            else if(res == ZR_BLOWN) blown++;
            else                     stall++;
         }
      }
      Out(StringFormat("  %3d  %5d   %5d       %5d        %5d       %5.1f%%",
                       age, met, resp, blown, stall, Pct(resp, met)));
   }
   Out("");
   Out("  If the respect rate CLIMBS with age, older untouched zones are the better levels");
   Out("  and today's fresh zone is the weaker one - trade the old zone, not the new one.");

   // --- the specific gold case: today's zone blown, what catches price? ---
   Out("");
   Rule();
   Out("WHEN TODAY'S ZONE IS BLOWN THROUGH - what catches price next?");
   Rule();
   {
      int blownSessions = 0, reachedOld = 0, oldRespected = 0;
      int ageHist[64];
      ArrayInitialize(ageHist, 0);

      for(int i = 0; i < ns; i++)
      {
         for(int d = -1; d <= 1; d += 2)
         {
            double nearE = (d > 0) ? s[i].u1 : s[i].l2;
            double farE  = (d > 0) ? s[i].u2 : s[i].l1;
            if(EvalZoneInSession(r, s[i], nearE, farE, d, s[i].range) != ZR_BLOWN) continue;
            blownSessions++;

            // Find the nearest virgin older zone further out in the same direction.
            int    bestAge = -1;
            double bestLvl = 0.0, bestFar = 0.0, bestRng = 0.0;
            for(int age = 1; age <= InpCarryDays; age++)
            {
               int j = i - age;
               if(j < 0) break;
               if(!IsVirgin(s, j, i, d, 0)) continue;
               double lvl = (d > 0) ? s[j].u1 : s[j].l2;
               if(d > 0 && lvl <= farE) continue;   // must sit beyond the zone just broken
               if(d < 0 && lvl >= farE) continue;
               if(bestAge < 0 || (d > 0 && lvl < bestLvl) || (d < 0 && lvl > bestLvl))
               {
                  bestAge = age; bestLvl = lvl;
                  bestFar = (d > 0) ? s[j].u2 : s[j].l1;
                  bestRng = s[j].range;
               }
            }
            if(bestAge < 0) continue;

            int res = EvalZoneInSession(r, s[i], bestLvl, bestFar, d, bestRng);
            if(res == ZR_UNTOUCHED) continue;
            reachedOld++;
            ageHist[bestAge]++;
            if(res == ZR_RESPECTED) oldRespected++;
         }
      }
      Out(StringFormat("  Sessions that blew through a fresh zone:            %d", blownSessions));
      Out(StringFormat("  ...that then reached the next virgin OLDER zone:    %d  (%.1f%%)",
                       reachedOld, Pct(reachedOld, blownSessions)));
      Out(StringFormat("  ...and were REJECTED there:                         %d  (%.1f%% of those reached)",
                       oldRespected, Pct(oldRespected, reachedOld)));
      Out("");
      Out("  Age of the zone that caught it:");
      for(int a = 1; a <= InpCarryDays; a++)
         if(ageHist[a] > 0)
            Out(StringFormat("    %d day(s) old   %4d   %5.1f%%", a, ageHist[a], Pct(ageHist[a], reachedOld)));
      Out("");
      Out("  This is the 'blasted through today's zone, respected the one from two days ago'");
      Out("  case. If the rejection rate here beats the fresh-zone respect rate above, the");
      Out("  correct target on a breakout day is the OLD virgin zone, not today's.");
   }
}

// Model 6: today's zone is blown through - ride the break to the nearest
// virgin older zone instead of fading the fresh one.
SimRes RunCarryBreakModel(const MqlRates &r[], const SessionRec &s[], const int ns)
{
   SimRes sr;
   ZeroMemory(sr);

   for(int i = 0; i < ns; i++)
   {
      for(int d = -1; d <= 1; d += 2)
      {
         double nearE = (d > 0) ? s[i].u1 : s[i].l2;
         double farE  = (d > 0) ? s[i].u2 : s[i].l1;

         // Find the bar that breaks the far edge - that is the entry trigger.
         int trig = -1;
         for(int j = s[i].anchorIdx + 1; j <= s[i].endIdx; j++)
         {
            bool broke = (d > 0) ? (r[j].high >= farE) : (r[j].low <= farE);
            if(broke) { trig = j; break; }
         }
         if(trig < 0) { sr.skipped++; continue; }

         int    bestAge = -1;
         double bestLvl = 0.0;
         for(int age = 1; age <= InpCarryDays; age++)
         {
            int j2 = i - age;
            if(j2 < 0) break;
            if(!IsVirgin(s, j2, i, d, 0)) continue;
            double lvl = (d > 0) ? s[j2].u1 : s[j2].l2;
            if(d > 0 && lvl <= farE) continue;
            if(d < 0 && lvl >= farE) continue;
            if(bestAge < 0 || (d > 0 && lvl < bestLvl) || (d < 0 && lvl > bestLvl))
            { bestAge = age; bestLvl = lvl; }
         }
         if(bestAge < 0) { sr.skipped++; continue; }

         double entry = farE;                                  // fill on the break of the far edge
         double tp    = bestLvl;                               // near edge of the old virgin zone
         double sl    = entry - d * InpStopR * s[i].range;     // back inside today's zone

         int res = 0;
         double rMult = WalkTrade(r, s[i], trig, d, entry, tp, sl, res);
         AddTrade(sr, rMult, res);
      }
   }
   return sr;
}

//==================================================================//
//  ZONE BOOK - deciphering the ORDER in which zones are consumed    //
//==================================================================//
// Everything above treats today's zone as the object of interest. That is
// almost certainly the wrong frame. What actually exists at any moment is a
// BOOK of live levels: every zone from the last N sessions that price has
// never reached. Price works through that book. "Blasted through today's
// upper zone and respected the one from two days ago" is not an anomaly -
// it is the book being consumed in an order that today's zone does not
// determine.
//
// So the question becomes: given the live book at the start of a session,
// what rule picks the zone that gets consumed FIRST? This block builds the
// book, watches the real consumption order, and then puts eleven candidate
// ordering rules in a tournament against each other and against chance.
// Finally it grid-searches a weighted formula over the same features, fit
// on the first half of history and scored on the second, so the number you
// end up trusting is one the search never saw.

#define MAXBOOK   64
#define NRULES    11

#define RL_NEAR_PRICE  0
#define RL_NEAR_OWN    1
#define RL_OLDEST      2
#define RL_NEWEST      3
#define RL_BIG_ANCHOR  4
#define RL_SMALL_ANCH  5
#define RL_CLUSTER     6
#define RL_CLUST_NEAR  7
#define RL_ANCHOR_BIAS 8
#define RL_ROTATE      9
#define RL_CONTINUE    10

string RuleName(const int k)
{
   switch(k)
   {
      case RL_NEAR_PRICE:  return "nearest in price";
      case RL_NEAR_OWN:    return "nearest, scaled by the zone's own range";
      case RL_OLDEST:      return "oldest untouched first (FIFO queue)";
      case RL_NEWEST:      return "newest first (LIFO)";
      case RL_BIG_ANCHOR:  return "widest anchor candle wins";
      case RL_SMALL_ANCH:  return "tightest anchor candle wins";
      case RL_CLUSTER:     return "biggest cluster of stacked zones";
      case RL_CLUST_NEAR:  return "cluster first, nearest as tiebreak";
      case RL_ANCHOR_BIAS: return "side the 9pm candle closed toward";
      case RL_ROTATE:      return "opposite side to the last zone consumed";
      case RL_CONTINUE:    return "same side as the last zone consumed";
   }
   return "?";
}

// One live zone in the book, flattened so the grid search can sweep it fast.
struct BookZone
{
   int    sess;        // session it belongs to
   int    kind;        // 0 = the 2.0-2.5 daily zone, 1 = the Enigma range boundary
   int    age;         // sessions old (0 = tonight's anchor)
   int    side;        // +1 upper, -1 lower
   double nearE, farE, range;
   double distToday;   // |nearE - reference| in units of TODAY's range
   double distOwn;     // ...in units of the zone's OWN anchor range
   int    cluster;     // live zones stacked within tolerance of this one
   int    order;       // consumption order this session: 0 = never, 1 = first, ...
   int    bar;         // bar index of consumption
};

double RuleScore(const int rule, const BookZone &z, const int anchorDir, const int lastSide)
{
   switch(rule)
   {
      case RL_NEAR_PRICE:  return -z.distToday;
      case RL_NEAR_OWN:    return -z.distOwn;
      case RL_OLDEST:      return  z.age * 10.0 - z.distToday;
      case RL_NEWEST:      return -z.age * 10.0 - z.distToday;
      case RL_BIG_ANCHOR:  return  z.range;
      case RL_SMALL_ANCH:  return -z.range;
      case RL_CLUSTER:     return  z.cluster;
      case RL_CLUST_NEAR:  return  z.cluster * 10.0 - z.distToday;
      case RL_ANCHOR_BIAS: return ((z.side == anchorDir) ? 10.0 : 0.0) - z.distToday;
      case RL_ROTATE:      return ((lastSide != 0 && z.side == -lastSide) ? 10.0 : 0.0) - z.distToday;
      case RL_CONTINUE:    return ((lastSide != 0 && z.side ==  lastSide) ? 10.0 : 0.0) - z.distToday;
   }
   return 0.0;
}

// The four features the weighted formula search sweeps. All normalised to
// roughly 0..1 so the weights are comparable to each other.
void ZoneFeatures(const BookZone &z, const int anchorDir, double &f[])
{
   double d = z.distToday; if(d > 6.0) d = 6.0;
   f[0] = 1.0 - d / 6.0;                                   // proximity
   f[1] = (double)z.age / (double)InpBookDays;             // staleness
   double c = (double)(z.cluster - 1); if(c > 3.0) c = 3.0;
   f[2] = c / 3.0;                                         // confluence
   f[3] = (z.side == anchorDir) ? 1.0 : 0.0;               // anchor-candle bias
}

//------------------------------------------------------------------
// Build the live book for session i and watch the order it is consumed in.
//------------------------------------------------------------------
int BuildBook(const MqlRates &r[], const SessionRec &s[], const int ns, const int i,
              BookZone &book[])
{
   int nb = 0;
   ArrayResize(book, 0);

   double refPrice = (InpBookRefPoint == 1 && s[i].hasNY) ? s[i].nyPrice : r[s[i].anchorIdx].close;
   int    startBar = (InpBookRefPoint == 1 && s[i].hasNY) ? s[i].nyIdx   : s[i].anchorIdx + 1;

   for(int age = 0; age <= InpBookDays; age++)
   {
      int j = i - age;
      if(j < 0) break;
      for(int kind = 0; kind <= 1; kind++)
      {
      if(kind == 1 && !InpBookIncludeEnigma) continue;
      // Tonight's own Enigma range is where price already is - it sits inches
      // away and would win every proximity contest for trivial reasons. Only
      // older, still-untouched Enigma ranges are real standing levels.
      if(kind == 1 && age == 0) continue;

      for(int d = -1; d <= 1; d += 2)
      {
         // Age 0 is tonight's own zone and is live by definition. Older zones
         // only count while price has still never reached them.
         if(age > 0 && !IsVirgin(s, j, i, d, kind)) continue;

         BookZone z;
         ZeroMemory(z);
         z.sess  = j;
         z.kind  = kind;
         z.age   = age;
         z.side  = d;
         if(kind == 1)
         {
            z.nearE = (d > 0) ? s[j].rHigh : s[j].rLow;
            z.farE  = (d > 0) ? s[j].rHigh + 0.25 * s[j].range : s[j].rLow - 0.25 * s[j].range;
         }
         else
         {
            z.nearE = (d > 0) ? s[j].u1 : s[j].l2;
            z.farE  = (d > 0) ? s[j].u2 : s[j].l1;
         }
         z.range = s[j].range;

         // A zone already on the wrong side of price is not a level price is
         // travelling toward - it is behind it. Drop it from the book.
         if(d > 0 && z.nearE <= refPrice) continue;
         if(d < 0 && z.nearE >= refPrice) continue;

         z.distToday = MathAbs(z.nearE - refPrice) / s[i].range;
         z.distOwn   = MathAbs(z.nearE - refPrice) / z.range;

         if(nb >= MAXBOOK) continue;
         ArrayResize(book, nb + 1);
         book[nb] = z;
         nb++;
      }
      }
   }
   if(nb == 0) return 0;

   // Confluence: how many live zones stack within tolerance of each one.
   // Price does not care which day a level came from, so this counts by price
   // only, not by side.
   double tol = InpClusterTolR * s[i].range;
   for(int a = 0; a < nb; a++)
   {
      book[a].cluster = 0;
      for(int b = 0; b < nb; b++)
         if(MathAbs(book[a].nearE - book[b].nearE) <= tol) book[a].cluster++;
   }

   // Watch the session and stamp the real consumption order.
   int ord = 0;
   for(int j2 = startBar; j2 <= s[i].endIdx; j2++)
   {
      // Several zones can be taken out by one bar. Order them by how far they
      // sit from that bar's open - the nearest is reached first on the way.
      for(;;)
      {
         int    pick = -1;
         double best = 0.0;
         for(int a = 0; a < nb; a++)
         {
            if(book[a].order != 0) continue;
            bool hit = (book[a].side > 0) ? (r[j2].high >= book[a].nearE)
                                          : (r[j2].low  <= book[a].nearE);
            if(!hit) continue;
            double dd = MathAbs(book[a].nearE - r[j2].open);
            if(pick < 0 || dd < best) { pick = a; best = dd; }
         }
         if(pick < 0) break;
         ord++;
         book[pick].order = ord;
         book[pick].bar   = j2;
      }
   }
   return nb;
}

//------------------------------------------------------------------
void AnalyseZoneBook(const MqlRates &r[], const int n, const SessionRec &s[], const int ns)
{
   // Flat storage so the weight search can sweep every candidate cheaply.
   int    fSess[];  int    fAge[];   int    fSide[];  int fClust[]; int fOrder[]; int fKind[];
   double fDistT[]; double fDistO[]; double fRange[];
   int    sStart[]; int    sCount[]; int    sFirst[]; int sAnchorDir[];
   ArrayResize(sStart, ns); ArrayResize(sCount, ns);
   ArrayResize(sFirst, ns); ArrayResize(sAnchorDir, ns);

   // Reserve up front - growing eight arrays one element at a time is the
   // difference between this finishing instantly and it crawling.
   int cap = ns * (InpBookDays + 1) * 2;
   ArrayResize(fSess, 0, cap);  ArrayResize(fAge,   0, cap); ArrayResize(fSide,  0, cap);
   ArrayResize(fClust, 0, cap); ArrayResize(fOrder, 0, cap); ArrayResize(fDistT, 0, cap);
   ArrayResize(fDistO, 0, cap); ArrayResize(fRange, 0, cap); ArrayResize(fKind, 0, cap);

   int total = 0, lastSide = 0;
   int lastSideArr[];
   ArrayResize(lastSideArr, ns);

   int sizeHist[MAXBOOK];
   ArrayInitialize(sizeHist, 0);
   int consumedHist[MAXBOOK];
   ArrayInitialize(consumedHist, 0);

   for(int i = 0; i < ns; i++)
   {
      sStart[i] = total; sCount[i] = 0; sFirst[i] = -1;
      sAnchorDir[i]  = (r[s[i].anchorIdx].close >= r[s[i].anchorIdx].open) ? 1 : -1;
      lastSideArr[i] = lastSide;

      BookZone book[];
      int nb = BuildBook(r, s, ns, i, book);
      if(nb <= 0) continue;

      if(nb < MAXBOOK) sizeHist[nb]++;
      int consumed = 0, lastOrd = 0, lastS = 0;

      for(int a = 0; a < nb; a++)
      {
         ArrayResize(fSess,  total + 1); ArrayResize(fAge,   total + 1);
         ArrayResize(fSide,  total + 1); ArrayResize(fClust, total + 1);
         ArrayResize(fOrder, total + 1); ArrayResize(fDistT, total + 1);
         ArrayResize(fDistO, total + 1); ArrayResize(fRange, total + 1);
         ArrayResize(fKind,  total + 1); fKind[total] = book[a].kind;
         fSess[total]  = book[a].sess;  fAge[total]   = book[a].age;
         fSide[total]  = book[a].side;  fClust[total] = book[a].cluster;
         fOrder[total] = book[a].order; fDistT[total] = book[a].distToday;
         fDistO[total] = book[a].distOwn; fRange[total] = book[a].range;
         if(book[a].order == 1) sFirst[i] = total;
         if(book[a].order > 0)
         {
            consumed++;
            if(book[a].order > lastOrd) { lastOrd = book[a].order; lastS = book[a].side; }
         }
         total++; sCount[i]++;
      }
      if(consumed < MAXBOOK) consumedHist[consumed]++;
      if(lastS != 0) lastSide = lastS;
   }

   Out("");
   Out("==============================================================================");
   Out("  ZONE BOOK - the order the live levels are consumed in");
   Out("==============================================================================");
   Out(StringFormat("  Book depth %d sessions, cluster tolerance %.2f R, reference = %s",
                    InpBookDays, InpClusterTolR,
                    (InpBookRefPoint == 1) ? "NY reference bar open" : "9pm anchor candle close"));

   // --- how big is the book, and how much of it gets eaten ---------
   Out("");
   Rule();
   Out("BOOK SIZE - live untouched zones at the start of a session, and how many go");
   Rule();
   Out("  live zones   sessions        consumed   sessions");
   for(int k = 0; k < 20; k++)
   {
      if(sizeHist[k] == 0 && consumedHist[k] == 0) continue;
      Out(StringFormat("  %6d      %5d  (%5.1f%%)    %6d     %5d  (%5.1f%%)",
                       k, sizeHist[k], Pct(sizeHist[k], ns), k, consumedHist[k], Pct(consumedHist[k], ns)));
   }

   // --- THE key descriptive table ----------------------------------
   // If the first zone consumed is almost always the nearest one, the ordering
   // rule is just proximity and there is nothing else to find. If it is spread
   // across ranks, something other than distance is driving the choice.
   Out("");
   Rule();
   Out("WHERE THE FIRST-CONSUMED ZONE SAT IN THE NEAREST-FIRST ORDERING");
   Out("Rank 1 = it was the closest live zone. Spread across ranks = distance is not the rule.");
   Rule();
   {
      int rankHist[MAXBOOK];
      ArrayInitialize(rankHist, 0);
      int tot = 0;
      for(int i = 0; i < ns; i++)
      {
         if(sFirst[i] < 0 || sCount[i] < 2) continue;
         int rank = 1;
         for(int a = sStart[i]; a < sStart[i] + sCount[i]; a++)
            if(fDistT[a] < fDistT[sFirst[i]]) rank++;
         if(rank < MAXBOOK) { rankHist[rank]++; tot++; }
      }
      for(int k = 1; k < 12; k++)
         if(rankHist[k] > 0)
         {
            int bars = (int)MathRound(Pct(rankHist[k], tot) / 2.0);
            string bar = "";
            for(int z = 0; z < bars; z++) bar += "#";
            Out(StringFormat("  rank %2d   %5.1f%%  %4d  %s", k, Pct(rankHist[k], tot), rankHist[k], bar));
         }
      Out(StringFormat("  (%d sessions with a real choice to make)", tot));
   }

   // --- age and cluster profile of what gets taken first -----------
   Out("");
   Rule();
   Out("AGE AND CONFLUENCE OF THE FIRST ZONE CONSUMED");
   Rule();
   {
      int ageH[32], clH[16];
      ArrayInitialize(ageH, 0); ArrayInitialize(clH, 0);
      int tot = 0;
      // Availability, so a rate can be computed rather than a raw count -
      // age 0 is present every session, age 7 is not.
      int ageAvail[32];
      ArrayInitialize(ageAvail, 0);
      for(int i = 0; i < ns; i++)
      {
         if(sCount[i] < 2) continue;
         for(int a = sStart[i]; a < sStart[i] + sCount[i]; a++)
            if(fAge[a] < 32) ageAvail[fAge[a]]++;
         if(sFirst[i] < 0) continue;
         if(fAge[sFirst[i]]   < 32) ageH[fAge[sFirst[i]]]++;
         if(fClust[sFirst[i]] < 16) clH[fClust[sFirst[i]]]++;
         tot++;
      }
      Out("  age   taken first   times live   taken-first rate");
      for(int k = 0; k <= InpBookDays && k < 32; k++)
         Out(StringFormat("  %3d   %5d        %6d       %5.1f%%",
                          k, ageH[k], ageAvail[k], Pct(ageH[k], ageAvail[k])));
      Out("");
      Out("  If the taken-first RATE is flat across ages, age is irrelevant and only");
      Out("  proximity matters. If it climbs with age, the book really is a queue.");
      Out("");
      Out("  cluster size of the zone taken first:");
      for(int k = 1; k < 16; k++)
         if(clH[k] > 0) Out(StringFormat("    %d stacked   %5d   %5.1f%%", k, clH[k], Pct(clH[k], tot)));
   }

   // --- which drawn object actually gets traded to --------------------
   Out("");
   Rule();
   Out("LEVEL TYPE - which of the indicator's objects is the one price goes to?");
   Rule();
   {
      int firstK[2], availK[2];
      ArrayInitialize(firstK, 0); ArrayInitialize(availK, 0);
      for(int i = 0; i < ns; i++)
      {
         if(sCount[i] < 2) continue;
         for(int a = sStart[i]; a < sStart[i] + sCount[i]; a++)
            if(fKind[a] >= 0 && fKind[a] < 2) availK[fKind[a]]++;
         if(sFirst[i] >= 0 && fKind[sFirst[i]] < 2) firstK[fKind[sFirst[i]]]++;
      }
      Out("  level type              taken first   times live   taken-first rate");
      Out(StringFormat("  Daily Zone (2.0-2.5)    %6d       %7d      %5.1f%%",
                       firstK[0], availK[0], Pct(firstK[0], availK[0])));
      Out(StringFormat("  Enigma range boundary   %6d       %7d      %5.1f%%",
                       firstK[1], availK[1], Pct(firstK[1], availK[1])));
      Out("");
      Out("  If old Enigma boundaries out-rate the Daily Zones, the 2.0-2.5 projections");
      Out("  are not the magnets - the untouched 9pm candle ranges themselves are.");
   }

   // --- the tournament ---------------------------------------------
   Out("");
   Rule();
   Out("RULE TOURNAMENT - which ordering rule predicts the first zone consumed?");
   Out("MRR is mean reciprocal rank: 1.00 = always ranked it first, 0.50 = typically second.");
   Out("Beat the CHANCE row by a wide margin or the rule is decoration.");
   Rule();
   Out("  rule                                              top-1     MRR      n");

   double chance = 0.0; int chanceN = 0;
   for(int i = 0; i < ns; i++)
   {
      if(sFirst[i] < 0 || sCount[i] < 2) continue;
      chance += 1.0 / (double)sCount[i];
      chanceN++;
   }

   for(int rule = 0; rule < NRULES; rule++)
   {
      int hits = 0, cnt = 0;
      double mrr = 0.0;
      for(int i = 0; i < ns; i++)
      {
         if(sFirst[i] < 0 || sCount[i] < 2) continue;
         BookZone za; ZeroMemory(za);
         int rank = 1, bestIdx = -1; double bestSc = 0.0;
         // score of the actual winner
         BookZone zw; ZeroMemory(zw);
         zw.age = fAge[sFirst[i]]; zw.side = fSide[sFirst[i]]; zw.cluster = fClust[sFirst[i]];
         zw.distToday = fDistT[sFirst[i]]; zw.distOwn = fDistO[sFirst[i]]; zw.range = fRange[sFirst[i]];
         double scW = RuleScore(rule, zw, sAnchorDir[i], lastSideArr[i]);
         for(int a = sStart[i]; a < sStart[i] + sCount[i]; a++)
         {
            za.age = fAge[a]; za.side = fSide[a]; za.cluster = fClust[a];
            za.distToday = fDistT[a]; za.distOwn = fDistO[a]; za.range = fRange[a];
            double sc = RuleScore(rule, za, sAnchorDir[i], lastSideArr[i]);
            if(sc > scW) rank++;
            if(bestIdx < 0 || sc > bestSc) { bestSc = sc; bestIdx = a; }
         }
         if(bestIdx == sFirst[i]) hits++;
         mrr += 1.0 / (double)rank;
         cnt++;
      }
      Out(StringFormat("  %-48s %5.1f%%   %5.3f   %4d",
                       RuleName(rule), Pct(hits, cnt), (cnt > 0) ? mrr / cnt : 0.0, cnt));
   }
   Out(StringFormat("  %-48s %5.1f%%       -    %4d", "CHANCE (random pick from the book)",
                    (chanceN > 0) ? 100.0 * chance / chanceN : 0.0, chanceN));

   // --- the formula search -----------------------------------------
   // Fit on the first half, score on the second. The train number will always
   // look good; only the test number means anything.
   Out("");
   Rule();
   Out("FORMULA SEARCH - score = w0*proximity + w1*staleness + w2*confluence + w3*anchor-bias");
   Out("Weights swept on the FIRST half of history, then scored on the SECOND half,");
   Out("which the search never saw. Trust the test column and nothing else.");
   Rule();

   int split = ns / 2;
   double grid[5] = {-1.0, -0.5, 0.0, 0.5, 1.0};
   double bw[4]; ArrayInitialize(bw, 0.0);
   double bestTrain = -1.0;

   for(int a0 = 0; a0 < 5; a0++)
   for(int a1 = 0; a1 < 5; a1++)
   for(int a2 = 0; a2 < 5; a2++)
   for(int a3 = 0; a3 < 5; a3++)
   {
      double w[4]; w[0] = grid[a0]; w[1] = grid[a1]; w[2] = grid[a2]; w[3] = grid[a3];
      if(w[0] == 0.0 && w[1] == 0.0 && w[2] == 0.0 && w[3] == 0.0) continue;

      int hits = 0, cnt = 0;
      for(int i = 0; i < split; i++)
      {
         if(sFirst[i] < 0 || sCount[i] < 2) continue;
         int bestIdx = -1; double bestSc = 0.0;
         for(int a = sStart[i]; a < sStart[i] + sCount[i]; a++)
         {
            BookZone z; ZeroMemory(z);
            z.age = fAge[a]; z.side = fSide[a]; z.cluster = fClust[a]; z.distToday = fDistT[a];
            double f[4]; ZoneFeatures(z, sAnchorDir[i], f);
            double sc = w[0]*f[0] + w[1]*f[1] + w[2]*f[2] + w[3]*f[3];
            if(bestIdx < 0 || sc > bestSc) { bestSc = sc; bestIdx = a; }
         }
         if(bestIdx == sFirst[i]) hits++;
         cnt++;
      }
      double acc = (cnt > 0) ? (double)hits / cnt : 0.0;
      if(acc > bestTrain) { bestTrain = acc; bw[0]=w[0]; bw[1]=w[1]; bw[2]=w[2]; bw[3]=w[3]; }
   }

   int hits2 = 0, cnt2 = 0;
   double chance2 = 0.0;
   for(int i = split; i < ns; i++)
   {
      if(sFirst[i] < 0 || sCount[i] < 2) continue;
      int bestIdx = -1; double bestSc = 0.0;
      for(int a = sStart[i]; a < sStart[i] + sCount[i]; a++)
      {
         BookZone z; ZeroMemory(z);
         z.age = fAge[a]; z.side = fSide[a]; z.cluster = fClust[a]; z.distToday = fDistT[a];
         double f[4]; ZoneFeatures(z, sAnchorDir[i], f);
         double sc = bw[0]*f[0] + bw[1]*f[1] + bw[2]*f[2] + bw[3]*f[3];
         if(bestIdx < 0 || sc > bestSc) { bestSc = sc; bestIdx = a; }
      }
      if(bestIdx == sFirst[i]) hits2++;
      chance2 += 1.0 / (double)sCount[i];
      cnt2++;
   }

   Out(StringFormat("  best weights:  proximity %+.1f   staleness %+.1f   confluence %+.1f   anchor-bias %+.1f",
                    bw[0], bw[1], bw[2], bw[3]));
   Out(StringFormat("  train (first half)  %5.1f%%   n=%d", 100.0 * bestTrain, split));
   Out(StringFormat("  TEST  (second half) %5.1f%%   n=%d", Pct(hits2, cnt2), cnt2));
   Out(StringFormat("  chance on test      %5.1f%%", (cnt2 > 0) ? 100.0 * chance2 / cnt2 : 0.0));
   Out("");
   Out("  Test barely above chance => there is no stable formula, and the order the");
   Out("  zones get taken in is mostly path-dependent noise. Test clearly above chance");
   Out("  AND close to train => the weights are the thing you were looking for.");

   // --- what follows what ------------------------------------------
   Out("");
   Rule();
   Out("SECOND ZONE, GIVEN THE FIRST - does the book get worked in a readable order?");
   Rule();
   {
      int sameSide = 0, oppSide = 0, olderNext = 0, newerNext = 0, tot = 0;
      for(int i = 0; i < ns; i++)
      {
         if(sFirst[i] < 0) continue;
         int second = -1;
         for(int a = sStart[i]; a < sStart[i] + sCount[i]; a++)
            if(fOrder[a] == 2) second = a;
         if(second < 0) continue;
         tot++;
         if(fSide[second] == fSide[sFirst[i]]) sameSide++; else oppSide++;
         if(fAge[second]  >  fAge[sFirst[i]])  olderNext++;
         if(fAge[second]  <  fAge[sFirst[i]])  newerNext++;
      }
      Out(StringFormat("  sessions with a 2nd consumption:  %d", tot));
      Out(StringFormat("    same side as the first:   %5.1f%%", Pct(sameSide, tot)));
      Out(StringFormat("    opposite side:            %5.1f%%", Pct(oppSide, tot)));
      Out(StringFormat("    an OLDER zone next:       %5.1f%%", Pct(olderNext, tot)));
      Out(StringFormat("    a NEWER zone next:        %5.1f%%", Pct(newerNext, tot)));
      Out("");
      Out("  Same-side dominance means price runs the book outward in one direction");
      Out("  before turning. Opposite-side dominance is the bounce you already see.");
   }
}

//==================================================================//
//  PER-SYMBOL DRIVER                                               //
//==================================================================//
bool AnalyseSymbol(const string sym, Summary &sum)
{
   if(!SymbolSelect(sym, true))
   {
      Out(StringFormat("!! %s: cannot select symbol - check the exact name in Market Watch", sym));
      return false;
   }

   MqlRates r[];
   ArraySetAsSeries(r, false);
   datetime from = (datetime)((long)TimeCurrent() - (long)InpLookbackDays * 86400);
   int n = CopyRates(sym, PERIOD_H1, from, TimeCurrent(), r);
   if(n < 200)
   {
      Out(StringFormat("!! %s: only %d H1 bars available. Open an H1 chart of this symbol and scroll back to load history, then re-run.", sym, n));
      return false;
   }

   SessionRec s[];
   int ns = BuildSessions(r, n, s);
   if(ns < 20)
   {
      Out(StringFormat("!! %s: only %d sessions built from %d bars. The %02d:00 NY anchor hour probably does not exist on this feed - check InpServerToNYOffset.",
                       sym, ns, n, InpAnchorHourNY));
      return false;
   }

   Out("");
   Out("==============================================================================");
   Out(StringFormat("  %s   %d sessions   %s  ->  %s   (all times NY)",
                    sym, ns, NYStamp(s[0].anchorTime), NYStamp(s[ns-1].anchorTime)));
   Out(StringFormat("  Zone mode %d, %.1f-%.1f deviations of the %02d:00 H1 candle range",
                    InpZoneMode, InpDevNear, InpDevFar, InpAnchorHourNY));
   Out("==============================================================================");

   MapZoneTouches(r, n, s, ns);
   PrintSequenceTables(s, ns);
   PrintCarryTables(r, s, ns);
   AnalyseZoneBook(r, n, s, ns);

   Out("");
   Rule();
   Out("ENTRY MODELS - same data, five pre-specified rule sets, expectancy in R");
   Out("Model 5 is the control for model 3: if 3 does not beat 5, the proximity read adds nothing.");
   Rule();
   SimRes m1 = RunNYModel(r, s, ns, 1);
   SimRes m2 = RunFadeModel(r, s, ns);
   SimRes m3 = RunNYModel(r, s, ns, 3);
   SimRes m4 = RunNYModel(r, s, ns, 4);
   SimRes m5 = RunNYModel(r, s, ns, 5);
   SimRes m6 = RunCarryBreakModel(r, s, ns);
   ReportModel("1  NY open -> nearest zone", m1);
   ReportModel("2  fade the first tap -> opposite zone", m2);
   ReportModel("3  nearest AND opposite of yesterday", m3);
   ReportModel("4  nearest AND gap >= min (conviction filter)", m4);
   ReportModel("5  opposite of yesterday, ignoring proximity", m5);
   ReportModel("6  break of today's zone -> old virgin zone", m6);
   Out("");
   Out("  Costs are NOT modelled. Subtract your spread + commission per trade before believing any of it.");

   // --- summary for the cross-symbol table --------------------------
   int ocC[OC_COUNT];
   ArrayInitialize(ocC, 0);
   for(int i = 0; i < ns; i++) ocC[s[i].outcome]++;

   int nTot = 0, nHit = 0, oTot = 0, oOpp = 0;
   for(int i = 0; i < ns; i++)
   {
      if(s[i].hasNY && s[i].firstHit != 0 && !(InpSkipPreNY && s[i].preNYHit))
      {
         nTot++;
         if(s[i].firstHit == s[i].nearSide) nHit++;
      }
      if(i == 0) continue;
      int prev = s[i-1].outcome;
      if((prev == OC_UP_ONLY || prev == OC_DN_ONLY) && s[i].firstHit != 0)
      {
         oTot++;
         if(s[i].firstHit == -((prev == OC_UP_ONLY) ? 1 : -1)) oOpp++;
      }
   }

   sum.sym          = sym;
   sum.sessions     = ns;
   sum.pctBoth      = Pct(ocC[OC_UP_THEN_DN] + ocC[OC_DN_THEN_UP], ns);
   sum.pctUpOnly    = Pct(ocC[OC_UP_ONLY], ns);
   sum.pctDnOnly    = Pct(ocC[OC_DN_ONLY], ns);
   sum.pctNone      = Pct(ocC[OC_NONE], ns);
   sum.nearestAcc   = Pct(nHit, nTot);
   sum.oppositeNext = Pct(oOpp, oTot);
   sum.m1n = m1.n; sum.m1R = (m1.n > 0) ? m1.totalR / m1.n : 0.0; sum.m1win = Pct(m1.wins, m1.n);
   sum.m2n = m2.n; sum.m2R = (m2.n > 0) ? m2.totalR / m2.n : 0.0; sum.m2win = Pct(m2.wins, m2.n);
   sum.m3n = m3.n; sum.m3R = (m3.n > 0) ? m3.totalR / m3.n : 0.0; sum.m3win = Pct(m3.wins, m3.n);
   sum.m4n = m4.n; sum.m4R = (m4.n > 0) ? m4.totalR / m4.n : 0.0; sum.m4win = Pct(m4.wins, m4.n);
   sum.m5n = m5.n; sum.m5R = (m5.n > 0) ? m5.totalR / m5.n : 0.0; sum.m5win = Pct(m5.wins, m5.n);

   // --- per-session CSV so you can pivot it yourself -----------------
   if(InpWriteCSV)
   {
      string fname = sym + "_zone_sequence.csv";
      int fh = FileOpen(fname, FILE_WRITE | FILE_CSV | FILE_ANSI, ',');
      if(fh == INVALID_HANDLE)
         Out(StringFormat("  (could not write %s, error %d)", fname, GetLastError()));
      else
      {
         FileWrite(fh, "anchor_ny", "range", "r_high", "r_low", "u1", "u2", "l2", "l1",
                       "ny_price", "dist_up_R", "dist_dn_R", "gap_R", "near_side",
                       "first_hit", "first_hit_hour_ny", "second_hit", "second_hit_hour_ny",
                       "up_filled", "dn_filled", "pre_ny_hit", "ambiguous",
                       "max_dev_up", "max_dev_dn", "outcome");
         for(int i = 0; i < ns; i++)
            FileWrite(fh, NYStamp(s[i].anchorTime), s[i].range, s[i].rHigh, s[i].rLow,
                          s[i].u1, s[i].u2, s[i].l2, s[i].l1,
                          s[i].hasNY ? s[i].nyPrice : 0.0, s[i].distUp, s[i].distDn, s[i].gap,
                          s[i].nearSide, s[i].firstHit, s[i].firstHitHour,
                          s[i].secondHit, s[i].secondHitHour,
                          s[i].upFilled ? 1 : 0, s[i].dnFilled ? 1 : 0,
                          s[i].preNYHit ? 1 : 0, s[i].ambiguous ? 1 : 0,
                          s[i].maxDevUp, s[i].maxDevDn, OutcomeName(s[i].outcome));
         FileClose(fh);
         Out("");
         Out(StringFormat("  Per-session CSV written: MQL5/Files/%s", fname));
      }
   }
   return true;
}

//==================================================================//
//  ENTRY POINT                                                     //
//==================================================================//
void OnStart()
{
   if(InpWriteReport)
   {
      g_rep = FileOpen("zone_sequence_report.txt", FILE_WRITE | FILE_TXT | FILE_ANSI);
      if(g_rep == INVALID_HANDLE) Print("Could not open the report file, logging to the Experts tab only.");
   }

   string list = InpSymbols;
   StringTrimLeft(list); StringTrimRight(list);
   if(StringLen(list) == 0) list = _Symbol;

   string parts[];
   int np = StringSplit(list, ',', parts);
   if(np <= 0) { np = 1; ArrayResize(parts, 1); parts[0] = _Symbol; }

   Summary sums[];
   int nsum = 0;

   for(int p = 0; p < np; p++)
   {
      string sym = parts[p];
      StringTrimLeft(sym); StringTrimRight(sym);
      if(StringLen(sym) == 0) continue;

      Summary sum;
      if(!AnalyseSymbol(sym, sum)) continue;
      ArrayResize(sums, nsum + 1);
      sums[nsum] = sum;
      nsum++;
   }

   if(nsum > 1)
   {
      Out("");
      Out("==============================================================================");
      Out("  CROSS-SYMBOL COMPARISON");
      Out("  A behaviour that holds on both instruments is structural. One that shows up");
      Out("  on only one of them is that instrument's character - or curve fitting.");
      Out("==============================================================================");
      Out("  symbol        n   both%   up%   dn%  none%   nearest%  rotate%   M1 avgR   M3 avgR");
      for(int i = 0; i < nsum; i++)
         Out(StringFormat("  %-10s %4d  %5.1f %5.1f %5.1f  %5.1f     %5.1f    %5.1f    %+6.2f    %+6.2f",
                          sums[i].sym, sums[i].sessions, sums[i].pctBoth, sums[i].pctUpOnly,
                          sums[i].pctDnOnly, sums[i].pctNone, sums[i].nearestAcc,
                          sums[i].oppositeNext, sums[i].m1R, sums[i].m3R));
   }

   Out("");
   Out("Done. Check the anchor times in the CSV against your chart before trading any of this.");

   if(g_rep != INVALID_HANDLE)
   {
      FileClose(g_rep);
      g_rep = INVALID_HANDLE;
      Print("Report written: MQL5/Files/zone_sequence_report.txt");
   }
}
//+------------------------------------------------------------------+
