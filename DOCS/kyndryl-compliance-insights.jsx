import React, { useState, useEffect } from "react";
import {
  LayoutDashboard, ShieldCheck, ClipboardCheck, History as HistoryIcon, Gauge,
  Play, ChevronDown, ChevronRight, Sparkles, Check, X, Pencil,
  Send, Loader2, Circle, Building2, PanelRightClose, ArrowRight, Zap, ArrowUpRight, ArrowDownRight
} from "lucide-react";
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";

/* ---------- palette (light app + Option B hero) ---------- */
const C = {
  coral: "#FF4C34", coralLt: "#FF7A66", coralDark: "#D93A22", coralSoft: "#FFEDE8",
  amber: "#FBBF3C", cyan: "#38BDF8",
  ink: "#0E1420", ink2: "#141B29", ink3: "#1A2233", inkLine: "rgba(255,255,255,0.08)",
  railBg: "#16181E", railText: "#E8EAEF", railMute: "#7E8695", railEl: "#2A2E39",
  paper: "#F6F7F9", card: "#FFFFFF", line: "#E8EAEE", lineStrong: "#D8DBE2",
  text: "#16181E", slate: "#545A64", mute: "#8A909B",
  green: "#16B15E", greenSoft: "#E7F7EE", greenBright: "#34D399",
  r1: "#E0A02E", r1s: "#F7F0DF", r2: "#E3742E", r2s: "#FBEADD", r3: "#D6462A", r3s: "#FADFD9",
};
const FONT = "Inter, system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif";
const MONO = "ui-monospace, SFMono-Regular, Menlo, monospace";
const RULE = { 1: { c: C.r1, s: C.r1s }, 2: { c: C.r2, s: C.r2s }, 3: { c: C.r3, s: C.r3s } };

/* ---------- data ---------- */
const TOTAL = 100000, FAILS = { 1: 3214, 2: 7179, 3: 6181 }, ANY_FAIL = 14890;
const COMPLIANT = TOTAL - ANY_FAIL, PRE = 85.1, POST = 96.2, REMOVED = 2740;
const TREND = [{ d: "07-26", s: 82.0 }, { d: "07-27", s: 83.1 }, { d: "07-28", s: 84.0 }, { d: "07-29", s: 84.6 }, { d: "07-31", s: 85.0 }, { d: "08-01", s: POST }];
const RUNS = [{ id: "074e319c", score: POST, pre: PRE, when: "Aug 1, 06:45 PM" }, { id: "a91c2f77", score: 85.0, pre: 84.2, when: "Jul 31, 04:10 PM" }, { id: "5d0b81e2", score: 84.6, pre: 83.9, when: "Jul 29, 11:22 AM" }];
const AUDIT = [
  { tag: "ingest", tone: C.slate, text: "Loaded 100,000 loans + parsed 100 company profiles" },
  { tag: "evaluate", tone: C.slate, text: "All loans checked against 3 Rego policies via OPA" },
  { tag: "rule_1", tone: C.r1, text: "3,214 below €25,000 after FX conversion" },
  { tag: "rule_2", tone: C.r2, text: "7,179 currency mismatches found" },
  { tag: "rule_3", tone: C.r3, text: "6,181 under-collateralised (asset < 50% of loan)" },
  { tag: "score", tone: C.coralDark, text: "Pre-review compliance: 85.1%" },
  { tag: "group", tone: C.slate, text: "14,890 failures clubbed into 9 review groups" },
  { tag: "suggest", tone: C.r3, text: "Wave 1: generated 5,065 Rule 3 suggestions" },
  { tag: "review", tone: C.green, text: "Reviewer resolved 12,150 across groups" },
  { tag: "verify", tone: C.green, text: "Re-scored via OPA: 85.1% → 96.2% (Δ +11.1%)" },
];
const GROUPS = [
  { id: "g1", rule: 2, title: "German companies reported in USD", fix: "Change currency to EUR", count: 1240, summary: "1,240 loans across 47 German-headquartered companies booked in USD — consistent with a single mis-mapped ledger import. Every loan shares the identical deterministic fix (relabel to EUR from the country table). Outliers: 3 loans also fall below €25,000 once converted, so they route to Rule 1 removal, not a currency fix; and 12 belong to companies with US subsidiaries, which likely explains the USD booking.", samples: [{ loan: "L004821", co: "Aldergate Industries", from: "USD", to: "EUR" }, { loan: "L011907", co: "Vireo Holdings", from: "USD", to: "EUR" }, { loan: "L028345", co: "Kestrel Pharma", from: "USD", to: "EUR" }] },
  { id: "g2", rule: 2, title: "UK companies reported in EUR", fix: "Change currency to GBP", count: 760, summary: "760 loans from UK-headquartered borrowers reported in EUR instead of GBP. Uniform fix (relabel to GBP). No Rule 1 interaction — all sit above the threshold in either currency. One company accounts for 210 of the 760, suggesting a per-borrower convention rather than a systemic import error.", samples: [{ loan: "L006612", co: "Thornbury Freight", from: "EUR", to: "GBP" }, { loan: "L019004", co: "Marlow Logistics", from: "EUR", to: "GBP" }] },
  { id: "g3", rule: 1, title: "Below €25,000 after conversion", fix: "Remove from report (out of scope)", count: 3214, summary: "3,214 loans fall below the €25,000 reporting floor once converted to EUR. Terminal — nothing to correct, so the action is removal. This count is measured before currency remediation; loans that only look small because of a wrong currency label may be rescued when their Rule 2 fix is re-checked, so the final removed count will be lower.", samples: [{ loan: "L003310", co: "Pinewood Agritech", val: "€24,180" }, { loan: "L022145", co: "Harbold Metals", val: "€23,905" }] },
  { id: "g4", rule: 3, title: "Insufficient collateral — asset < 50% of loan", fix: "Substitute a qualifying asset", count: 5065, summary: "5,065 loans where the pledged asset covers less than half the loan. For most, another asset in the same company's holdings clears the threshold and is suggested. The agent flags 214 loans where no held asset qualifies — honest dead-ends surfaced for the reviewer, not forced fixes. Single-high-value-asset companies dominate the dead-end set.", samples: [{ loan: "L007788", co: "Aldergate Industries", sub: "Graz Freight Hub (€834,171)" }, { loan: "L014562", co: "Kestrel Pharma", sub: "Basel Cold Store (€1,120,400)" }, { loan: "L031200", co: "Marlow Logistics", sub: "— no qualifying asset", dead: true }] },
];

/* near-threshold, non-EUR only, within 5% of €25,000 (€23,750–€26,250) */
const NEAR = {
  band: 5, floor: 25000, totalAbove: 22, totalBelow: 15,
  above: [ // passes now, fragile
    { loan: "L041220", co: "Kestrel Pharma", ccy: "USD", eur: 25180, d: 0.7 },
    { loan: "L052910", co: "Thornbury Freight", ccy: "GBP", eur: 25410, d: 1.6 },
    { loan: "L047733", co: "Marlow Logistics", ccy: "USD", eur: 25690, d: 2.8 },
    { loan: "L061002", co: "Aldergate Industries", ccy: "CHF", eur: 25920, d: 3.7 },
    { loan: "L058815", co: "Vireo Holdings", ccy: "JPY", eur: 26140, d: 4.6 },
  ],
  below: [ // fails now, near miss
    { loan: "L039401", co: "Harbold Metals", ccy: "USD", eur: 24880, d: -0.5 },
    { loan: "L044120", co: "Pinewood Agritech", ccy: "GBP", eur: 24610, d: -1.6 },
    { loan: "L050337", co: "Kestrel Pharma", ccy: "SEK", eur: 24180, d: -3.3 },
    { loan: "L055219", co: "Marlow Logistics", ccy: "USD", eur: 23910, d: -4.4 },
  ],
  summary: "37 non-EUR loans sit within 5% of the €25,000 reporting floor — all genuinely rate-sensitive, since EUR loans can't move against EUR. 22 currently pass but are fragile: a small strengthening of EUR against their booking currency would push them under the floor and out of scope, concentrated in USD-booked loans from Kestrel Pharma and Marlow Logistics. 15 currently fail but by a thin margin (as little as 0.5%), so a modest favorable move would clear them — they may not be genuinely out of scope. USD exposure dominates both groups. This is a fragility signal on today's rates, not a prediction of where rates will move; the 22 fragile passes are worth watching ahead of the next reporting cycle.",
};

/* ---------- motion ---------- */
function useCountUp(from, to, dur = 1400, run = true) {
  const [v, setV] = useState(from);
  useEffect(() => {
    if (!run) { setV(to); return; }
    let raf, start;
    const step = (t) => { if (!start) start = t; const p = Math.min((t - start) / dur, 1); const e = 1 - Math.pow(1 - p, 3); setV(from + (to - from) * e); if (p < 1) raf = requestAnimationFrame(step); };
    raf = requestAnimationFrame(step); return () => cancelAnimationFrame(raf);
  }, [from, to, dur, run]);
  return v;
}
function useMounted() { const [m, setM] = useState(false); useEffect(() => { const t = setTimeout(() => setM(true), 70); return () => clearTimeout(t); }, []); return m; }

/* ---------- primitives ---------- */
const Panel = ({ children, style, ...p }) => <div {...p} style={{ background: C.card, border: `1px solid ${C.line}`, borderRadius: 12, ...style }}>{children}</div>;
const Tag = ({ rule }) => { const r = RULE[rule]; return <span style={{ background: r.s, color: r.c, fontFamily: MONO, fontSize: 11, fontWeight: 700, padding: "2px 7px", borderRadius: 5 }}>R{rule}</span>; };
const Btn = ({ kind = "ghost", children, style, ...p }) => {
  const m = { solid: { background: C.coral, color: "#fff", border: `1px solid ${C.coral}` }, ghost: { background: "#fff", color: C.text, border: `1px solid ${C.lineStrong}` }, green: { background: C.greenSoft, color: C.green, border: `1px solid ${C.greenSoft}` }, red: { background: C.coralSoft, color: C.coralDark, border: `1px solid ${C.coralSoft}` }, violet: { background: C.r3s, color: C.r3, border: `1px solid ${C.r3s}` } }[kind];
  return <button {...p} style={{ ...m, fontFamily: FONT, fontSize: 13, fontWeight: 600, padding: "7px 12px", borderRadius: 8, cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 6, ...style }}>{children}</button>;
};
const Eyebrow = ({ children, dark }) => <div style={{ color: dark ? C.railMute : C.mute, fontSize: 11, fontWeight: 700, letterSpacing: 1.2, textTransform: "uppercase" }}>{children}</div>;

function Ring({ value, size = 74, stroke = 7, run }) {
  const r = (size - stroke) / 2, circ = 2 * Math.PI * r;
  const v = useCountUp(0, value, 1400, run);
  return (
    <svg width={size} height={size}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={C.railEl} strokeWidth={stroke} />
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={C.coral} strokeWidth={stroke} strokeLinecap="round" strokeDasharray={circ} strokeDashoffset={circ * (1 - v / 100)} transform={`rotate(-90 ${size / 2} ${size / 2})`} />
      <text x="50%" y="50%" textAnchor="middle" dominantBaseline="central" fill={C.railText} fontFamily={MONO} fontSize={15} fontWeight={700}>{v.toFixed(0)}%</text>
    </svg>
  );
}

/* ---------- Dashboard ---------- */
function Dashboard() {
  const mounted = useMounted();
  const score = useCountUp(PRE, POST, 1600);
  const loans = useCountUp(0, TOTAL, 1400);
  const seg = [{ label: "Compliant", n: COMPLIANT, c: C.greenBright }, { label: "Rule 1", n: FAILS[1], c: C.r1 }, { label: "Rule 2", n: FAILS[2], c: C.r2 }, { label: "Rule 3", n: FAILS[3], c: C.r3 }];
  const segTotal = seg.reduce((a, s) => a + s.n, 0);
  return (
    <div className="flex flex-col gap-5">
      <div style={{ position: "relative", overflow: "hidden", borderRadius: 16, background: `linear-gradient(135deg, ${C.ink} 0%, ${C.ink2} 70%, ${C.ink3} 100%)`, border: `1px solid #232D3E`, padding: 28 }}>
        <div style={{ position: "absolute", top: -90, right: -50, width: 300, height: 300, background: `radial-gradient(circle, ${C.cyan}33 0%, transparent 68%)` }} />
        <div style={{ position: "relative" }}>
          <div className="flex items-start justify-between flex-wrap" style={{ gap: 20 }}>
            <div>
              <Eyebrow dark>Compliance · after healing</Eyebrow>
              <div className="flex items-end gap-3" style={{ marginTop: 10 }}>
                <span style={{ fontFamily: MONO, fontSize: 66, fontWeight: 800, lineHeight: 0.9, color: C.amber, letterSpacing: -2 }}>{score.toFixed(1)}<span style={{ fontSize: 32 }}>%</span></span>
                <div style={{ marginBottom: 8 }}>
                  <div className="flex items-center gap-2" style={{ fontSize: 13, fontFamily: MONO }}><span style={{ color: C.railMute }}>{PRE}%</span><ArrowRight size={14} color={C.railMute} /><span style={{ color: C.greenBright, fontWeight: 700 }}>{POST}%</span></div>
                  <div style={{ display: "inline-flex", alignItems: "center", gap: 5, marginTop: 6, background: "rgba(52,211,153,0.14)", color: "#6EE7B7", fontSize: 12.5, fontWeight: 700, padding: "3px 9px", borderRadius: 6 }}><Zap size={13} /> +{(POST - PRE).toFixed(1)} pts healed</div>
                </div>
              </div>
              <div style={{ color: C.railMute, fontSize: 13.5, marginTop: 12 }}><b style={{ color: "#fff", fontFamily: MONO }}>{Math.round(loans).toLocaleString()}</b> loans checked · <b style={{ color: "#fff", fontFamily: MONO }}>{ANY_FAIL.toLocaleString()}</b> failures remediated by human review</div>
            </div>
            <div style={{ background: "rgba(255,255,255,0.04)", border: `1px solid #232D3E`, borderRadius: 12, padding: "12px 16px" }}>
              <div className="text-right"><div style={{ color: C.railMute, fontSize: 11 }}>Removed · Rule 1</div><div style={{ fontFamily: MONO, fontSize: 22, fontWeight: 700, color: C.r2 }}>{REMOVED.toLocaleString()}</div></div>
            </div>
          </div>
          <div style={{ marginTop: 22 }}>
            <div style={{ display: "flex", height: 40, borderRadius: 9, overflow: "hidden", background: "rgba(255,255,255,0.06)" }}>
              {seg.map((s, i) => <div key={s.label} title={`${s.label}: ${s.n.toLocaleString()}`} style={{ width: mounted ? `${(s.n / segTotal) * 100}%` : "0%", background: s.c, transition: `width 1.1s cubic-bezier(.22,1,.36,1) ${i * 0.1}s`, minWidth: mounted ? 3 : 0 }} />)}
            </div>
            <div className="flex flex-wrap gap-x-5 gap-y-2" style={{ marginTop: 12 }}>
              {seg.map((s) => <div key={s.label} className="flex items-center gap-2"><span style={{ width: 9, height: 9, borderRadius: 2, background: s.c }} /><span style={{ fontSize: 12.5, color: C.railMute }}>{s.label}</span><span style={{ fontFamily: MONO, fontSize: 12.5, fontWeight: 700, color: "#fff" }}>{s.n.toLocaleString()}</span></div>)}
            </div>
          </div>
        </div>
      </div>
      <div className="grid grid-cols-3 gap-5">{[1, 2, 3].map((r, i) => <RuleStat key={r} r={r} delay={i} mounted={mounted} />)}</div>
      <div className="grid grid-cols-3 gap-5">
        <Panel style={{ padding: 20 }} className="col-span-2">
          <Eyebrow>Score trend · 7 days</Eyebrow>
          <div style={{ height: 190, marginTop: 10 }}>
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={TREND} margin={{ top: 6, right: 8, bottom: 0, left: -20 }}>
                <defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={C.coral} stopOpacity={0.28} /><stop offset="100%" stopColor={C.coral} stopOpacity={0} /></linearGradient></defs>
                <XAxis dataKey="d" tick={{ fill: C.mute, fontSize: 11 }} axisLine={{ stroke: C.line }} tickLine={false} />
                <YAxis domain={[78, 100]} tick={{ fill: C.mute, fontSize: 11 }} axisLine={false} tickLine={false} />
                <Tooltip contentStyle={{ borderRadius: 8, border: `1px solid ${C.line}`, fontSize: 12 }} />
                <Area type="monotone" dataKey="s" stroke={C.coral} strokeWidth={2.5} fill="url(#g)" dot={{ r: 3, fill: C.coral }} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Panel>
        <Panel style={{ padding: 20 }}>
          <Eyebrow>Recent runs</Eyebrow>
          <div className="flex flex-col" style={{ marginTop: 12 }}>
            {RUNS.map((r, i) => <div key={r.id} className="flex items-center justify-between" style={{ padding: "10px 0", borderTop: i ? `1px solid ${C.line}` : "none" }}><div className="flex items-center gap-2"><Circle size={8} fill={C.green} color={C.green} /><span style={{ fontFamily: MONO, fontSize: 12.5 }}>{r.id}</span></div><div className="text-right"><div style={{ fontFamily: MONO, fontSize: 13, fontWeight: 700 }}>{r.score}%</div><div style={{ color: C.mute, fontSize: 11 }}>{r.when}</div></div></div>)}
          </div>
        </Panel>
      </div>
    </div>
  );
}
function RuleStat({ r, delay, mounted }) {
  const n = useCountUp(0, FAILS[r], 1300);
  const pct = (FAILS[r] / TOTAL) * 100;
  return (
    <Panel style={{ padding: 18 }}>
      <div className="flex items-center justify-between"><Tag rule={r} /><span style={{ color: C.mute, fontSize: 12 }}>{r === 1 ? "Min value" : r === 2 ? "Currency" : "Collateral"}</span></div>
      <div style={{ fontFamily: MONO, fontSize: 28, fontWeight: 700, marginTop: 12 }}>{Math.round(n).toLocaleString()}</div>
      <div style={{ color: C.slate, fontSize: 12.5 }}>failed · {(100 - pct).toFixed(1)}% passed</div>
      <div style={{ height: 5, background: C.paper, borderRadius: 3, marginTop: 10, overflow: "hidden" }}><div style={{ width: mounted ? `${Math.min(pct * 6, 100)}%` : "0%", height: "100%", background: RULE[r].c, transition: `width 1s ease ${delay * 0.1}s` }} /></div>
    </Panel>
  );
}

/* ---------- Insights (new) ---------- */
function Insights() {
  const [sum, setSum] = useState(null); // null | loading | done
  const gen = () => { setSum("loading"); setTimeout(() => setSum("done"), 900); };
  const total = NEAR.totalAbove + NEAR.totalBelow;
  const th = { color: C.mute, fontSize: 11, fontWeight: 700, letterSpacing: 0.6, textAlign: "left", padding: "0 0 6px" };

  const NearTable = ({ rows, above, shown, totalN }) => (
    <Panel style={{ padding: 0, overflow: "hidden", borderTop: `3px solid ${above ? C.r1 : C.r3}` }}>
      <div className="flex items-center justify-between" style={{ padding: "14px 16px" }}>
        <div className="flex items-center gap-2">
          {above ? <ArrowUpRight size={16} color={C.r1} /> : <ArrowDownRight size={16} color={C.r3} />}
          <span style={{ fontSize: 14, fontWeight: 700 }}>{above ? "Fragile passes — just above the floor" : "Near-miss removals — just below the floor"}</span>
        </div>
        <span style={{ fontFamily: MONO, fontSize: 13, fontWeight: 700, color: above ? C.r1 : C.r3 }}>{totalN}</span>
      </div>
      <div style={{ padding: "0 16px 8px", fontSize: 12, color: C.slate }}>
        {above ? "Pass today, but a small EUR strengthening would push them under €25,000." : "Fail today, but a small favourable move would clear them — may not be genuinely out of scope."}
      </div>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead><tr><th style={{ ...th, paddingLeft: 16 }}>LOAN</th><th style={th}>COMPANY</th><th style={th}>CCY</th><th style={{ ...th, textAlign: "right" }}>EUR VALUE</th><th style={{ ...th, textAlign: "right" }}>Δ TO FLOOR</th><th style={{ ...th, textAlign: "right", paddingRight: 16 }}>MOVE TO FLIP</th></tr></thead>
        <tbody>
          {rows.map((x) => (
            <tr key={x.loan} style={{ borderTop: `1px solid ${C.line}` }}>
              <td style={{ padding: "10px 0 10px 16px", fontFamily: MONO, fontSize: 12.5, color: C.slate }}>{x.loan}</td>
              <td style={{ fontSize: 13 }}>{x.co}</td>
              <td style={{ fontFamily: MONO, fontSize: 12.5, color: C.slate }}>{x.ccy}</td>
              <td style={{ fontFamily: MONO, fontSize: 13, textAlign: "right" }}>€{x.eur.toLocaleString()}</td>
              <td style={{ textAlign: "right" }}>
                <span style={{ fontFamily: MONO, fontSize: 12.5, fontWeight: 700, color: above ? C.r1 : C.r3, background: above ? C.r1s : C.r3s, padding: "2px 7px", borderRadius: 5 }}>{x.d > 0 ? "+" : ""}{x.d.toFixed(1)}%</span>
              </td>
              <td style={{ fontFamily: MONO, fontSize: 12, color: C.mute, textAlign: "right", paddingRight: 16 }}>≈{Math.abs(x.d).toFixed(1)}% {above ? "adverse" : "favourable"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div style={{ padding: "10px 16px", fontSize: 12, color: C.mute, borderTop: `1px solid ${C.line}` }}>Showing {shown} of {totalN}</div>
    </Panel>
  );

  return (
    <div className="flex flex-col gap-5">
      {/* AI summarizer */}
      <Panel style={{ padding: 18 }}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2" style={{ color: C.r3, fontWeight: 700, fontSize: 14 }}><Sparkles size={16} /> AI insight summary</div>
          {sum !== "done" && <Btn kind="violet" onClick={gen}>{sum === "loading" ? <><Loader2 size={14} className="spin" /> Generating…</> : <><Sparkles size={14} /> Generate summary</>}</Btn>}
        </div>
        {sum === "done" ? <div style={{ fontSize: 13.5, lineHeight: 1.65, marginTop: 12, color: C.text }}>{NEAR.summary}</div>
          : <div style={{ fontSize: 12.5, color: C.mute, marginTop: 8 }}>Summarise the near-threshold picture — which loans are fragile, where the exposure concentrates, and the one-line caveat that this is today's fragility, not a rate prediction.</div>}
      </Panel>

      {/* context header */}
      <Panel style={{ padding: "16px 18px" }}>
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div>
            <div className="flex items-center gap-2"><Gauge size={16} color={C.slate} /><span style={{ fontSize: 15, fontWeight: 700 }}>Near the reporting floor</span></div>
            <div style={{ fontSize: 12.5, color: C.slate, marginTop: 4 }}>Non-EUR loans within <b>{NEAR.band}%</b> of the €25,000 Rule 1 threshold. EUR loans are excluded — they can't move against EUR. This is a fragility signal on today's rates, not a forecast.</div>
          </div>
          <div className="flex gap-5">
            <div className="text-right"><div style={{ fontFamily: MONO, fontSize: 22, fontWeight: 700 }}>{total}</div><div style={{ fontSize: 11, color: C.mute }}>near floor</div></div>
            <div className="text-right"><div style={{ fontFamily: MONO, fontSize: 22, fontWeight: 700, color: C.r1 }}>{NEAR.totalAbove}</div><div style={{ fontSize: 11, color: C.mute }}>fragile passes</div></div>
            <div className="text-right"><div style={{ fontFamily: MONO, fontSize: 22, fontWeight: 700, color: C.r3 }}>{NEAR.totalBelow}</div><div style={{ fontSize: 11, color: C.mute }}>near-miss fails</div></div>
          </div>
        </div>
      </Panel>

      <NearTable rows={NEAR.above} above shown={NEAR.above.length} totalN={NEAR.totalAbove} />
      <NearTable rows={NEAR.below} above={false} shown={NEAR.below.length} totalN={NEAR.totalBelow} />
    </div>
  );
}

/* ---------- Compliance ---------- */
function Compliance() {
  const rows = [{ r: 1, name: "Minimum loan value", cond: "> €25,000 (EUR)", fail: FAILS[1] }, { r: 2, name: "Currency matches HQ", cond: "currency == country", fail: FAILS[2] }, { r: 3, name: "Asset coverage", cond: "asset ≥ 50% of loan", fail: FAILS[3] }];
  const port = [{ co: "Aldergate Industries", country: "Austria", loans: 1420, val: "€1.94B" }, { co: "Kestrel Pharma", country: "Germany", loans: 1180, val: "€1.61B" }, { co: "Marlow Logistics", country: "United Kingdom", loans: 990, val: "£1.28B" }, { co: "Vireo Holdings", country: "Austria", loans: 870, val: "€1.12B" }, { co: "Thornbury Freight", country: "United Kingdom", loans: 640, val: "£0.83B" }];
  const th = { color: C.mute, fontSize: 11, fontWeight: 700, letterSpacing: 0.6, textAlign: "left", padding: "0 0 4px" };
  return (
    <div className="flex flex-col gap-5">
      <Panel style={{ padding: 22 }}>
        <div style={{ fontSize: 15, fontWeight: 700 }}>Rule breakdown</div>
        <div style={{ color: C.slate, fontSize: 13, margin: "4px 0 16px" }}>Every verdict comes from an OPA / Rego policy — deterministic and traceable.</div>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead><tr><th style={th}>RULE</th><th style={th}>CONDITION</th><th style={{ ...th, textAlign: "right" }}>PASSED</th><th style={{ ...th, textAlign: "right" }}>FAILED</th><th style={{ ...th, textAlign: "right" }}>FAIL %</th></tr></thead>
          <tbody>{rows.map((x) => <tr key={x.r} style={{ borderTop: `1px solid ${C.line}` }}><td style={{ padding: "12px 0" }}><Tag rule={x.r} /> <span style={{ fontSize: 13, marginLeft: 6 }}>{x.name}</span></td><td style={{ fontFamily: MONO, fontSize: 12, color: C.slate }}>{x.cond}</td><td style={{ fontFamily: MONO, fontSize: 13, color: C.green, fontWeight: 700, textAlign: "right" }}>{(TOTAL - x.fail).toLocaleString()}</td><td style={{ fontFamily: MONO, fontSize: 13, color: C.r3, fontWeight: 700, textAlign: "right" }}>{x.fail.toLocaleString()}</td><td style={{ fontFamily: MONO, fontSize: 13, color: C.slate, textAlign: "right" }}>{((x.fail / TOTAL) * 100).toFixed(1)}%</td></tr>)}</tbody>
        </table>
      </Panel>
      <Panel style={{ padding: 22 }}>
        <div className="flex items-center gap-2" style={{ marginBottom: 14 }}><Building2 size={16} color={C.slate} /><span style={{ fontSize: 15, fontWeight: 700 }}>Portfolio exposure — top companies</span></div>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead><tr><th style={th}>COMPANY</th><th style={th}>HQ</th><th style={{ ...th, textAlign: "right" }}>LOANS</th><th style={{ ...th, textAlign: "right" }}>TOTAL VALUE</th></tr></thead>
          <tbody>{port.map((p) => <tr key={p.co} style={{ borderTop: `1px solid ${C.line}` }}><td style={{ padding: "11px 0", fontSize: 13, fontWeight: 600 }}>{p.co}</td><td style={{ fontSize: 13, color: C.slate }}>{p.country}</td><td style={{ fontFamily: MONO, fontSize: 13, color: C.slate, textAlign: "right" }}>{p.loans.toLocaleString()}</td><td style={{ fontFamily: MONO, fontSize: 13, fontWeight: 700, textAlign: "right" }}>{p.val}</td></tr>)}</tbody>
        </table>
      </Panel>
    </div>
  );
}

/* ---------- Review ---------- */
function Review() {
  const [st, setSt] = useState(GROUPS.reduce((a, g) => ({ ...a, [g.id]: { open: false, sum: null, resolved: 0 } }), {}));
  const set = (id, p) => setSt((s) => ({ ...s, [id]: { ...s[id], ...p } }));
  const gen = (id) => { set(id, { sum: "loading" }); setTimeout(() => set(id, { sum: "done" }), 850); };
  const resolved = Object.values(st).reduce((a, x) => a + x.resolved, 0);
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between" style={{ padding: "12px 16px", background: "#fff", border: `1px solid ${C.line}`, borderRadius: 12 }}>
        <span style={{ fontSize: 13, color: C.slate }}><b style={{ color: C.text }}>{ANY_FAIL.toLocaleString()}</b> failures · <b style={{ color: C.text }}>{GROUPS.length}</b> groups · precedence R2 → R1 → R3</span>
        <span style={{ fontFamily: MONO, fontSize: 13, fontWeight: 700, color: C.green }}>{resolved.toLocaleString()} resolved</span>
      </div>
      {GROUPS.map((g) => {
        const s = st[g.id], done = s.resolved >= g.count;
        return (
          <Panel key={g.id} style={{ padding: 0, overflow: "hidden", borderLeft: `3px solid ${RULE[g.rule].c}` }}>
            <div className="flex items-center gap-3" style={{ padding: 16, cursor: "pointer" }} onClick={() => set(g.id, { open: !s.open })}>
              {s.open ? <ChevronDown size={17} color={C.mute} /> : <ChevronRight size={17} color={C.mute} />}
              <Tag rule={g.rule} />
              <div className="flex-1"><div style={{ fontSize: 14, fontWeight: 700 }}>{g.title}</div><div style={{ fontSize: 12.5, color: C.slate }}>Fix: {g.fix}</div></div>
              <div className="text-right"><div style={{ fontFamily: MONO, fontSize: 16, fontWeight: 700, color: done ? C.green : C.text }}>{done ? "✓" : (g.count - s.resolved).toLocaleString()}</div>{!done && <div style={{ fontSize: 11, color: C.mute }}>open</div>}</div>
            </div>
            {s.open && (
              <div style={{ borderTop: `1px solid ${C.line}` }}>
                <div style={{ padding: 16, background: C.paper }}>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2" style={{ color: C.r3, fontWeight: 700, fontSize: 13 }}><Sparkles size={15} /> AI group summary</div>
                    {s.sum !== "done" && <Btn kind="violet" onClick={() => gen(g.id)}>{s.sum === "loading" ? <><Loader2 size={14} className="spin" /> Generating…</> : <><Sparkles size={14} /> Generate</>}</Btn>}
                  </div>
                  {s.sum === "done" ? <div style={{ fontSize: 13, lineHeight: 1.6, marginTop: 10, background: "#fff", border: `1px solid ${C.line}`, borderRadius: 8, padding: 13 }}>{g.summary}</div> : !s.sum && <div style={{ fontSize: 12, color: C.mute, marginTop: 8 }}>On-demand summary of the common pattern and the outliers in this group.</div>}
                </div>
                <div style={{ padding: "0 16px 16px" }}>
                  {g.samples.map((x) => (
                    <div key={x.loan} className="flex items-center gap-3" style={{ padding: "11px 0", borderBottom: `1px solid ${C.line}` }}>
                      <span style={{ fontFamily: MONO, fontSize: 12.5, color: C.slate, width: 78 }}>{x.loan}</span>
                      <span style={{ fontSize: 13, flex: 1 }}>{x.co}</span>
                      <span style={{ fontFamily: MONO, fontSize: 12.5, color: x.dead ? C.coralDark : C.slate }}>{x.to ? `${x.from} → ${x.to}` : x.val || x.sub}</span>
                      <div className="flex gap-1.5"><Btn kind="green" style={{ padding: "5px 9px" }}><Check size={13} /></Btn><Btn style={{ padding: "5px 9px" }}><Pencil size={13} /></Btn><Btn kind="red" style={{ padding: "5px 9px" }}><X size={13} /></Btn></div>
                    </div>
                  ))}
                  <div className="flex items-center justify-between" style={{ paddingTop: 12 }}>
                    <span style={{ fontSize: 12, color: C.mute }}>3 of {g.count.toLocaleString()} shown · bulk applies the same fix</span>
                    <div className="flex gap-2"><Btn kind="red" onClick={() => set(g.id, { resolved: g.count })}><X size={14} /> Ignore all</Btn><Btn kind="solid" onClick={() => set(g.id, { resolved: g.count })}><Check size={14} /> Accept all</Btn></div>
                  </div>
                </div>
              </div>
            )}
          </Panel>
        );
      })}
    </div>
  );
}

/* ---------- History ---------- */
function HistoryTab() {
  const [open, setOpen] = useState("074e319c");
  return (
    <div className="flex flex-col gap-4">
      {RUNS.map((r) => (
        <Panel key={r.id} style={{ padding: 0, overflow: "hidden" }}>
          <div className="flex items-center gap-3" style={{ padding: 16, cursor: "pointer" }} onClick={() => setOpen(open === r.id ? null : r.id)}>
            {open === r.id ? <ChevronDown size={17} color={C.mute} /> : <ChevronRight size={17} color={C.mute} />}
            <Circle size={8} fill={C.green} color={C.green} /><span style={{ fontFamily: MONO, fontSize: 14, fontWeight: 600 }}>{r.id}</span>
            <div className="flex-1" /><span style={{ fontFamily: MONO, fontSize: 13, color: C.slate }}>{r.pre}% → <b style={{ color: C.green }}>{r.score}%</b></span>
            <span style={{ fontSize: 12, color: C.mute, width: 132, textAlign: "right" }}>{r.when}</span>
          </div>
          {open === r.id && (
            <div style={{ borderTop: `1px solid ${C.line}`, padding: 20 }}>
              <div style={{ fontSize: 12, color: C.mute, marginBottom: 16 }}>Agent: <b style={{ color: C.text }}>LangGraph + Groq Llama 3.3 70B</b> · Verdicts: OPA / Rego (deterministic)</div>
              {AUDIT.map((a, i) => (
                <div key={i} className="flex gap-3">
                  <div className="flex flex-col items-center"><div style={{ width: 8, height: 8, borderRadius: 8, background: a.tone, marginTop: 5 }} />{i < AUDIT.length - 1 && <div style={{ width: 1.5, flex: 1, background: C.line, marginTop: 2 }} />}</div>
                  <div style={{ paddingBottom: 14 }}><span style={{ fontFamily: MONO, fontSize: 11, color: a.tone, fontWeight: 700 }}>{a.tag}</span><span style={{ fontSize: 13, marginLeft: 10 }}>{a.text}</span></div>
                </div>
              ))}
            </div>
          )}
        </Panel>
      ))}
    </div>
  );
}

/* ---------- assistant ---------- */
const BLURB = {
  dashboard: "Dashboard. This run moved compliance from 85.1% pre-review to 96.2% after healing. Rule 2 (currency) had the most failures at 7,179, then Rule 3 (collateral) at 6,181, then Rule 1 at 3,214. 2,740 loans removed as genuinely below the €25,000 floor.",
  compliance: "Compliance. Each Rego rule with its pass/fail split, plus portfolio exposure by company. Aldergate Industries carries the largest exposure at €1.94B across 1,420 loans. Every verdict traces to an OPA policy.",
  insights: "Insights. 37 non-EUR loans sit within 5% of the €25,000 floor — 22 fragile passes and 15 near-miss removals. Use the AI summary at the top for the narrative; the tables show each loan's distance to the floor. This is a fragility signal on today's rates, not a forecast.",
  review: "Review queue. 14,890 failures clubbed into 9 groups by precedence (R2 → R1 → R3). Bulk-approve a group's shared fix, or open the AI summary to see the common pattern and outliers before deciding.",
  history: "Pipeline history. Each run expands to its audit trail — ingest through verify — with deterministic OPA verdicts and the LangGraph agent's remediation steps. Latest run re-scored 85.1% → 96.2%.",
};
function Assistant({ page, open, onClose }) {
  const [msgs, setMsgs] = useState([{ role: "bot", text: BLURB[page] }]);
  const [txt, setTxt] = useState("");
  useEffect(() => { setMsgs([{ role: "bot", text: BLURB[page] }]); }, [page]);
  const send = () => { if (!txt.trim()) return; setMsgs((m) => [...m, { role: "user", text: txt }, { role: "bot", text: "Prototype — a live assistant would answer from this page's data and the audit log." }]); setTxt(""); };
  if (!open) return null;
  return (
    <div style={{ width: 340, borderLeft: `1px solid ${C.line}`, background: "#fff", display: "flex", flexDirection: "column", height: "100vh", position: "sticky", top: 0 }}>
      <div className="flex items-center justify-between" style={{ padding: "14px 16px", borderBottom: `1px solid ${C.line}` }}>
        <div className="flex items-center gap-2" style={{ fontWeight: 700, fontSize: 14 }}><Sparkles size={16} color={C.coral} /> Page assistant</div>
        <PanelRightClose size={18} color={C.mute} style={{ cursor: "pointer" }} onClick={onClose} />
      </div>
      <div className="flex-1 flex flex-col gap-2" style={{ padding: 14, overflowY: "auto" }}>
        {msgs.map((m, i) => <div key={i} style={{ alignSelf: m.role === "user" ? "flex-end" : "flex-start", maxWidth: "88%", background: m.role === "user" ? C.coral : C.paper, color: m.role === "user" ? "#fff" : C.text, fontSize: 13, lineHeight: 1.5, padding: "9px 12px", borderRadius: 11 }}>{m.text}</div>)}
      </div>
      <div className="flex gap-2" style={{ padding: 14, borderTop: `1px solid ${C.line}` }}>
        <input value={txt} onChange={(e) => setTxt(e.target.value)} onKeyDown={(e) => e.key === "Enter" && send()} placeholder="Ask about this page…" style={{ flex: 1, fontSize: 13, fontFamily: FONT, border: `1px solid ${C.lineStrong}`, borderRadius: 8, padding: "8px 11px", outline: "none" }} />
        <Btn kind="solid" onClick={send} style={{ padding: "8px 11px" }}><Send size={15} /></Btn>
      </div>
    </div>
  );
}

/* ---------- shell ---------- */
export default function App() {
  const [tab, setTab] = useState("dashboard");
  const [running, setRunning] = useState(false);
  const [asst, setAsst] = useState(true);
  const nav = [{ id: "dashboard", label: "Dashboard", icon: LayoutDashboard }, { id: "compliance", label: "Compliance", icon: ShieldCheck }, { id: "insights", label: "Insights", icon: Gauge }, { id: "review", label: "Review", icon: ClipboardCheck, badge: `${(ANY_FAIL / 1000).toFixed(1)}k` }, { id: "history", label: "History", icon: HistoryIcon }];
  const title = nav.find((n) => n.id === tab).label;
  const run = () => { setRunning(true); setTimeout(() => setRunning(false), 1600); };
  return (
    <div style={{ fontFamily: FONT, background: C.paper, color: C.text, display: "flex", minHeight: "100vh" }}>
      <style>{`.spin{animation:sp 1s linear infinite}@keyframes sp{to{transform:rotate(360deg)}}*{box-sizing:border-box}button:focus-visible,input:focus-visible{outline:2px solid ${C.coral};outline-offset:1px}`}</style>
      <div style={{ width: 216, background: C.railBg, color: C.railText, display: "flex", flexDirection: "column", position: "sticky", top: 0, height: "100vh" }}>
        <div style={{ padding: "20px 18px" }}><div style={{ fontSize: 18, fontWeight: 800, letterSpacing: -0.3 }}>Kyndryl</div><div style={{ fontSize: 11, color: C.railMute, marginTop: 2 }}>Loan Compliance</div></div>
        <div style={{ padding: "6px 12px", display: "flex", flexDirection: "column", gap: 2 }}>
          {nav.map((n) => { const on = tab === n.id, Icon = n.icon; return (
            <button key={n.id} onClick={() => setTab(n.id)} style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 12px", borderRadius: 8, border: "none", cursor: "pointer", textAlign: "left", fontFamily: FONT, fontSize: 13.5, fontWeight: on ? 700 : 500, background: on ? "rgba(255,76,52,0.16)" : "transparent", color: on ? "#fff" : C.railText, borderLeft: on ? `2px solid ${C.coral}` : "2px solid transparent" }}>
              <Icon size={17} color={on ? C.coral : C.railMute} /><span className="flex-1">{n.label}</span>{n.badge && <span style={{ fontFamily: MONO, fontSize: 10.5, fontWeight: 700, background: C.railEl, color: C.railMute, padding: "1px 6px", borderRadius: 7 }}>{n.badge}</span>}
            </button>); })}
        </div>
        <div style={{ marginTop: "auto", padding: 18, borderTop: `1px solid ${C.inkLine}`, display: "flex", alignItems: "center", gap: 14 }}>
          <Ring value={POST} run={tab === "dashboard"} />
          <div><div style={{ fontSize: 11, color: C.railMute }}>Live score</div><div style={{ fontSize: 12.5, color: C.railText, marginTop: 2 }}>after healing</div><div style={{ fontSize: 11, color: C.greenBright, marginTop: 2 }}>▲ {(POST - PRE).toFixed(1)} pts</div></div>
        </div>
      </div>
      <div className="flex-1" style={{ minWidth: 0 }}>
        <div className="flex items-center justify-between" style={{ padding: "16px 24px", borderBottom: `1px solid ${C.line}`, background: "#fff" }}>
          <div><Eyebrow>Run 074e319c</Eyebrow><div style={{ fontSize: 19, fontWeight: 700, marginTop: 2 }}>{title}</div></div>
          <div className="flex items-center gap-2">
            {!asst && <Btn onClick={() => setAsst(true)}><Sparkles size={15} color={C.coral} /> Assistant</Btn>}
            <Btn kind="solid" onClick={run} disabled={running} style={{ opacity: running ? 0.7 : 1 }}>{running ? <><Loader2 size={15} className="spin" /> Running…</> : <><Play size={15} /> Run pipeline</>}</Btn>
          </div>
        </div>
        <div style={{ padding: 24, maxWidth: 1000 }}>
          {tab === "dashboard" && <Dashboard />}
          {tab === "compliance" && <Compliance />}
          {tab === "insights" && <Insights />}
          {tab === "review" && <Review />}
          {tab === "history" && <HistoryTab />}
        </div>
      </div>
      <Assistant page={tab} open={asst} onClose={() => setAsst(false)} />
    </div>
  );
}
