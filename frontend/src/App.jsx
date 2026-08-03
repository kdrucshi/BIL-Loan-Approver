import React, { useState, useEffect } from "react";
import {
  LayoutDashboard, ShieldCheck, ClipboardCheck, History as HistoryIcon,
  Play, ChevronDown, ChevronRight, Sparkles, Check, X, Pencil,
  Send, Loader2, Circle, Building2, ArrowRight, Zap, Lightbulb
} from "lucide-react";
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";

/* ---------- light app palette (unchanged) + Option B hero accents ---------- */
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

/* ---------- Backend API integration ---------- */
// All calls go through the /api prefix, proxied to the FastAPI backend by
// vite.config.js (see server.proxy) - no hardcoded host, no CORS issues.

const AUDIT_TONE_BY_SOURCE = {
  ingest: C.slate,
  evaluate: C.slate,
  rule_eval: C.slate,
  score: C.coralDark,
  reviewer: C.green,
  report: C.slate,
};

function formatPortfolioValue(totalValue, currency) {
  const n = Number(totalValue) || 0;
  if (n >= 1e9) return `${currency === "EUR" ? "€" : currency + " "}${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6) return `${currency === "EUR" ? "€" : currency + " "}${(n / 1e6).toFixed(2)}M`;
  return `${currency === "EUR" ? "€" : currency + " "}${n.toLocaleString()}`;
}

async function getJSON(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${path} -> HTTP ${res.status}`);
  return res.json();
}

/** Fetches every tab's data from the real backend in parallel, then maps
 * each response into the exact shape the existing UI components expect
 * (see `initialData` above) - this is the ONE integration seam; the
 * components themselves are untouched. */
async function loadAllData() {
  const [dashboard, compliance, insights, reviewGroups] = await Promise.all([
    getJSON("/api/dashboard"),
    getJSON("/api/compliance"),
    getJSON("/api/insights/fx-fragility"),
    getJSON("/api/review/groups"),
  ]);

  const runId = dashboard.run_id;
  const [history, historyDetail] = await Promise.all([
    getJSON("/api/history"),
    runId ? getJSON(`/api/history/${runId}`) : Promise.resolve({ audit_trail: [] }),
  ]);

  // Real sample loans per rule bucket, used to populate each review group's
  // example rows with actual data instead of inventing placeholders.
  const [bucket1, bucket2, bucket3] = await Promise.all([
    getJSON("/api/review/loans?bucket=1&limit=10"),
    getJSON("/api/review/loans?bucket=2&limit=500"), // enough to cover every currency sub-group
    getJSON("/api/review/loans?bucket=3&limit=10"),
  ]);

  const groups = reviewGroups.groups.map((g) => {
    let samples = [];
    if (g.rule === 1) {
      samples = bucket1.loans.slice(0, 3).map((l) => ({
        loan: l.loan_id, co: l.company_name,
        val: `€${Math.round(Number(l.loan_value_eur)).toLocaleString()}`,
      }));
    } else if (g.rule === 2) {
      const targetCurrency = g.id.replace("rule2-to-", "");
      samples = bucket2.loans
        .filter((l) => l.expected_currency === targetCurrency)
        .slice(0, 3)
        .map((l) => ({ loan: l.loan_id, co: l.company_name, from: l.loan_currency, to: l.expected_currency }));
    } else if (g.rule === 3) {
      samples = bucket3.loans.slice(0, 3).map((l) => ({
        loan: l.loan_id, co: l.company_name,
        sub: l.suggestion_text || "— suggestion not generated yet",
        dead: (l.suggestion_text || "").includes("No asset"),
      }));
    }
    return { ...g, samples };
  });

  return {
    total: dashboard.total,
    fails: dashboard.fails,
    anyFail: dashboard.any_fail,
    compliant: dashboard.compliant,
    pre: dashboard.pre_review_compliance ?? 0,
    post: dashboard.post_review_compliance ?? dashboard.pre_review_compliance ?? 0,
    removed: dashboard.removed,
    trend: dashboard.trend.map((t) => ({ d: (t.date || "").slice(5, 10) || t.run_id, s: t.score })),
    runs: history.runs.map((r) => ({
      id: r.run_id, score: r.post_review_compliance ?? r.pre_review_compliance,
      pre: r.pre_review_compliance, when: r.started_at,
    })),
    audit: historyDetail.audit_trail.map((e) => ({
      tag: e.source,
      tone: AUDIT_TONE_BY_SOURCE[e.source] || C.slate,
      text: e.loan_id ? `${e.message} (${e.loan_id})` : e.message,
    })),
    groups,
    portfolio: compliance.portfolio.map((p) => ({
      co: p.company_name, country: p.hq_country, loans: p.n_loans,
      val: formatPortfolioValue(p.total_value, p.loan_currency),
    })),
    insights: {
      nearFloorTotal: insights.total_above + insights.total_below,
      fragilePassesCount: insights.total_above,
      nearMissFailsCount: insights.total_below,
      fragilePasses: insights.above.map((a) => ({
        id: a.loan_id, company: a.company_name, currency: a.currency,
        eurValue: `€${Math.round(a.eur_value).toLocaleString()}`,
        deltaPct: a.distance_pct.toFixed(2),
        movePct: Math.abs(a.distance_pct).toFixed(2),
      })),
      nearMissFails: insights.below.map((a) => ({
        id: a.loan_id, company: a.company_name, currency: a.currency,
        eurValue: `€${Math.round(a.eur_value).toLocaleString()}`,
        deltaPct: a.distance_pct.toFixed(2),
        movePct: Math.abs(a.distance_pct).toFixed(2),
      })),
      summary: null, // generated on demand via POST /api/insights/fx-fragility/summary
    },
  };
}


const DataContext = React.createContext();

const initialData = {
  total: 0,
  fails: { 1: 0, 2: 0, 3: 0 },
  anyFail: 0,
  compliant: 0,
  pre: 0,
  post: 0,
  removed: 0,
  trend: [],
  runs: [],
  audit: [],
  groups: [],
  portfolio: [],
  insights: {
    nearFloorTotal: 0,
    fragilePassesCount: 0,
    nearMissFailsCount: 0,
    fragilePasses: [],
    nearMissFails: [],
    summary: null
  }
};

/* ---------- motion ---------- */
function useCountUp(from, to, dur = 1400, run = true) {
  const [v, setV] = useState(from);
  useEffect(() => {
    if (!run) { setV(to); return; }
    let raf, start;
    const step = (t) => { 
      if (!start) start = t; 
      const p = Math.min((t - start) / dur, 1); 
      const e = 1 - Math.pow(1 - p, 3); 
      setV(from + (to - from) * e); 
      if (p < 1) raf = requestAnimationFrame(step); 
    };
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
  const { total, fails, anyFail, compliant, pre, post, removed, trend, runs } = React.useContext(DataContext);
  const mounted = useMounted();
  const score = useCountUp(pre, post, 1600);
  const loans = useCountUp(0, total, 1400);
  const seg = [{ label: "Compliant", n: compliant, c: C.greenBright }, { label: "Rule 1", n: fails[1], c: C.r1 }, { label: "Rule 2", n: fails[2], c: C.r2 }, { label: "Rule 3", n: fails[3], c: C.r3 }];
  const segTotal = seg.reduce((a, s) => a + s.n, 0) || 1; // avoid div by 0
  
  return (
    <div className="flex flex-col gap-5">
      {/* HERO — Option B palette */}
      <div style={{ position: "relative", overflow: "hidden", borderRadius: 16, background: `linear-gradient(135deg, ${C.ink} 0%, ${C.ink2} 70%, ${C.ink3} 100%)`, border: `1px solid #232D3E`, padding: 28 }}>
        <div style={{ position: "absolute", top: -90, right: -50, width: 300, height: 300, background: `radial-gradient(circle, ${C.cyan}33 0%, transparent 68%)` }} />
        <div style={{ position: "relative" }}>
          <div className="flex items-start justify-between flex-wrap" style={{ gap: 20 }}>
            <div>
              <Eyebrow dark>Compliance · after healing</Eyebrow>
              <div className="flex items-end gap-3" style={{ marginTop: 10 }}>
                <span style={{ fontFamily: MONO, fontSize: 66, fontWeight: 800, lineHeight: 0.9, color: C.amber, letterSpacing: -2 }}>{score.toFixed(1)}<span style={{ fontSize: 32 }}>%</span></span>
                <div style={{ marginBottom: 8 }}>
                  <div className="flex items-center gap-2" style={{ fontSize: 13, fontFamily: MONO }}>
                    <span style={{ color: C.railMute }}>{pre}%</span><ArrowRight size={14} color={C.railMute} /><span style={{ color: C.greenBright, fontWeight: 700 }}>{post}%</span>
                  </div>
                  <div style={{ display: "inline-flex", alignItems: "center", gap: 5, marginTop: 6, background: "rgba(52,211,153,0.14)", color: "#6EE7B7", fontSize: 12.5, fontWeight: 700, padding: "3px 9px", borderRadius: 6 }}>
                    <Zap size={13} /> +{(post - pre).toFixed(1)} pts healed
                  </div>
                </div>
              </div>
              <div style={{ color: C.railMute, fontSize: 13.5, marginTop: 12 }}>
                <b style={{ color: "#fff", fontFamily: MONO }}>{Math.round(loans).toLocaleString()}</b> loans checked · <b style={{ color: "#fff", fontFamily: MONO }}>{anyFail.toLocaleString()}</b> failures remediated by human review
              </div>
            </div>
            <div style={{ background: "rgba(255,255,255,0.04)", border: `1px solid #232D3E`, borderRadius: 12, padding: "12px 16px" }}>
              <div className="text-right">
                <div style={{ color: C.railMute, fontSize: 11 }}>Removed · Rule 1</div>
                <div style={{ fontFamily: MONO, fontSize: 22, fontWeight: 700, color: C.r2 }}>{removed.toLocaleString()}</div>
              </div>
            </div>
          </div>
          <div style={{ marginTop: 22 }}>
            <div style={{ display: "flex", height: 40, borderRadius: 9, overflow: "hidden", background: "rgba(255,255,255,0.06)" }}>
              {seg.map((s, i) => <div key={s.label} title={`${s.label}: ${s.n.toLocaleString()}`} style={{ width: mounted ? `${(s.n / segTotal) * 100}%` : "0%", background: s.c, transition: `width 1.1s cubic-bezier(.22,1,.36,1) ${i * 0.1}s`, minWidth: mounted && s.n > 0 ? 3 : 0 }} />)}
            </div>
            <div className="flex flex-wrap gap-x-5 gap-y-2" style={{ marginTop: 12 }}>
              {seg.map((s) => (
                <div key={s.label} className="flex items-center gap-2">
                  <span style={{ width: 9, height: 9, borderRadius: 2, background: s.c }} />
                  <span style={{ fontSize: 12.5, color: C.railMute }}>{s.label}</span>
                  <span style={{ fontFamily: MONO, fontSize: 12.5, fontWeight: 700, color: "#fff" }}>{s.n.toLocaleString()}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">{[1, 2, 3].map((r, i) => <RuleStat key={r} r={r} delay={i} mounted={mounted} />)}</div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        <Panel style={{ padding: 20 }} className="lg:col-span-2">
          <Eyebrow>Score trend · 7 days</Eyebrow>
          <div style={{ height: 190, marginTop: 10 }}>
            {trend.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={trend} margin={{ top: 6, right: 8, bottom: 0, left: -20 }}>
                  <defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={C.coral} stopOpacity={0.28} /><stop offset="100%" stopColor={C.coral} stopOpacity={0} /></linearGradient></defs>
                  <XAxis dataKey="d" tick={{ fill: C.mute, fontSize: 11 }} axisLine={{ stroke: C.line }} tickLine={false} />
                  <YAxis domain={[78, 100]} tick={{ fill: C.mute, fontSize: 11 }} axisLine={false} tickLine={false} />
                  <Tooltip contentStyle={{ borderRadius: 8, border: `1px solid ${C.line}`, fontSize: 12 }} />
                  <Area type="monotone" dataKey="s" stroke={C.coral} strokeWidth={2.5} fill="url(#g)" dot={{ r: 3, fill: C.coral }} />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <div className="flex h-full items-center justify-center text-slate-400 text-sm">No trend data available</div>
            )}
          </div>
        </Panel>
        <Panel style={{ padding: 20 }}>
          <Eyebrow>Recent runs</Eyebrow>
          <div className="flex flex-col" style={{ marginTop: 12 }}>
            {runs.length > 0 ? runs.map((r, i) => (
              <div key={r.id} className="flex items-center justify-between" style={{ padding: "10px 0", borderTop: i ? `1px solid ${C.line}` : "none" }}>
                <div className="flex items-center gap-2"><Circle size={8} fill={C.green} color={C.green} /><span style={{ fontFamily: MONO, fontSize: 12.5 }}>{r.id}</span></div>
                <div className="text-right"><div style={{ fontFamily: MONO, fontSize: 13, fontWeight: 700 }}>{r.score}%</div><div style={{ color: C.mute, fontSize: 11 }}>{r.when}</div></div>
              </div>
            )) : <div className="text-slate-400 text-sm mt-4 text-center">No recent runs</div>}
          </div>
        </Panel>
      </div>
    </div>
  );
}

function RuleStat({ r, delay, mounted }) {
  const { fails, total } = React.useContext(DataContext);
  const n = useCountUp(0, fails[r], 1300);
  const pct = total > 0 ? (fails[r] / total) * 100 : 0;
  return (
    <Panel style={{ padding: 18 }}>
      <div className="flex items-center justify-between"><Tag rule={r} /><span style={{ color: C.mute, fontSize: 12 }}>{r === 1 ? "Min value" : r === 2 ? "Currency" : "Collateral"}</span></div>
      <div style={{ fontFamily: MONO, fontSize: 28, fontWeight: 700, marginTop: 12 }}>{Math.round(n).toLocaleString()}</div>
      <div style={{ color: C.slate, fontSize: 12.5 }}>failed · {(100 - pct).toFixed(1)}% passed</div>
      <div style={{ height: 5, background: C.paper, borderRadius: 3, marginTop: 10, overflow: "hidden" }}>
        <div style={{ width: mounted ? `${Math.min(pct * 6, 100)}%` : "0%", height: "100%", background: RULE[r].c, transition: `width 1s ease ${delay * 0.1}s` }} />
      </div>
    </Panel>
  );
}

/* ---------- Compliance ---------- */
function Compliance() {
  const { fails, total, portfolio } = React.useContext(DataContext);
  const rows = [
    { r: 1, name: "Minimum loan value", cond: "> €25,000 (EUR)", fail: fails[1] },
    { r: 2, name: "Currency matches HQ", cond: "currency == country", fail: fails[2] }, 
    { r: 3, name: "Asset coverage", cond: "asset ≥ 50% of loan", fail: fails[3] }
  ];
  const th = { color: C.mute, fontSize: 11, fontWeight: 700, letterSpacing: 0.6, textAlign: "left", padding: "0 0 4px" };
  
  return (
    <div className="flex flex-col gap-5">
      <Panel style={{ padding: 22 }}>
        <div style={{ fontSize: 15, fontWeight: 700 }}>Rule breakdown</div>
        <div style={{ color: C.slate, fontSize: 13, margin: "4px 0 16px" }}>Every verdict comes from an OPA / Rego policy — deterministic and traceable.</div>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead><tr><th style={th}>RULE</th><th style={th}>CONDITION</th><th style={{ ...th, textAlign: "right" }}>PASSED</th><th style={{ ...th, textAlign: "right" }}>FAILED</th><th style={{ ...th, textAlign: "right" }}>FAIL %</th></tr></thead>
          <tbody>{rows.map((x) => <tr key={x.r} style={{ borderTop: `1px solid ${C.line}` }}><td style={{ padding: "12px 0" }}><Tag rule={x.r} /> <span style={{ fontSize: 13, marginLeft: 6 }}>{x.name}</span></td><td style={{ fontFamily: MONO, fontSize: 12, color: C.slate }}>{x.cond}</td><td style={{ fontFamily: MONO, fontSize: 13, color: C.green, fontWeight: 700, textAlign: "right" }}>{(total - x.fail).toLocaleString()}</td><td style={{ fontFamily: MONO, fontSize: 13, color: C.r3, fontWeight: 700, textAlign: "right" }}>{x.fail.toLocaleString()}</td><td style={{ fontFamily: MONO, fontSize: 13, color: C.slate, textAlign: "right" }}>{total > 0 ? ((x.fail / total) * 100).toFixed(1) : "0.0"}%</td></tr>)}</tbody>
        </table>
      </Panel>
      <Panel style={{ padding: 22 }}>
        <div className="flex items-center gap-2" style={{ marginBottom: 14 }}><Building2 size={16} color={C.slate} /><span style={{ fontSize: 15, fontWeight: 700 }}>Portfolio exposure — top companies</span></div>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead><tr><th style={th}>COMPANY</th><th style={th}>HQ</th><th style={{ ...th, textAlign: "right" }}>LOANS</th><th style={{ ...th, textAlign: "right" }}>TOTAL VALUE</th></tr></thead>
          <tbody>
            {portfolio.length > 0 ? portfolio.map((p) => <tr key={p.co} style={{ borderTop: `1px solid ${C.line}` }}><td style={{ padding: "11px 0", fontSize: 13, fontWeight: 600 }}>{p.co}</td><td style={{ fontSize: 13, color: C.slate }}>{p.country}</td><td style={{ fontFamily: MONO, fontSize: 13, color: C.slate, textAlign: "right" }}>{p.loans.toLocaleString()}</td><td style={{ fontFamily: MONO, fontSize: 13, fontWeight: 700, textAlign: "right" }}>{p.val}</td></tr>) : <tr><td colSpan="4" className="py-4 text-center text-sm text-slate-400">No portfolio data available</td></tr>}
          </tbody>
        </table>
      </Panel>
    </div>
  );
}

/* ---------- Insights ---------- */
function InsightsTab() {
  const { insights } = React.useContext(DataContext);
  const data = insights || { nearFloorTotal: 0, fragilePassesCount: 0, nearMissFailsCount: 0, fragilePasses: [], nearMissFails: [], summary: null };
  const [sumState, setSumState] = useState(data.summary ? "done" : null);
  const [summaryText, setSummaryText] = useState(data.summary);
  const gen = async () => {
    setSumState("loading");
    try {
      const res = await fetch("/api/insights/fx-fragility/summary", { method: "POST" });
      const body = await res.json();
      setSummaryText(body.summary);
      setSumState("done");
    } catch (e) {
      console.error("Failed to generate insight summary:", e);
      setSumState(null);
    }
  };
  const th = { color: C.mute, fontSize: 11, fontWeight: 700, letterSpacing: 0.6, textAlign: "left", padding: "0 0 4px" };
  const thGreen = { ...th, color: C.green, borderBottom: `2px solid ${C.greenSoft}`, padding: "0 0 8px" };
  const thRed = { ...th, color: C.r3, borderBottom: `2px solid ${C.r3s}`, padding: "0 0 8px" };

  return (
    <div className="flex flex-col gap-5">
      <Panel style={{ padding: 16, background: C.paper }}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2" style={{ color: C.coralDark, fontWeight: 700, fontSize: 13 }}><Sparkles size={15} /> AI insight summary</div>
          {sumState !== "done" && <Btn kind="violet" onClick={gen}>{sumState === "loading" ? <><Loader2 size={14} className="spin" /> Generating…</> : <><Sparkles size={14} /> Generate</>}</Btn>}
        </div>
        {sumState === "done" ? <div style={{ fontSize: 13, lineHeight: 1.6, marginTop: 10, background: "#fff", border: `1px solid ${C.line}`, borderRadius: 8, padding: 13 }}>{summaryText || "Summary of fragile passes and near-misses will appear here when data is loaded."}</div> : !sumState && <div style={{ fontSize: 12, color: C.mute, marginTop: 8 }}>On-demand summary narrating the tables below.</div>}
      </Panel>
      
      <div className="flex items-center justify-between" style={{ padding: "12px 16px", background: "#fff", border: `1px solid ${C.line}`, borderRadius: 12 }}>
        <span style={{ fontSize: 13, color: C.slate }}>Non-EUR loans within 5% of €25,000 floor. <b style={{ color: C.text }}>{data.nearFloorTotal.toLocaleString()}</b> total · <b style={{ color: C.text }}>{data.fragilePassesCount.toLocaleString()}</b> fragile passes · <b style={{ color: C.text }}>{data.nearMissFailsCount.toLocaleString()}</b> near-misses</span>
        <span style={{ fontSize: 12, color: C.mute }}>Today's fragility, not a forecast</span>
      </div>

      <Panel style={{ padding: 22 }}>
        <div style={{ fontSize: 15, fontWeight: 700, color: C.green }}>Fragile passes</div>
        <div style={{ color: C.slate, fontSize: 13, margin: "4px 0 16px" }}>Above the floor today, but a small EUR strengthening would push them under.</div>
        <div className="insight-scroll" style={{ maxHeight: 380, overflowY: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead style={{ position: "sticky", top: 0, background: "#fff", zIndex: 1 }}><tr><th style={thGreen}>LOAN</th><th style={thGreen}>COMPANY</th><th style={thGreen}>CURRENCY</th><th style={{ ...thGreen, textAlign: "right" }}>EUR VALUE</th><th style={{ ...thGreen, textAlign: "right" }}>Δ TO FLOOR</th><th style={{ ...thGreen, textAlign: "right" }}>MOVE TO FLIP</th></tr></thead>
            <tbody>
              {data.fragilePasses.length > 0 ? data.fragilePasses.map((r, i) => (
                <tr key={r.id || i} style={{ borderTop: `1px solid ${C.line}` }}>
                  <td style={{ padding: "11px 0", fontFamily: MONO, fontSize: 12.5, color: C.slate }}>{r.id}</td>
                  <td style={{ fontSize: 13 }}>{r.company}</td>
                  <td style={{ fontSize: 13, color: C.slate }}>{r.currency}</td>
                  <td style={{ fontFamily: MONO, fontSize: 13, textAlign: "right" }}>{r.eurValue}</td>
                  <td style={{ fontFamily: MONO, fontSize: 13, color: C.green, textAlign: "right" }}>+{r.deltaPct}%</td>
                  <td style={{ fontFamily: MONO, fontSize: 13, color: C.r2, textAlign: "right" }}>≈{r.movePct}% adverse</td>
                </tr>
              )) : <tr><td colSpan="6" className="py-4 text-center text-sm text-slate-400">No fragile passes data available</td></tr>}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel style={{ padding: 22 }}>
        <div style={{ fontSize: 15, fontWeight: 700, color: C.r3 }}>Near-miss removals</div>
        <div style={{ color: C.slate, fontSize: 13, margin: "4px 0 16px" }}>Below the floor today, but a small favourable move would clear them.</div>
        <div className="insight-scroll" style={{ maxHeight: 380, overflowY: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead style={{ position: "sticky", top: 0, background: "#fff", zIndex: 1 }}><tr><th style={thRed}>LOAN</th><th style={thRed}>COMPANY</th><th style={thRed}>CURRENCY</th><th style={{ ...thRed, textAlign: "right" }}>EUR VALUE</th><th style={{ ...thRed, textAlign: "right" }}>Δ TO FLOOR</th><th style={{ ...thRed, textAlign: "right" }}>MOVE TO FLIP</th></tr></thead>
            <tbody>
              {data.nearMissFails.length > 0 ? data.nearMissFails.map((r, i) => (
                <tr key={r.id || i} style={{ borderTop: `1px solid ${C.line}` }}>
                  <td style={{ padding: "11px 0", fontFamily: MONO, fontSize: 12.5, color: C.slate }}>{r.id}</td>
                  <td style={{ fontSize: 13 }}>{r.company}</td>
                  <td style={{ fontSize: 13, color: C.slate }}>{r.currency}</td>
                  <td style={{ fontFamily: MONO, fontSize: 13, textAlign: "right" }}>{r.eurValue}</td>
                  <td style={{ fontFamily: MONO, fontSize: 13, color: C.r3, textAlign: "right" }}>{r.deltaPct}%</td>
                  <td style={{ fontFamily: MONO, fontSize: 13, color: C.green, textAlign: "right" }}>≈{r.movePct}% favourable</td>
                </tr>
              )) : <tr><td colSpan="6" className="py-4 text-center text-sm text-slate-400">No near-misses data available</td></tr>}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}


/* ---------- Review ---------- */
function Review({ st, setSt }) {
  const { anyFail, groups } = React.useContext(DataContext);
  const set = (id, p) => setSt((s) => ({ ...s, [id]: { ...s[id], ...p } }));
  const gen = (id) => { set(id, { sum: "loading" }); setTimeout(() => set(id, { sum: "done" }), 850); };
  const resolved = Object.values(st).reduce((a, x) => a + (x.resolved || 0), 0);
  const [applying, setApplying] = useState({}); // loanId -> bool, disables buttons mid-request

  // The one real integration point for the human-in-the-loop actions
  // (Action_Engine.md section 9): calls the backend's decide endpoint for
  // the loan's rule, which applies the fix and re-checks through OPA.
  const applyDecision = async (g, loanId, decision) => {
    setApplying((a) => ({ ...a, [loanId]: true }));
    try {
      if (g.rule === 1) {
        await fetch(`/api/review/${loanId}/rule1/decide`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ decision: decision === "manual" ? "accept" : decision }),
        });
      } else if (g.rule === 2) {
        let manual_currency;
        if (decision === "manual") {
          manual_currency = window.prompt("Correct currency code (e.g. EUR):");
          if (!manual_currency) { setApplying((a) => ({ ...a, [loanId]: false })); return; }
        }
        await fetch(`/api/review/${loanId}/rule2/decide`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ decision, manual_currency }),
        });
      } else if (g.rule === 3) {
        let manual_asset;
        if (decision === "manual") {
          const asset_description = window.prompt("Substitute asset description:");
          const asset_value = window.prompt("Substitute asset value:");
          if (!asset_description || !asset_value) { setApplying((a) => ({ ...a, [loanId]: false })); return; }
          manual_asset = { asset_description, asset_value: parseFloat(asset_value) };
        } else if (decision !== "ignore") {
          // Rule 3 needs a suggestion generated before it can be accepted
          // (the LangGraph thread must reach its human-review interrupt first).
          await fetch(`/api/review/${loanId}/rule3/generate`, { method: "POST" });
        }
        await fetch(`/api/review/${loanId}/rule3/decide`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ decision, manual_asset }),
        });
      }
      set(g.id, { resolved: (st[g.id]?.resolved || 0) + 1 });
    } catch (e) {
      console.error(`Failed to apply ${decision} for ${loanId}:`, e);
    } finally {
      setApplying((a) => ({ ...a, [loanId]: false }));
    }
  };
  
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between" style={{ padding: "12px 16px", background: "#fff", border: `1px solid ${C.line}`, borderRadius: 12 }}>
        <span style={{ fontSize: 13, color: C.slate }}><b style={{ color: C.text }}>{anyFail.toLocaleString()}</b> failures · <b style={{ color: C.text }}>{groups.length}</b> groups · precedence R2 → R1 → R3</span>
        <span style={{ fontFamily: MONO, fontSize: 13, fontWeight: 700, color: C.green }}>{resolved.toLocaleString()} resolved</span>
      </div>
      {groups.length > 0 ? groups.map((g) => {
        const s = st[g.id] || { open: false, sum: null, resolved: 0 };
        const done = s.resolved >= g.count;
        return (
          <Panel key={g.id} style={{ padding: 0, overflow: "hidden", borderLeft: `3px solid ${RULE[g.rule].c}` }}>
            <div className="flex items-center gap-3" style={{ padding: 16, cursor: "pointer" }} onClick={() => set(g.id, { open: !s.open })}>
              {s.open ? <ChevronDown size={17} color={C.mute} /> : <ChevronRight size={17} color={C.mute} />}
              <Tag rule={g.rule} />
              <div className="flex-1"><div style={{ fontSize: 14, fontWeight: 700 }}>{g.title}</div><div style={{ fontSize: 12.5, color: C.slate }}>Fix: {g.fix}</div></div>
              <div className="text-right"><div style={{ fontFamily: MONO, fontSize: 16, fontWeight: 700, color: done ? C.green : C.text }}>{done ? "✓" : (g.count - (s.resolved || 0)).toLocaleString()}</div>{!done && <div style={{ fontSize: 11, color: C.mute }}>open</div>}</div>
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
                  {g.samples && g.samples.map((x) => (
                    <div key={x.loan} className="flex items-center gap-3" style={{ padding: "11px 0", borderBottom: `1px solid ${C.line}` }}>
                      <span style={{ fontFamily: MONO, fontSize: 12.5, color: C.slate, width: 78 }}>{x.loan}</span>
                      <span style={{ fontSize: 13, flex: 1 }}>{x.co}</span>
                      <span style={{ fontFamily: MONO, fontSize: 12.5, color: x.dead ? C.coralDark : C.slate }}>{x.to ? `${x.from} → ${x.to}` : x.val || x.sub}</span>
                      <div className="flex gap-1.5">
                        <Btn kind="green" style={{ padding: "5px 9px" }} disabled={applying[x.loan]} onClick={() => applyDecision(g, x.loan, "accept")}><Check size={13} /></Btn>
                        <Btn style={{ padding: "5px 9px" }} disabled={applying[x.loan]} onClick={() => applyDecision(g, x.loan, "manual")}><Pencil size={13} /></Btn>
                        <Btn kind="red" style={{ padding: "5px 9px" }} disabled={applying[x.loan]} onClick={() => applyDecision(g, x.loan, "ignore")}><X size={13} /></Btn>
                      </div>
                    </div>
                  ))}
                  <div className="flex items-center justify-between" style={{ paddingTop: 12 }}>
                    <span style={{ fontSize: 12, color: C.mute }}>{g.samples?.length || 0} of {g.count.toLocaleString()} shown · bulk applies the same fix</span>
                    <div className="flex gap-2"><Btn kind="red" onClick={() => set(g.id, { resolved: g.count })}><X size={14} /> Ignore all</Btn><Btn kind="solid" onClick={() => set(g.id, { resolved: g.count })}><Check size={14} /> Accept all</Btn></div>
                  </div>
                </div>
              </div>
            )}
          </Panel>
        );
      }) : <div className="text-center text-sm text-slate-400 py-8">No review groups generated yet</div>}
    </div>
  );
}

/* ---------- History ---------- */
function HistoryTab() {
  const { runs, audit } = React.useContext(DataContext);
  const [open, setOpen] = useState(runs.length > 0 ? runs[0].id : null);
  
  return (
    <div className="flex flex-col gap-4">
      {runs.length > 0 ? runs.map((r) => (
        <Panel key={r.id} style={{ padding: 0, overflow: "hidden" }}>
          <div className="flex items-center gap-3" style={{ padding: 16, cursor: "pointer" }} onClick={() => setOpen(open === r.id ? null : r.id)}>
            {open === r.id ? <ChevronDown size={17} color={C.mute} /> : <ChevronRight size={17} color={C.mute} />}
            <Circle size={8} fill={C.green} color={C.green} /><span style={{ fontFamily: MONO, fontSize: 14, fontWeight: 600 }}>{r.id}</span>
            <div className="flex-1" /><span style={{ fontFamily: MONO, fontSize: 13, color: C.slate }}>{r.pre}% → <b style={{ color: C.green }}>{r.score}%</b></span>
            <span style={{ fontSize: 12, color: C.mute, width: 132, textAlign: "right" }}>{r.when}</span>
          </div>
          {open === r.id && (
            <div style={{ borderTop: `1px solid ${C.line}`, padding: 20 }}>
              <div style={{ fontSize: 12, color: C.mute, marginBottom: 16 }}>Agent: <b style={{ color: C.text }}>LangGraph + Azure OpenAI (gpt-5.4-mini)</b> · Verdicts: OPA / Rego (deterministic)</div>
              {audit.length > 0 ? audit.map((a, i) => (
                <div key={i} className="flex gap-3">
                  <div className="flex flex-col items-center"><div style={{ width: 8, height: 8, borderRadius: 8, background: a.tone, marginTop: 5 }} />{i < audit.length - 1 && <div style={{ width: 1.5, flex: 1, background: C.line, marginTop: 2 }} />}</div>
                  <div style={{ paddingBottom: 14 }}><span style={{ fontFamily: MONO, fontSize: 11, color: a.tone, fontWeight: 700 }}>{a.tag}</span><span style={{ fontSize: 13, marginLeft: 10 }}>{a.text}</span></div>
                </div>
              )) : <div className="text-sm text-slate-400">No audit trail available</div>}
            </div>
          )}
        </Panel>
      )) : <div className="text-center text-sm text-slate-400 py-8">No run history available</div>}
    </div>
  );
}

/* ---------- assistant ---------- */
function buildBlurb(page, ctx, data) {
  if (!data) return "";
  switch (page) {
    case "dashboard":
      return `Dashboard. This run moved compliance from ${data.pre}% pre-review to ${data.post}% after healing. Rule 2 (currency) had the most failures at ${data.fails[2].toLocaleString()}, then Rule 3 (collateral) at ${data.fails[3].toLocaleString()}, then Rule 1 at ${data.fails[1].toLocaleString()}. ${data.removed.toLocaleString()} loans removed as genuinely below the €25,000 floor.`;
    case "compliance": {
      const top = data.portfolio?.[0];
      if (!top) return "Compliance. Each Rego rule with its pass/fail split, plus portfolio exposure by company.";
      return `Compliance. Each Rego rule with its pass/fail split, plus portfolio exposure by company. ${top.co} carries the largest exposure at ${top.val} across ${top.loans.toLocaleString()} loans. Every verdict traces to an OPA policy.`;
    }
    case "insights":
      return `Insights. Surfacing FX fragility for non-EUR loans. ${data.insights?.fragilePassesCount || 0} passes are fragile to a 5% adverse move. ${data.insights?.nearMissFailsCount || 0} near-miss removals could pass on a 5% favourable move.`;
    case "review":
      return `Review queue. ${data.anyFail.toLocaleString()} failures clubbed into ${data.groups?.length || 0} groups by precedence (R2 → R1 → R3). ${(ctx?.resolved ?? 0).toLocaleString()} resolved so far. Bulk-approve a group's shared fix, or open the AI summary to see the common pattern and outliers before deciding.`;
    case "history":
      return `Pipeline history. Each run expands to its audit trail — ingest through verify — with deterministic OPA verdicts and the LangGraph agent's remediation steps. Latest run re-scored ${data.pre}% → ${data.post}%.`;
    default:
      return "";
  }
}

function Assistant({ page, ctx, open, onToggle }) {
  const data = React.useContext(DataContext);
  const [msgs, setMsgs] = useState([{ role: "bot", text: buildBlurb(page, ctx, data) }]);
  const [txt, setTxt] = useState("");
  const [sending, setSending] = useState(false);

  useEffect(() => { 
    if (open) setMsgs([{ role: "bot", text: buildBlurb(page, ctx, data) }]); 
  }, [page, ctx, open, data]);

  // Grounded in the real backend (POST /api/assistant, gpt-5.4-mini) - the
  // model only sees this page's own live data (see _assistant_context in
  // app/main.py), never invents numbers not already on screen.
  const send = async () => {
    const message = txt.trim();
    if (!message || sending) return;
    const history = msgs.slice(-6).map((m) => ({ role: m.role === "user" ? "user" : "assistant", content: m.text }));
    setMsgs((m) => [...m, { role: "user", text: message }]);
    setTxt("");
    setSending(true);
    try {
      const res = await fetch("/api/assistant", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ page, message, history }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const body = await res.json();
      setMsgs((m) => [...m, { role: "bot", text: body.reply }]);
    } catch (e) {
      console.error("Assistant request failed:", e);
      setMsgs((m) => [...m, { role: "bot", text: "Sorry, I couldn't reach the assistant just now — please try again." }]);
    } finally {
      setSending(false);
    }
  };
  
  return (
    <>
      <button
        onClick={onToggle}
        aria-label={open ? "Close page assistant" : "Open page assistant"}
        style={{ position: "fixed", right: 24, bottom: 24, width: 52, height: 52, borderRadius: "50%", background: C.coral, color: "#fff", border: "none", cursor: "pointer", boxShadow: "0 10px 24px rgba(255,76,52,0.35)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 60 }}
      >
        {open ? <X size={22} /> : <Sparkles size={22} />}
      </button>
      {open && (
        <div style={{ position: "fixed", right: 24, bottom: 88, width: 340, maxHeight: "min(70vh, 560px)", borderRadius: 14, border: `1px solid ${C.line}`, background: "#fff", boxShadow: "0 20px 50px rgba(14,20,32,0.2)", display: "flex", flexDirection: "column", zIndex: 60, overflow: "hidden" }}>
          <div className="flex items-center justify-between" style={{ padding: "14px 16px", borderBottom: `1px solid ${C.line}` }}>
            <div className="flex items-center gap-2" style={{ fontWeight: 700, fontSize: 14 }}><Sparkles size={16} color={C.coral} /> Page assistant</div>
            <X size={18} color={C.mute} style={{ cursor: "pointer" }} onClick={onToggle} />
          </div>
          <div className="flex-1 flex flex-col gap-2" style={{ padding: 14, overflowY: "auto" }}>
            {msgs.map((m, i) => <div key={i} style={{ alignSelf: m.role === "user" ? "flex-end" : "flex-start", maxWidth: "88%", background: m.role === "user" ? C.coral : C.paper, color: m.role === "user" ? "#fff" : C.text, fontSize: 13, lineHeight: 1.5, padding: "9px 12px", borderRadius: 11 }}>{m.text}</div>)}
            {sending && <div style={{ alignSelf: "flex-start", display: "flex", alignItems: "center", gap: 6, color: C.mute, fontSize: 12, padding: "9px 12px" }}><Loader2 size={13} className="spin" /> Thinking…</div>}
          </div>
          <div className="flex gap-2" style={{ padding: 14, borderTop: `1px solid ${C.line}` }}>
            <input value={txt} onChange={(e) => setTxt(e.target.value)} onKeyDown={(e) => e.key === "Enter" && send()} disabled={sending} placeholder="Ask about this page…" style={{ flex: 1, fontSize: 13, fontFamily: FONT, border: `1px solid ${C.lineStrong}`, borderRadius: 8, padding: "8px 11px", outline: "none" }} />
            <Btn kind="solid" onClick={send} disabled={sending} style={{ padding: "8px 11px", opacity: sending ? 0.6 : 1 }}><Send size={15} /></Btn>
          </div>
        </div>
      )}
    </>
  );
}

/* ---------- shell ---------- */
export default function App() {
  const [data, setData] = useState(initialData);
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState("dashboard");
  const [running, setRunning] = useState(false);
  const [asst, setAsst] = useState(false);
  const [reviewState, setReviewState] = useState({});

  const fetchBackendData = async () => {
    setLoading(true);
    try {
      const mapped = await loadAllData();
      setData(mapped);
    } catch (e) {
      console.error("Failed to load data from backend:", e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchBackendData();
  }, []);

  useEffect(() => {
    if (data && data.groups) {
      setReviewState(data.groups.reduce((a, g) => ({ ...a, [g.id]: { open: false, sum: null, resolved: 0 } }), {}));
    }
  }, [data.groups]);

  const reviewResolved = Object.values(reviewState).reduce((a, x) => a + (x.resolved || 0), 0);
  
  const nav = [
    { id: "dashboard", label: "Dashboard", icon: LayoutDashboard }, 
    { id: "compliance", label: "Compliance", icon: ShieldCheck },
    { id: "insights", label: "Insights", icon: Lightbulb }, 
    { id: "review", label: "Review", icon: ClipboardCheck, badge: data.anyFail > 0 ? `${(data.anyFail / 1000).toFixed(1)}k` : undefined }, 
    { id: "history", label: "History", icon: HistoryIcon }
  ];
  
  const title = nav.find((n) => n.id === tab).label;
  
  // Triggers a fresh Engine 1 evaluation on the backend (OPA re-run over the
  // full 100k loans, ~20s), then polls run history until a new completed
  // run appears, then reloads every tab's data from that new run.
  const run = async () => {
    setRunning(true);
    try {
      const before = await getJSON("/api/history");
      const beforeCount = before.runs.length;
      await fetch("/api/run", { method: "POST" });

      for (let attempt = 0; attempt < 40; attempt++) {
        await new Promise((r) => setTimeout(r, 1500));
        const after = await getJSON("/api/history");
        if (after.runs.length > beforeCount && after.runs[0]?.status === "completed") break;
      }
      await fetchBackendData();
    } catch (e) {
      console.error("Failed to run pipeline:", e);
    } finally {
      setRunning(false);
    }
  };
  
  return (
    <DataContext.Provider value={data}>
      <div style={{ fontFamily: FONT, background: C.paper, color: C.text, display: "flex", minHeight: "100vh" }}>
        <style>{`.spin{animation:sp 1s linear infinite}@keyframes sp{to{transform:rotate(360deg)}}*{box-sizing:border-box}button:focus-visible,input:focus-visible{outline:2px solid ${C.coral};outline-offset:1px}`}</style>
        {/* rail */}
        <div style={{ width: 216, background: C.railBg, color: C.railText, display: "flex", flexDirection: "column", position: "sticky", top: 0, height: "100vh" }}>
          <div style={{ padding: "20px 18px" }}><div style={{ fontSize: 18, fontWeight: 800, letterSpacing: -0.3 }}>Kyndryl</div><div style={{ fontSize: 11, color: C.railMute, marginTop: 2 }}>Loan Compliance</div></div>
          <div style={{ padding: "6px 12px", display: "flex", flexDirection: "column", gap: 2 }}>
            {nav.map((n) => { const on = tab === n.id, Icon = n.icon; return (
              <button key={n.id} onClick={() => setTab(n.id)} style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 12px", borderRadius: 8, border: "none", cursor: "pointer", textAlign: "left", fontFamily: FONT, fontSize: 13.5, fontWeight: on ? 700 : 500, background: on ? "rgba(255,76,52,0.16)" : "transparent", color: on ? "#fff" : C.railText, borderLeft: on ? `2px solid ${C.coral}` : "2px solid transparent" }}>
                <Icon size={17} color={on ? C.coral : C.railMute} /><span className="flex-1">{n.label}</span>{n.badge && <span style={{ fontFamily: MONO, fontSize: 10.5, fontWeight: 700, background: C.railEl, color: C.railMute, padding: "1px 6px", borderRadius: 7 }}>{n.badge}</span>}
              </button>); })}
          </div>
        </div>
        {/* main */}
        <div className="flex-1 flex flex-col" style={{ minWidth: 0, height: "100vh", overflowY: "auto" }}>
          <div className="flex items-center justify-between shrink-0" style={{ padding: "24px 32px", borderBottom: `1px solid ${C.line}`, background: "#fff" }}>
            <div><Eyebrow>Run Dashboard</Eyebrow><div style={{ fontSize: 19, fontWeight: 700, marginTop: 2 }}>{title}</div></div>
            <div className="flex items-center gap-2">
              <Btn kind="solid" onClick={run} disabled={running || loading} style={{ opacity: (running || loading) ? 0.7 : 1 }}>{(running || loading) ? <><Loader2 size={15} className="spin" /> Fetching…</> : <><Play size={15} /> Run pipeline</>}</Btn>
            </div>
          </div>
          <div className="w-full flex-1" style={{ padding: 32 }}>
            {tab === "dashboard" && <Dashboard />}
            {tab === "compliance" && <Compliance />}
            {tab === "insights" && <InsightsTab />}
            {tab === "review" && <Review st={reviewState} setSt={setReviewState} />}
            {tab === "history" && <HistoryTab />}
          </div>
        </div>
        <Assistant page={tab} ctx={{ resolved: reviewResolved }} open={asst} onToggle={() => setAsst((v) => !v)} />
      </div>
    </DataContext.Provider>
  );
}
