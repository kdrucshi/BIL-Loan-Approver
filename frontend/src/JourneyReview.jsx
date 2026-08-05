import React, { useState, useEffect, useRef } from "react";
import {
  Search, ChevronLeft, ChevronRight, ChevronDown, Check, Pencil, X,
  ArrowRight, ArrowDown, ArrowUpDown, CircleAlert, CircleCheck, ExternalLink, Info, Building2,
  LayoutDashboard, ClipboardCheck, ShieldCheck, BarChart3,
  FileText, RefreshCw, AlertTriangle, Sparkles, SlidersHorizontal, RotateCcw, Loader2, Trash2
} from "lucide-react";

const C = {
  coral: "#FF4C34", coralLt: "#FF7A66", coralDark: "#D93A22", coralSoft: "#FFEDE8",
  amber: "#FBBF3C", cyan: "#38BDF8",
  ink: "#0E1420", ink2: "#141B29", ink3: "#1A2233", inkLine: "rgba(255,255,255,0.08)",
  railBg: "#16181E", railText: "#E8EAEF", railMute: "#7E8695", railEl: "#2A2E39",
  paper: "#F6F7F9", card: "#FFFFFF", line: "#E8EAEE", lineStrong: "#D8DBE2",
  text: "#16181E", slate: "#545A64", mute: "#8A909B",
  green: "#16B15E", greenSoft: "#E7F7EE", greenBright: "#34D399",
  r1: "#E0A02E", r1s: "#F7F0DF", r2: "#E3742E", r2s: "#FBEADD", r3: "#D6462A", r3s: "#FADFD9",
  yellowHl: "#FDE68A",
};
const FONT = "Inter, system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif";
const MONO = "ui-monospace, SFMono-Regular, Menlo, monospace";
const RULE = { 1: { c: C.r1, s: C.r1s }, 2: { c: C.r2, s: C.r2s }, 3: { c: C.r3, s: C.r3s } };
const row = (gap = 0, extra = {}) => ({ display: "flex", alignItems: "center", gap, ...extra });
const col = (gap = 0, extra = {}) => ({ display: "flex", flexDirection: "column", gap, ...extra });
const PER_PAGE = 25;
// Single source of truth for every number rendered on this screen — always en-US
// grouping with no decimals, so figures never render with locale-dependent
// (e.g. Indian) digit grouping or stray trailing decimals.
const fmtMoney = (n) => new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(Number(n) || 0);
const fmtNum = fmtMoney;

async function getJSON(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${path} -> HTTP ${res.status}`);
  return res.json();
}
async function postJSON(path, body) {
  const res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) throw new Error(`${path} -> HTTP ${res.status}`);
  return res.json();
}

const Card = ({ children, style, ...p }) => (<div {...p} style={{ background: C.card, border: `1px solid ${C.line}`, borderRadius: 12, ...style }}>{children}</div>);
const Label = ({ children, color = C.mute }) => (<div style={{ color, fontSize: 10.5, fontWeight: 700, letterSpacing: 0.4, textTransform: "uppercase" }}>{children}</div>);
const Tag = ({ rule, size = 11 }) => { const r = RULE[rule]; return <span style={{ background: r.s, color: r.c, fontFamily: MONO, fontSize: size, fontWeight: 700, padding: "2px 7px", borderRadius: 5, whiteSpace: "nowrap" }}>R{rule}</span>; };
const pageBtn = { background: C.card, border: `1px solid ${C.line}`, borderRadius: 7, padding: "6px 10px", cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 4, fontFamily: FONT, fontSize: 12.5, fontWeight: 600, color: C.slate };
const sectionTitle = { fontSize: 13, fontWeight: 700, color: C.text };
const RISK_COLOR = { High: { bg: C.r3s, fg: C.r3 }, Medium: { bg: C.r2s, fg: C.r2 }, Low: { bg: C.greenSoft, fg: C.green } };
const fInput = { flex: 1, width: "100%", border: `1px solid ${C.lineStrong}`, borderRadius: 7, padding: "6px 9px", fontFamily: MONO, fontSize: 12, color: C.text, outline: "none", background: C.card, minWidth: 0 };
const SORTS = {
  value_desc: { label: "Loan value · high → low" },
  value_asc: { label: "Loan value · low → high" },
  conf_desc: { label: "AI confidence · high → low" },
  conf_asc: { label: "AI confidence · low → high" },
};

function riskFor(row) {
  const eur = Number(row.loan_value_eur) || 0;
  if (eur > 5_000_000) return "High";
  if (eur >= 1_000_000) return "Medium";
  return "Low";
}

function FxStrip({ fx }) {
  if (!fx) {
    return (
      <div style={{ ...row(10), background: C.card, border: `1px solid ${C.line}`, borderRadius: 10, padding: "9px 14px", marginBottom: 14, color: C.mute, fontSize: 12.5 }}>
        <RefreshCw size={14} color={C.mute} /> Loading this run's FX rates…
      </div>
    );
  }
  const stale = fx.stale;
  return (
    <div style={{ ...row(12, { flexWrap: "wrap" }), background: stale ? C.r1s : C.card, border: `1px solid ${stale ? C.r1 : C.line}`, borderRadius: 10, padding: "9px 14px", marginBottom: 14 }}>
      <div style={{ ...row(7), fontWeight: 700, fontSize: 12.5, color: stale ? C.r1 : C.text }}>
        {stale ? <AlertTriangle size={15} color={C.r1} /> : <RefreshCw size={15} color={C.slate} />}
        FX rate
        <span style={{ fontFamily: MONO, fontSize: 10.5, fontWeight: 800, letterSpacing: 0.5, background: stale ? C.r1 : C.greenSoft, color: stale ? "#fff" : C.green, padding: "2px 7px", borderRadius: 4 }}>{stale ? "STALE" : "FRESH"}</span>
      </div>
      <span style={{ width: 1, height: 16, background: stale ? "rgba(224,160,46,0.4)" : C.line }} />
      {fx.rate_to_eur != null && <span style={{ fontFamily: MONO, fontSize: 12.5, color: C.text }}>1 {fx.currency} = {fx.rate_to_eur.toFixed(4)} EUR</span>}
      <span style={{ fontSize: 12, color: C.slate }}>{stale ? "cached — primary + secondary timed out" : `source: ${fx.source}`} · as of <b style={{ color: stale ? C.r1 : C.text }}>{fx.as_of}</b></span>
      <span style={{ marginLeft: "auto", fontSize: 11.5, color: C.mute }}>Fixed for this run · re-run to refresh</span>
    </div>
  );
}

function StagePipeline({ stages, activeRule, onPick, overall }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ ...row(7), marginBottom: 10 }}>
        <span style={{ fontSize: 15, fontWeight: 800, color: C.ink }}>Review Pipeline</span>
        <span style={{ fontSize: 12.5, color: C.mute }}>precedence R2 → R1 → R3</span>
        <Info size={13} color={C.mute} />
      </div>
      <div style={{ ...row(0), alignItems: "stretch" }}>
        {stages.map((s, i) => (
          <React.Fragment key={s.rule}>
            <StageCard {...s} active={s.rule === activeRule} onClick={() => onPick(s.rule)} />
            {i < stages.length - 1 && (<div style={{ ...row(0, { justifyContent: "center" }), padding: "0 8px" }}><ArrowRight size={16} color={C.lineStrong} /></div>)}
          </React.Fragment>
        ))}
        <div style={{ width: 12 }} />
        <OverallProgress overall={overall} />
      </div>
    </div>
  );
}
function StageCard({ n, name, rule, active, queue, onClick }) {
  const accent = RULE[rule].c, accentSoft = RULE[rule].s;
  return (
    <button onClick={onClick} style={{ all: "unset", cursor: "pointer", flex: 1, minWidth: 0, background: active ? accentSoft : C.card, border: `1px solid ${active ? accent : C.line}`, borderRadius: 11, padding: "13px 15px" }}>
      <div style={{ ...row(0, { justifyContent: "space-between" }), alignItems: "flex-start" }}>
        <div style={row(9)}>
          <div style={{ width: 24, height: 24, borderRadius: 24, background: active ? accent : "transparent", border: `1.5px solid ${active ? accent : C.lineStrong}`, color: active ? "#fff" : C.mute, ...row(0, { justifyContent: "center" }), fontFamily: MONO, fontSize: 12.5, fontWeight: 700 }}>{n}</div>
          <div>
            <div style={{ fontSize: 13.5, fontWeight: 700, color: active ? accent : C.text, lineHeight: 1.2 }}>{name}</div>
            <div style={{ fontSize: 11.5, color: C.mute, marginTop: 1 }}>Rule {rule}</div>
          </div>
        </div>
        <Tag rule={rule} size={10.5} />
      </div>
      <div style={{ ...row(0, { justifyContent: "space-between" }), marginTop: 11 }}>
        <span style={{ fontSize: 12, color: active ? accent : C.mute, fontWeight: active ? 700 : 500 }}>{active ? "In progress" : "Pending"}</span>
        <span style={{ fontFamily: MONO, fontSize: 12, color: C.slate }}>{fmtNum(queue)} <span style={{ color: C.mute }}>queued</span></span>
      </div>
    </button>
  );
}
function OverallProgress({ overall }) {
  const pct = overall.total ? (overall.reviewed / overall.total) * 100 : 0;
  return (
    <div style={{ minWidth: 216, background: C.ink, borderRadius: 11, padding: "13px 15px" }}>
      <div style={row(0, { justifyContent: "space-between" })}>
        <div style={{ fontSize: 12.5, fontWeight: 700, color: "#fff" }}>Overall progress</div>
        <div style={{ fontSize: 13, fontWeight: 800, color: C.amber, fontFamily: MONO }}>{pct.toFixed(0)}%</div>
      </div>
      <div style={{ height: 5, background: "rgba(255,255,255,0.1)", borderRadius: 4, marginTop: 11, overflow: "hidden" }}><div style={{ width: `${pct}%`, height: "100%", background: C.coral }} /></div>
      <div style={{ fontSize: 11.5, color: C.railMute, marginTop: 9 }}><span style={{ fontFamily: MONO, color: "#fff", fontWeight: 600 }}>{fmtNum(overall.reviewed)}</span> / {fmtNum(overall.total)} reviewed</div>
    </div>
  );
}

function Queue({ activeRule, stages, rows, stageTotal, filteredTotal, summary, filters, setFilters, activeId, onPick, sel, setSel, loading }) {
  const [sortOpen, setSortOpen] = useState(false);
  const [showFilters, setShowFilters] = useState(false);
  const [minDraft, setMinDraft] = useState(filters.min);
  const [maxDraft, setMaxDraft] = useState(filters.max);
  const [qDraft, setQDraft] = useState(filters.q || "");
  const debounceRef = useRef(null);
  const qDebounceRef = useRef(null);

  useEffect(() => { setMinDraft(filters.min); setMaxDraft(filters.max); }, [filters.min, filters.max]);
  useEffect(() => { setQDraft(filters.q || ""); }, [filters.q]);

  const debouncedRangeChange = (min, max) => {
    setMinDraft(min); setMaxDraft(max);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => setFilters((f) => ({ ...f, min, max, page: 1 })), 300);
  };
  const debouncedQChange = (q) => {
    setQDraft(q);
    if (qDebounceRef.current) clearTimeout(qDebounceRef.current);
    qDebounceRef.current = setTimeout(() => setFilters((f) => ({ ...f, q, page: 1 })), 300);
  };

  const anyFilter = filters.ccy !== "All" || filters.min !== "" || filters.max !== "" || filters.lowConf || !!filters.q;
  const activeFilterCount = (filters.ccy !== "All" ? 1 : 0) + (filters.min !== "" || filters.max !== "" ? 1 : 0) + (filters.lowConf ? 1 : 0) + (filters.q ? 1 : 0);
  const pageCount = Math.max(1, Math.ceil((filteredTotal || 0) / PER_PAGE));

  const viewIds = rows.map((l) => l.id);
  const allSelected = viewIds.length > 0 && viewIds.every((id) => sel.has(id));
  const someSelected = viewIds.some((id) => sel.has(id));
  const toggle = (id) => { const n = new Set(sel); n.has(id) ? n.delete(id) : n.add(id); setSel(n); };
  const toggleAll = () => { const n = new Set(sel); allSelected ? viewIds.forEach((id) => n.delete(id)) : viewIds.forEach((id) => n.add(id)); setSel(n); };
  const clearFilters = () => setFilters((f) => ({ ...f, ccy: "All", min: "", max: "", lowConf: false, q: "", page: 1 }));
  // Single source of truth for the stage name: the same `stages` data that drives
  // the pipeline cards above, never a separately-maintained local map.
  const stageName = stages?.find((s) => s.rule === activeRule)?.name || "";

  return (
    <Card style={{ padding: 0, overflow: "hidden", alignSelf: "start" }}>
      <div style={{ padding: 16 }}>
        <div style={{ ...row(7), marginBottom: 7 }}><Tag rule={activeRule} /><div style={{ fontSize: 13.5, fontWeight: 700, color: C.text }}>{stageName} queue</div></div>
        <div style={row(7, { alignItems: "baseline" })}>
          <span style={{ fontFamily: MONO, fontSize: 26, fontWeight: 800, color: C.ink }}>{fmtNum(filteredTotal)}</span>
          <span style={{ fontSize: 12.5, color: C.mute }}>{anyFilter ? "match the filter" : "loans to review"}</span>
        </div>
        {anyFilter && <div style={{ fontSize: 11.5, color: C.mute, marginTop: 3 }}>of {fmtNum(stageTotal)} in this stage</div>}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", borderTop: `1px solid ${C.line}`, borderBottom: `1px solid ${C.line}` }}>
        <MiniStat label="Suggested" value={summary.suggested} color={C.green} />
        <MiniStat label="Needs review" value={summary.needsReview} color={C.r2} divider />
        <MiniStat label="Ignored" value={summary.ignored} color={C.mute} divider />
      </div>

      <div style={{ ...row(8), padding: 12, borderBottom: `1px solid ${C.line}` }}>
        <div style={{ ...row(8, { flex: 1 }), background: C.paper, border: `1px solid ${C.line}`, borderRadius: 8, padding: "7px 10px" }}>
          <Search size={14} color={C.mute} />
          <input
            placeholder="Search company, loan id…"
            value={qDraft}
            onChange={(e) => debouncedQChange(e.target.value)}
            style={{ border: "none", background: "transparent", outline: "none", flex: 1, fontFamily: FONT, fontSize: 12.5, color: C.text, minWidth: 0 }}
          />
        </div>
        <button onClick={() => setShowFilters((v) => !v)} style={{ ...row(5), background: showFilters || activeFilterCount ? C.coralSoft : C.card, border: `1px solid ${showFilters || activeFilterCount ? C.coral + "55" : C.lineStrong}`, borderRadius: 8, padding: "7px 11px", fontFamily: FONT, fontSize: 12.5, fontWeight: 600, color: activeFilterCount ? C.coralDark : C.text, cursor: "pointer" }}>
          <SlidersHorizontal size={12} /> Filters{activeFilterCount ? ` · ${activeFilterCount}` : ""}
        </button>
      </div>

      {showFilters && (
        <div style={{ padding: "13px 16px", borderBottom: `1px solid ${C.line}`, background: C.paper, ...col(11) }}>
          <div>
            <Label>Loan value range (EUR)</Label>
            <div style={{ ...row(7), marginTop: 6 }}>
              <input value={minDraft} onChange={(e) => debouncedRangeChange(e.target.value.replace(/\D/g, ""), maxDraft)} placeholder="Min" style={fInput} />
              <span style={{ color: C.mute, fontSize: 12 }}>–</span>
              <input value={maxDraft} onChange={(e) => debouncedRangeChange(minDraft, e.target.value.replace(/\D/g, ""))} placeholder="Max" style={fInput} />
            </div>
          </div>
          <div>
            <Label>Currency</Label>
            <div style={{ ...row(6, { flexWrap: "wrap" }), marginTop: 6 }}>
              {["All", "USD", "GBP", "SEK", "CHF", "CAD", "PLN", "JPY"].map((c) => (
                <button key={c} onClick={() => setFilters((f) => ({ ...f, ccy: c, page: 1 }))} style={{ fontFamily: MONO, fontSize: 11.5, fontWeight: 700, padding: "4px 9px", borderRadius: 6, cursor: "pointer", border: `1px solid ${filters.ccy === c ? C.coral : C.lineStrong}`, background: filters.ccy === c ? C.coralSoft : C.card, color: filters.ccy === c ? C.coralDark : C.slate }}>{c}</button>
              ))}
            </div>
          </div>
          <label style={{ ...row(8), cursor: "pointer" }}>
            <input type="checkbox" checked={filters.lowConf} onChange={(e) => setFilters((f) => ({ ...f, lowConf: e.target.checked, page: 1 }))} style={{ accentColor: C.coral, width: 15, height: 15 }} />
            <span style={{ fontSize: 12.5, color: C.text }}>Only low AI confidence (&lt;80%)</span>
          </label>
          {activeFilterCount > 0 && (
            <button onClick={clearFilters} style={{ ...row(5), alignSelf: "start", background: "none", border: "none", color: C.slate, fontFamily: FONT, fontSize: 12, fontWeight: 600, cursor: "pointer", padding: 0 }}>
              <RotateCcw size={12} /> Clear filters
            </button>
          )}
        </div>
      )}

      <div style={{ ...row(0, { justifyContent: "space-between" }), padding: "9px 16px", borderBottom: `1px solid ${C.line}` }}>
        <label style={{ ...row(8), cursor: "pointer" }}>
          <input type="checkbox" checked={allSelected} ref={(el) => { if (el) el.indeterminate = someSelected && !allSelected; }} onChange={toggleAll} style={{ accentColor: C.coral, width: 15, height: 15 }} />
          <span style={{ fontSize: 12, color: C.slate, fontWeight: 600 }}>{someSelected ? `${viewIds.filter((id) => sel.has(id)).length} selected` : "Select all on page"}</span>
        </label>
        <div style={{ position: "relative" }}>
          <button onClick={() => setSortOpen((v) => !v)} style={{ ...row(5), background: "none", border: "none", fontFamily: FONT, fontSize: 12, color: C.slate, cursor: "pointer", padding: 0 }}>
            <ArrowUpDown size={12} /> {SORTS[filters.sort].label} <ChevronDown size={12} />
          </button>
          {sortOpen && (
            <div style={{ position: "absolute", right: 0, top: 24, zIndex: 10, background: C.card, border: `1px solid ${C.lineStrong}`, borderRadius: 8, boxShadow: "0 6px 20px rgba(0,0,0,0.1)", overflow: "hidden", minWidth: 190 }}>
              {Object.entries(SORTS).map(([k, v]) => (
                <button key={k} onClick={() => { setFilters((f) => ({ ...f, sort: k, page: 1 })); setSortOpen(false); }} style={{ display: "block", width: "100%", textAlign: "left", padding: "8px 12px", background: k === filters.sort ? C.paper : C.card, border: "none", fontFamily: FONT, fontSize: 12.5, color: C.text, cursor: "pointer" }}>{v.label}</button>
              ))}
            </div>
          )}
        </div>
      </div>

      <div style={{ maxHeight: 520, overflowY: "auto" }}>
        {loading && <div style={{ padding: "28px 16px", textAlign: "center", color: C.mute, fontSize: 12.5 }}><Loader2 size={16} className="spin" /> Loading…</div>}
        {!loading && rows.length === 0 && (
          <div style={{ padding: "28px 16px", textAlign: "center", color: C.mute, fontSize: 12.5 }}>No loans match these filters. <button onClick={clearFilters} style={{ background: "none", border: "none", color: C.coralDark, fontWeight: 600, cursor: "pointer" }}>Clear filters</button></div>
        )}
        {!loading && rows.map((l) => {
          const active = l.id === activeId;
          const checked = sel.has(l.id);
          const r = RISK_COLOR[l.risk];
          return (
            <div key={l.id} style={{ display: "grid", gridTemplateColumns: "22px 1fr auto", gap: 10, alignItems: "center", padding: "11px 16px", paddingLeft: active ? 13 : 16, borderTop: `1px solid ${C.line}`, background: checked ? "#FFF6F3" : active ? C.coralSoft : "transparent", borderLeft: active ? `3px solid ${C.coral}` : "3px solid transparent" }}>
              <input type="checkbox" checked={checked} onChange={() => toggle(l.id)} onClick={(e) => e.stopPropagation()} style={{ accentColor: C.coral, width: 15, height: 15, cursor: "pointer" }} />
              <div style={{ minWidth: 0, cursor: "pointer" }} onClick={() => onPick(l.id)}>
                <div style={{ ...row(7) }}>
                  <span style={{ fontFamily: MONO, fontSize: 12.5, color: C.text, fontWeight: 600 }}>{l.id}</span>
                  {l.alsoFails?.map((r) => (
                    <span key={r} style={{ fontSize: 9.5, fontWeight: 800, letterSpacing: 0.3, color: RULE[r].c, background: RULE[r].s, padding: "1px 5px", borderRadius: 4 }}>also fails R{r}</span>
                  ))}
                  {l.conf != null && l.conf < 80 && <span style={{ fontSize: 9.5, fontWeight: 800, color: C.mute, background: C.paper, padding: "1px 5px", borderRadius: 4 }}>{l.conf}%</span>}
                </div>
                <div style={{ fontSize: 12.5, color: C.slate, marginTop: 2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{l.co}</div>
              </div>
              <div style={{ textAlign: "right", cursor: "pointer" }} onClick={() => onPick(l.id)}>
                <div style={{ fontFamily: MONO, fontSize: 12.5, color: C.text }}>{l.value} <span style={{ color: C.mute }}>{l.ccy}</span></div>
                <div style={{ marginTop: 4 }}><span style={{ background: r.bg, color: r.fg, fontSize: 10.5, fontWeight: 700, padding: "1px 7px", borderRadius: 4 }}>{l.risk}</span></div>
              </div>
            </div>
          );
        })}
      </div>

      <div style={{ ...row(0, { justifyContent: "space-between" }), padding: "12px 16px", borderTop: `1px solid ${C.line}` }}>
        <button onClick={() => setFilters((f) => ({ ...f, page: Math.max(1, f.page - 1) }))} disabled={filters.page <= 1} style={{ ...pageBtn, opacity: filters.page <= 1 ? 0.4 : 1, cursor: filters.page <= 1 ? "default" : "pointer" }}><ChevronLeft size={14} color={C.slate} /></button>
        <span style={{ fontSize: 12, color: C.mute }}>
          <b style={{ color: C.text, fontFamily: MONO }}>{fmtNum(filteredTotal)}</b> {anyFilter ? "match" : "loans"} · page {filters.page} of {fmtNum(pageCount)}
        </span>
        <button onClick={() => setFilters((f) => ({ ...f, page: Math.min(pageCount, f.page + 1) }))} disabled={filters.page >= pageCount} style={{ ...pageBtn, opacity: filters.page >= pageCount ? 0.4 : 1, cursor: filters.page >= pageCount ? "default" : "pointer" }}><ChevronRight size={14} color={C.slate} /></button>
      </div>
    </Card>
  );
}
function MiniStat({ label, value, color, divider }) {
  return (<div style={{ padding: "13px 14px", borderLeft: divider ? `1px solid ${C.line}` : "none" }}><div style={{ fontSize: 10.5, color: C.mute, fontWeight: 600 }}>{label}</div><div style={{ fontFamily: MONO, fontSize: 17, fontWeight: 700, color, marginTop: 3 }}>{fmtNum(value)}</div></div>);
}

function BatchBar({ count, matchTotal, onSelectAllMatch, onClear, onAccept, onIgnore, busy }) {
  if (count === 0) return null;
  return (
    <div style={{ ...row(12, { flexWrap: "wrap" }), background: C.ink, borderRadius: 12, padding: "12px 16px", marginBottom: 14 }}>
      <div style={{ ...row(9) }}>
        <span style={{ fontFamily: MONO, fontSize: 15, fontWeight: 800, color: C.amber }}>{fmtNum(count)}</span>
        <span style={{ fontSize: 13, color: "#fff", fontWeight: 600 }}>selected</span>
        {matchTotal > count && (
          <button onClick={onSelectAllMatch} style={{ background: "none", border: "none", color: C.cyan, fontFamily: FONT, fontSize: 12.5, fontWeight: 600, cursor: "pointer", padding: 0 }}>
            Select all {fmtNum(matchTotal)} matching
          </button>
        )}
      </div>
      <div style={{ ...row(9), marginLeft: "auto" }}>
        <span style={{ fontSize: 11.5, color: C.railMute }}>Apply each loan's own suggestion · re-checked through OPA</span>
        <button disabled={busy} onClick={onIgnore} style={{ ...row(6), background: "transparent", border: `1px solid rgba(255,255,255,0.25)`, borderRadius: 8, padding: "8px 14px", color: "#fff", fontFamily: FONT, fontSize: 13, fontWeight: 700, cursor: busy ? "default" : "pointer", opacity: busy ? 0.6 : 1 }}><X size={14} /> Ignore selected</button>
        <button disabled={busy} onClick={onAccept} style={{ ...row(6), background: C.green, border: `1px solid ${C.green}`, borderRadius: 8, padding: "8px 14px", color: "#fff", fontFamily: FONT, fontSize: 13, fontWeight: 700, cursor: busy ? "default" : "pointer", opacity: busy ? 0.6 : 1 }}><Check size={14} /> Accept selected</button>
        <button onClick={onClear} title="Clear selection" style={{ ...row(0, { justifyContent: "center" }), width: 34, height: 34, background: "transparent", border: `1px solid rgba(255,255,255,0.25)`, borderRadius: 8, color: C.railMute, cursor: "pointer" }}><RotateCcw size={15} /></button>
      </div>
    </div>
  );
}

// The human-review gate for a Rule 3 batch accept: shows exactly which
// substitute asset the LLM picked for each loan (or an honest dead-end)
// BEFORE anything is applied - a separate, explicit "Confirm & apply" click
// is required. Never generate-and-apply a batch of LLM picks in one call.
function BatchReviewPanel({ batchReview, onConfirm, onCancel, busy }) {
  if (!batchReview) return null;
  const { results } = batchReview;
  const okCount = results.filter((r) => r.has_candidate && !r.error).length;
  return (
    <div style={{ background: C.card, border: `1px solid ${C.coral}55`, borderRadius: 12, padding: 16, marginBottom: 14 }}>
      <div style={{ ...row(9), marginBottom: 4 }}>
        <Sparkles size={16} color={C.coral} />
        <span style={{ fontSize: 13.5, fontWeight: 700, color: C.text }}>Review AI-suggested substitute assets before applying</span>
      </div>
      <div style={{ fontSize: 11.5, color: C.mute, marginBottom: 11 }}>
        {fmtNum(okCount)} of {fmtNum(results.length)} have a qualifying substitute · nothing has been applied yet.
      </div>
      <div style={{ maxHeight: 260, overflowY: "auto", border: `1px solid ${C.line}`, borderRadius: 9 }}>
        {results.map((r, i) => (
          <div key={r.loan_id || i} style={{ padding: "9px 12px", borderTop: i ? `1px solid ${C.line}` : "none", ...row(9) }}>
            <span style={{ fontFamily: MONO, fontSize: 12, fontWeight: 700, color: C.text, minWidth: 70 }}>{r.loan_id}</span>
            {r.error ? (
              <span style={{ fontSize: 12, color: C.coralDark }}>{r.error}</span>
            ) : r.has_candidate ? (
              <>
                <span style={{ fontSize: 12, color: C.slate, flex: 1 }}>{r.suggestion_text}</span>
                {r.confidence != null && <span style={{ fontFamily: MONO, fontSize: 10.5, fontWeight: 700, color: C.green, background: C.greenSoft, padding: "1px 6px", borderRadius: 4 }}>{Math.round(r.confidence)}%</span>}
              </>
            ) : (
              <span style={{ fontSize: 12, color: C.coralDark }}>No qualifying asset — will be skipped</span>
            )}
          </div>
        ))}
      </div>
      <div style={{ ...row(9), marginTop: 12 }}>
        <DecisionBtn tone="green" icon={<Check size={15} />} title="Confirm & apply" disabled={busy} onClick={onConfirm} />
        <DecisionBtn tone="ghost" icon={<X size={15} />} title="Cancel" disabled={busy} onClick={onCancel} />
      </div>
    </div>
  );
}

function renderHighlighted(snippet, highlight) {
  if (!snippet) return null;
  if (!highlight || !snippet.includes(highlight)) return snippet;
  const idx = snippet.indexOf(highlight);
  return (
    <>
      {snippet.slice(0, idx)}
      <mark style={{ background: C.yellowHl, color: C.text, padding: "1px 3px", borderRadius: 3, fontStyle: "normal", fontWeight: 600 }}>{highlight}</mark>
      {snippet.slice(idx + highlight.length)}
    </>
  );
}

// Full, honest, rule-aware explanation of why this loan is queued here — never a
// terse label. Reflects the same precedence facts the Impact panel shows (a
// currency fix is R3-invariant; it may or may not rescue R1 depending on the
// EUR conversion), so the two panels never contradict each other.
function failureBanner(loan) {
  const also = loan.also_fails || [];
  if (loan.rule_failed === 2) {
    let s = `Rule 2 · currency mismatch. Reported in ${loan.ccy}, expected ${loan.fix?.to || "a different currency"}.`;
    if (also.includes(1)) s += ` Also fails Rule 1 — correcting the currency changes the EUR value, so it may pass eligibility on re-check.`;
    if (also.includes(3)) s += ` Also fails Rule 3 — a currency fix won't resolve that, so it moves to Collateral after re-check.`;
    return s;
  }
  if (loan.rule_failed === 1) {
    let s = `Rule 1 · loan value falls below the €25,000 minimum after FX conversion.`;
    if (also.length) s += ` This loan also fails Rule ${also.join(", ")} — that will still need its own review after this decision.`;
    return s;
  }
  if (loan.rule_failed === 3) {
    let s = `Rule 3 · pledged asset covers less than 50% of the loan.`;
    if (also.length) s += ` This loan also fails Rule ${also.join(", ")} — that will still need its own review after this decision.`;
    return s;
  }
  return "No suggestion available.";
}

// Shared evidence-card shell so the header (icon + title + meta + right-side
// action/badge) looks identical across all three rules — only the body content
// (PDF snippet vs FX math vs pledged-asset note) differs per rule.
function EvidenceCard({ icon, title, meta, right, children }) {
  return (
    <div style={{ padding: "14px 18px", borderTop: `1px solid ${C.line}`, background: C.paper }}>
      <div style={{ ...row(0, { justifyContent: "space-between" }), marginBottom: 10 }}>
        <div style={{ ...row(8) }}>
          {icon}
          <span style={sectionTitle}>{title}</span>
          {meta}
        </div>
        {right}
      </div>
      {children}
    </div>
  );
}
const OpenPdfBtn = ({ page }) => (
  <a href={`/api/assets/company-reference.pdf${page ? `#page=${page}` : ""}`} target="_blank" rel="noreferrer" style={{ ...row(5), background: C.card, border: `1px solid ${C.lineStrong}`, borderRadius: 8, padding: "6px 11px", fontFamily: FONT, fontSize: 12, fontWeight: 600, color: C.slate, textDecoration: "none" }}>Open PDF <ExternalLink size={12} /></a>
);

// === RULE 2 — Currency Validation ===
function Rule2Body({ loan }) {
  return (
    <>
      <div style={{ padding: "0 18px 18px", display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12 }}>
        <div>
          <Label>From CSV</Label>
          <div style={{ fontFamily: MONO, fontSize: 15, fontWeight: 700, color: C.text, marginTop: 5 }}>{loan.ccy}</div>
          <div style={{ fontSize: 11.5, color: C.slate, marginTop: 2 }}>{loan.hq}</div>
        </div>
        <div>
          <Label>From PDF</Label>
          <div style={{ fontSize: 11.5, color: C.slate, marginTop: 5 }}>{loan.hq}</div>
          <div style={{ fontFamily: MONO, fontSize: 15, fontWeight: 700, color: C.text, marginTop: 2 }}>{loan.fix?.to}</div>
        </div>
        <div>
          <Label>AI suggested fix</Label>
          <div style={{ ...row(6), marginTop: 5 }}>
            <span style={{ fontFamily: MONO, fontSize: 14, fontWeight: 700, color: C.text }}>{loan.fix?.from}</span>
            <ArrowRight size={13} color={C.green} />
            <span style={{ fontFamily: MONO, fontSize: 14, fontWeight: 800, color: C.green }}>{loan.fix?.to}</span>
          </div>
        </div>
      </div>
      {loan.evidence && (
        <EvidenceCard
          icon={<FileText size={14} color={C.slate} />}
          title="PDF evidence"
          meta={<>
            <span style={{ fontFamily: MONO, fontSize: 12, color: C.slate }}>company-reference.pdf</span>
            {loan.evidence.pdfPage != null && <span style={{ fontFamily: MONO, fontSize: 10.5, color: C.coralDark, background: C.coralSoft, padding: "2px 7px", borderRadius: 4, fontWeight: 700 }}>p.{loan.evidence.pdfPage}{loan.evidence.pdfTotal ? ` of ${loan.evidence.pdfTotal}` : ""}</span>}
          </>}
          right={<OpenPdfBtn page={loan.evidence.pdfPage} />}
        >
          <div style={{ background: C.card, border: `1px solid ${C.line}`, borderRadius: 8, padding: "11px 13px", fontSize: 12.5, color: C.slate, lineHeight: 1.55, fontStyle: "italic" }}>
            “{renderHighlighted(loan.evidence.snippet, loan.evidence.highlight)}”
          </div>
        </EvidenceCard>
      )}
    </>
  );
}

// === RULE 1 — Loan Eligibility ===
function Rule1Body({ loan }) {
  return (
    <>
      <div style={{ padding: "0 18px 18px" }}>
        <Label>Suggested action</Label>
        <div style={{ fontSize: 14, fontWeight: 600, color: C.text, marginTop: 4 }}>Remove this loan — value falls below the €25,000 minimum after FX conversion.</div>
      </div>
      {loan.impact?.fx && (
        <EvidenceCard
          icon={<RefreshCw size={14} color={C.slate} />}
          title="FX evidence"
          right={<span style={{ fontFamily: MONO, fontSize: 10.5, color: loan.impact.fx.stale ? "#fff" : C.green, background: loan.impact.fx.stale ? C.r1 : C.greenSoft, padding: "2px 7px", borderRadius: 4, fontWeight: 800 }}>{loan.impact.fx.stale ? "STALE" : "FRESH"}</span>}
        >
          <div style={{ background: C.card, border: `1px solid ${C.line}`, borderRadius: 8, padding: "11px 13px", fontSize: 12.5, color: C.slate, lineHeight: 1.6 }}>
            <div style={{ fontFamily: MONO, color: C.text }}>
              {fmtMoney(loan.valueNum)} {loan.impact.fx.currency} × {loan.impact.fx.rate_to_eur?.toFixed(4)} = <b>€{fmtMoney(loan.impact.fx.converted_eur)}</b>
            </div>
            <div style={{ marginTop: 6, color: C.mute }}>source: {loan.impact.fx.source} · as of {loan.impact.fx.as_of}</div>
          </div>
        </EvidenceCard>
      )}
    </>
  );
}

// === RULE 3 — Collateral Review ===
function Rule3Body({ loan, selectedAsset, onSelectAsset, picking, onToggleManual, onApply, onReload }) {
  const assets = loan.assets;
  const hasFix = loan.fix?.type === "substitute_asset";
  const pledgedEntry = (assets || []).find((a) => a.current);
  const viaBadge = loan.via === "llm"
    ? <span style={{ fontFamily: MONO, fontSize: 10.5, fontWeight: 800, color: C.green, background: C.greenSoft, padding: "2px 7px", borderRadius: 4 }}>{loan.confidence != null ? `${Math.round(loan.confidence)}% CONF` : "LLM"}</span>
    : loan.via === "fallback"
      ? <span title="LLM unavailable — deterministic best-fit used" style={{ fontFamily: MONO, fontSize: 10.5, fontWeight: 800, color: C.slate, background: C.paper, border: `1px solid ${C.line}`, padding: "2px 7px", borderRadius: 4 }}>AUTO-SELECTED</span>
      : null;
  return (
    <>
      <div style={{ padding: "0 18px 18px", ...col(12) }}>
        {loan.pledged && (
          <div>
            <Label>Pledged asset</Label>
            <div style={{ fontSize: 14, fontWeight: 600, color: C.text, marginTop: 4 }}>{loan.pledged.description} — {fmtMoney(loan.pledged.value)} {loan.ccy}</div>
          </div>
        )}
        {hasFix ? (
          <div>
            <div style={{ ...row(7) }}><Label>Suggested substitute asset</Label>{viaBadge}</div>
            <div style={{ fontSize: 14, fontWeight: 600, color: C.text, marginTop: 4 }}>{loan.fix.asset_description} — {fmtMoney(loan.fix.asset_value)} {loan.ccy}</div>
            <div style={{ fontSize: 12.5, fontWeight: 700, color: C.green, marginTop: 6 }}>Clears 50% of {fmtMoney(loan.valueNum)} {loan.ccy} → pass</div>
            {loan.via === "llm" && loan.reasoning && (
              <div style={{ fontSize: 12, color: C.slate, marginTop: 8, fontStyle: "italic" }}>“{loan.reasoning}”</div>
            )}
          </div>
        ) : !loan.computed ? (
          <div style={{ ...row(9), background: C.paper, border: `1px solid ${C.line}`, borderRadius: 9, padding: "10px 13px" }}>
            <Loader2 size={14} color={C.mute} className="spin" />
            <div style={{ fontSize: 12.5, color: C.slate }}>Computing a substitute-asset suggestion for this loan…</div>
          </div>
        ) : (
          <div style={{ background: C.coralSoft, border: `1px solid ${C.coral}44`, borderRadius: 9, padding: "10px 13px" }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: C.coralDark }}>No asset in this company's catalog clears 50% coverage.</div>
            <div style={{ fontSize: 12, color: C.slate, marginTop: 3 }}>This loan has no adequate collateral available — remove it from the report or ignore as a reviewed exception.</div>
          </div>
        )}
        {picking && (
          <AssetPicker
            loan={loan} selectedAsset={selectedAsset} onSelectAsset={onSelectAsset}
            onApply={onApply}
            onCancel={onToggleManual}
            onReload={onReload}
          />
        )}
      </div>
      <EvidenceCard
        icon={<FileText size={14} color={C.slate} />}
        title="PDF evidence"
        meta={<>
          <span style={{ fontFamily: MONO, fontSize: 12, color: C.slate }}>company-reference.pdf</span>
          {pledgedEntry?.pdfPage != null && <span style={{ fontFamily: MONO, fontSize: 10.5, color: C.coralDark, background: C.coralSoft, padding: "2px 7px", borderRadius: 4, fontWeight: 700 }}>p.{pledgedEntry.pdfPage}</span>}
        </>}
        right={<OpenPdfBtn page={pledgedEntry?.pdfPage} />}
      >
        <div style={{ fontSize: 12.5, color: C.slate, lineHeight: 1.55 }}>Open the company reference document to review the full pledged-asset list.</div>
      </EvidenceCard>
    </>
  );
}

// Real asset-picker revealed by "Fix manually" - lists the company's actual
// pledgeable assets (loan.assets, sourced server-side from the same
// retrieve_company_assets the R3 agent itself uses), each with a real PDF
// page reference. Never renders a blank/fabricated list: an explicit
// loading state when loan.assets hasn't arrived yet, and an explicit
// "nothing to show" state (with a reload action) when it's genuinely empty.
function AssetPicker({ loan, selectedAsset, onSelectAsset, onApply, onCancel, onReload }) {
  const assets = loan.assets;
  if (assets == null) {
    return (
      <div style={{ background: C.paper, border: `1px solid ${C.lineStrong}`, borderRadius: 10, padding: 14, marginTop: 4 }}>
        <div style={{ ...row(8) }}><Loader2 size={14} className="spin" color={C.mute} /><span style={{ fontSize: 12.5, color: C.slate }}>Loading assets from company-reference.pdf…</span></div>
      </div>
    );
  }
  if (assets.length === 0) {
    return (
      <div style={{ background: C.paper, border: `1px solid ${C.lineStrong}`, borderRadius: 10, padding: 14, marginTop: 4 }}>
        <div style={{ fontSize: 12.5, color: C.slate, marginBottom: 8 }}>Asset catalog not loaded for {loan.co}. Fetch it from the reference document.</div>
        <button onClick={onReload} style={{ ...row(6), background: C.card, border: `1px solid ${C.lineStrong}`, borderRadius: 8, padding: "7px 12px", fontFamily: FONT, fontSize: 12.5, fontWeight: 600, color: C.text, cursor: "pointer" }}>
          <RefreshCw size={13} /> Load assets
        </button>
      </div>
    );
  }
  const sel = (selectedAsset && assets.find((a) => a.name === selectedAsset.name)) || null;
  return (
    <div style={{ background: C.paper, border: `1px solid ${C.lineStrong}`, borderRadius: 10, padding: 14, marginTop: 4 }}>
      <div style={{ ...row(0, { justifyContent: "space-between" }), marginBottom: 10 }}>
        <Label>Choose a substitute asset</Label>
        <span style={{ fontSize: 11, color: C.mute }}>50% threshold = {fmtMoney(loan.valueNum * 0.5)} {loan.ccy}</span>
      </div>
      <div style={{ ...col(7) }}>
        {assets.map((a) => {
          const isSel = sel && a.name === sel.name;
          const disabled = !a.qualifies;
          return (
            <div key={a.name} style={{ ...row(10), background: isSel ? C.greenSoft : C.card, border: `1px solid ${isSel ? C.greenBright : C.line}`, borderRadius: 8, padding: "10px 12px", opacity: disabled ? 0.55 : 1 }}>
              <button disabled={disabled} onClick={() => !disabled && onSelectAsset(a)} style={{ all: "unset", cursor: disabled ? "not-allowed" : "pointer", ...row(10), flex: 1, minWidth: 0 }}>
                <div style={{ width: 16, height: 16, borderRadius: 16, border: `2px solid ${isSel ? C.green : C.lineStrong}`, background: isSel ? C.green : "transparent", flexShrink: 0, ...row(0, { justifyContent: "center" }) }}>
                  {isSel && <Check size={10} color="#fff" strokeWidth={3} />}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ ...row(7) }}>
                    <span style={{ fontSize: 13, fontWeight: 600, color: C.text }}>{a.name}</span>
                    {a.current && <span style={{ fontSize: 9.5, fontWeight: 700, color: C.mute, background: C.paper, border: `1px solid ${C.line}`, padding: "1px 5px", borderRadius: 4 }}>CURRENT</span>}
                    {loan.fix?.asset_description === a.name && <span style={{ ...row(3), fontSize: 9.5, fontWeight: 800, color: C.r3, background: C.r3s, padding: "1px 5px", borderRadius: 4 }}><Sparkles size={9} /> AI PICK</span>}
                  </div>
                  <div style={{ fontFamily: MONO, fontSize: 12, color: C.slate, marginTop: 2 }}>{fmtMoney(a.value)} {loan.ccy} · {(a.coverage * 100).toFixed(0)}% coverage</div>
                </div>
              </button>
              {a.pdfPage != null && (
                <a href={`/api/assets/company-reference.pdf#page=${a.pdfPage}`} target="_blank" rel="noreferrer" style={{ fontFamily: MONO, fontSize: 10.5, fontWeight: 700, color: C.coralDark, background: C.coralSoft, padding: "2px 7px", borderRadius: 4, textDecoration: "none", flexShrink: 0 }}>p.{a.pdfPage}</a>
              )}
              <span style={{ fontSize: 10.5, fontWeight: 700, padding: "2px 7px", borderRadius: 4, whiteSpace: "nowrap", background: a.qualifies ? C.greenSoft : C.coralSoft, color: a.qualifies ? C.green : C.coralDark, flexShrink: 0 }}>
                {a.qualifies ? "✓ clears 50%" : "✗ below 50%"}
              </span>
            </div>
          );
        })}
      </div>
      {sel && (
        <div style={{ ...row(8), marginTop: 11, padding: "9px 12px", background: C.greenSoft, borderRadius: 8, fontFamily: MONO, fontSize: 12.5, color: C.text }}>
          <CircleCheck size={14} color={C.green} />
          {fmtMoney(sel.value)} {loan.ccy} = {(sel.coverage * 100).toFixed(0)}% of loan <b style={{ color: C.green }}>→ pass</b>
        </div>
      )}
      <div style={{ ...row(9), marginTop: 12 }}>
        <DecisionBtn tone="green" icon={<Check size={14} />} title="Apply this asset" disabled={!sel} onClick={onApply} />
        <DecisionBtn tone="ghost" icon={<X size={14} />} title="Cancel" disabled={false} onClick={onCancel} />
      </div>
    </div>
  );
}

function Detail({ loan, index, stageTotal, selectedAsset, onSelectAsset, picking, onToggleManual, onReload }) {
  if (!loan) {
    return <Card style={{ padding: 32, textAlign: "center", color: C.mute, fontSize: 13 }}>Select a loan from the queue to review it.</Card>;
  }
  return (
    <Card style={{ padding: 0, overflow: "hidden" }}>
      <div style={{ ...row(0, { justifyContent: "space-between" }), padding: "11px 18px", borderBottom: `1px solid ${C.line}`, background: C.paper }}>
        <span style={{ fontSize: 12.5, color: C.mute }}>Loan {Math.max(index ?? 0, 0) + 1} of {fmtNum(stageTotal)}</span>
        <Tag rule={loan.rule_failed} />
      </div>
      <div style={{ padding: 18 }}>
        <div style={{ ...row(13), alignItems: "flex-start" }}>
          <div style={{ width: 46, height: 46, borderRadius: 11, background: C.paper, border: `1px solid ${C.line}`, ...row(0, { justifyContent: "center" }), flexShrink: 0 }}><Building2 size={21} color={C.slate} /></div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontFamily: MONO, fontSize: 18, fontWeight: 800, color: C.ink }}>{loan.id}</div>
            <div style={{ fontSize: 13, color: C.slate, marginTop: 1 }}>{loan.co}</div>
            {loan.industry && <div style={{ display: "inline-block", background: C.paper, border: `1px solid ${C.line}`, borderRadius: 6, padding: "2px 8px", fontSize: 11.5, color: C.slate, marginTop: 7 }}>{loan.industry}</div>}
          </div>
          <div style={{ textAlign: "right" }}><Label>Loan amount</Label><div style={{ marginTop: 5 }}><span style={{ fontFamily: MONO, fontSize: 19, fontWeight: 800, color: C.ink }}>{fmtMoney(loan.valueNum)}</span> <span style={{ fontSize: 12.5, color: C.slate }}>{loan.ccy}</span></div></div>
          {loan.confidence != null && (
            <div style={{ textAlign: "right", minWidth: 96 }}><Label>AI confidence</Label><div style={{ ...row(7, { justifyContent: "flex-end" }), marginTop: 5 }}><span style={{ fontFamily: MONO, fontSize: 19, fontWeight: 800, color: C.green }}>{Math.round(loan.confidence)}%</span><ConfidenceRing pct={loan.confidence} /></div></div>
          )}
        </div>
      </div>
      <div style={{ margin: "0 18px 16px", ...row(9), background: RULE[loan.rule_failed].s, border: `1px solid ${RULE[loan.rule_failed].c}`, borderRadius: 10, padding: "11px 14px" }}>
        <CircleAlert size={16} color={RULE[loan.rule_failed].c} style={{ flexShrink: 0 }} />
        <div style={{ fontSize: 13, color: C.slate, lineHeight: 1.5 }}>{failureBanner(loan)}</div>
      </div>
      {loan.rule_failed === 2 && <Rule2Body loan={loan} />}
      {loan.rule_failed === 1 && <Rule1Body loan={loan} />}
      {loan.rule_failed === 3 && <Rule3Body loan={loan} selectedAsset={selectedAsset} onSelectAsset={onSelectAsset} picking={picking} onToggleManual={onToggleManual} onReload={onReload} />}
    </Card>
  );
}
function ConfidenceRing({ pct }) {
  const r = 11, circ = 2 * Math.PI * r;
  return (<svg width={28} height={28}><circle cx={14} cy={14} r={r} fill="none" stroke={C.line} strokeWidth={3} /><circle cx={14} cy={14} r={r} fill="none" stroke={C.green} strokeWidth={3} strokeLinecap="round" strokeDasharray={circ} strokeDashoffset={circ * (1 - pct / 100)} transform="rotate(-90 14 14)" /></svg>);
}

function Impact({ loan }) {
  if (!loan) return null;
  const rule1Step = loan.rule_failed === 1
    ? { icon: <Dot color={C.green} solid />, title: <>Loan eligibility <span style={{ color: C.mute, fontWeight: 500 }}>· R1</span></>, body: "Fix applied here" }
    : loan.also_fails?.includes(1)
      ? { icon: <Dot color={C.r2} />, title: <>Loan eligibility <span style={{ color: C.mute, fontWeight: 500 }}>· R1</span></>, body: <span style={{ color: C.r2, fontWeight: 600 }}>May flip to pass — EUR value changes with the currency label</span> }
      : null;
  return (
    <Card style={{ padding: 18, alignSelf: "start" }}>
      <div style={sectionTitle}>Impact of accepting the fix</div>
      <div style={{ fontSize: 11.5, color: C.mute, marginTop: 4, lineHeight: 1.5 }}>OPA re-checks all three rules. Only downstream decisions can move.</div>
      <div style={{ marginTop: 15 }}>
        {loan.rule_failed === 2 && <ImpactStep icon={<Dot color={C.green} solid />} title={<>Currency <span style={{ color: C.mute, fontWeight: 500 }}>· R2</span></>} body={`Corrected to ${loan.fix?.to || "the expected currency"} — fix applied here`} line />}
        {rule1Step && <ImpactStep {...rule1Step} line />}
        <ImpactStep icon={<Dot color={C.mute} />} title={<>Collateral <span style={{ color: C.mute, fontWeight: 500 }}>· R3</span></>} body={loan.rule_failed === 3 ? "Fix applied here" : <>Currency-invariant — <b>cannot change</b> from a currency fix</>} />
      </div>
      {loan.impact?.fx && (
        <>
          <div style={{ height: 1, background: C.line, margin: "16px 0" }} />
          <div style={{ ...row(7), marginBottom: 11 }}><Tag rule={1} /><span style={sectionTitle}>The €25,000 check</span></div>
          <div style={{ background: loan.impact.fx.stale ? C.r1s : C.paper, border: `1px solid ${loan.impact.fx.stale ? C.r1 : C.line}`, borderRadius: 9, padding: 12 }}>
            <div style={{ ...row(6), marginBottom: 7 }}><RefreshCw size={12} color={C.slate} /><Label>As reported ({loan.impact.fx.currency})</Label></div>
            <div style={{ fontFamily: MONO, fontSize: 12.5, color: C.text, lineHeight: 1.5 }}>
              = <b>€{fmtMoney(loan.impact.fx.converted_eur)}</b>{" "}
              <span style={{ color: loan.impact.fx.converted_eur < 25000 ? C.r3 : C.green, fontWeight: 700 }}>
                {loan.impact.fx.converted_eur < 25000 ? "< €25,000 · fail" : "≥ €25,000 · pass"}
              </span>
            </div>
            <div style={{ fontSize: 10.5, color: C.mute, marginTop: 6 }}>{loan.impact.fx.source} · {loan.impact.fx.as_of}</div>
          </div>
        </>
      )}
    </Card>
  );
}
function Dot({ color, solid }) { return <div style={{ width: 20, height: 20, borderRadius: 20, background: solid ? color : color + "22", border: `1.5px solid ${color}`, ...row(0, { justifyContent: "center" }), flexShrink: 0 }}>{solid && <Check size={12} color="#fff" strokeWidth={3} />}</div>; }
function ImpactStep({ icon, title, body, line }) {
  return (<div style={{ ...row(11), alignItems: "stretch" }}><div style={{ ...col(0, { alignItems: "center" }) }}>{icon}{line && <div style={{ width: 1.5, flex: 1, background: C.line, marginTop: 3, minHeight: 20 }} />}</div><div style={{ paddingBottom: line ? 14 : 0 }}><div style={{ fontSize: 13, fontWeight: 700, color: C.text }}>{title}</div><div style={{ fontSize: 11.5, color: C.slate, marginTop: 2, lineHeight: 1.45 }}>{body}</div></div></div>);
}

function DecisionBar({ loan, onDecide, busy, acceptDisabled, showRemove, picking, onToggleManual }) {
  if (!loan) return null;
  const isR3 = loan.rule_failed === 3;
  return (
    <Card style={{ padding: 14 }}>
      <div style={{ ...row(11, { flexWrap: "wrap" }) }}>
        <span style={{ ...sectionTitle, marginRight: 2 }}>Your decision</span>
        {!showRemove && <DecisionBtn tone="green" icon={<Check size={15} />} title="Accept" disabled={busy || acceptDisabled} onClick={() => onDecide("accept")} />}
        <DecisionBtn
          tone={isR3 && picking ? "active" : "ghost"}
          icon={<Pencil size={15} />} title="Fix manually" disabled={busy}
          onClick={isR3 ? onToggleManual : () => onDecide("manual")}
        />
        {showRemove && <DecisionBtn tone="ghost" icon={<Trash2 size={15} />} title="Remove from report" disabled={busy} onClick={() => onDecide("remove")} />}
        <DecisionBtn tone="red" icon={<X size={15} />} title="Ignore" disabled={busy} onClick={() => onDecide("ignore")} />
      </div>
      {showRemove && <div style={{ fontSize: 11.5, color: C.mute, marginTop: 10 }}>No qualifying collateral — removal keeps the report honest; ignore marks it a reviewed exception.</div>}
    </Card>
  );
}
function DecisionBtn({ tone, icon, title, onClick, disabled }) {
  const map = {
    green: { bg: C.greenSoft, fg: C.green, border: C.greenBright + "66" },
    ghost: { bg: "#fff", fg: C.text, border: C.lineStrong },
    active: { bg: C.coralSoft, fg: C.coralDark, border: C.coral + "66" },
    red: { bg: C.coralSoft, fg: C.coralDark, border: C.coral + "44" },
  }[tone];
  return (<button onClick={onClick} disabled={disabled} style={{ ...row(7), background: map.bg, border: `1px solid ${map.border}`, borderRadius: 9, padding: "9px 15px", cursor: disabled ? "default" : "pointer", opacity: disabled ? 0.6 : 1, fontFamily: FONT, color: map.fg, fontSize: 13, fontWeight: 700, whiteSpace: "nowrap" }}>{icon} {title}</button>);
}

const OUTER_NAV = [
  { id: "dashboard", label: "Dashboard", icon: LayoutDashboard },
  { id: "review", label: "Review", icon: ClipboardCheck },
  { id: "insights", label: "Insights", icon: BarChart3 },
  { id: "compliance", label: "Compliance", icon: ShieldCheck },
  { id: "history", label: "History", icon: FileText },
];

export function Review({ setTab, onRefresh }) {
  const [stages, setStages] = useState([]);
  const [activeRule, setActiveRule] = useState(null);
  const [summary, setSummary] = useState({ suggested: 0, needsReview: 0, ignored: 0 });
  const [overall, setOverall] = useState({ reviewed: 0, total: 0 });
  const [loans, setLoans] = useState([]);
  const [filteredTotal, setFilteredTotal] = useState(0);
  const [stageTotal, setStageTotal] = useState(0);
  const [queueLoading, setQueueLoading] = useState(false);
  const [pick, setPick] = useState(null);
  const [loan, setLoan] = useState(null);
  const [sel, setSel] = useState(new Set());
  const [selectAllMatching, setSelectAllMatching] = useState(false);
  const [toast, setToast] = useState(null);
  const [filters, setFilters] = useState({ ccy: "All", min: "", max: "", lowConf: false, q: "", sort: "value_desc", page: 1 });
  const [busy, setBusy] = useState(false);
  const [runFx, setRunFx] = useState(null); // per-run FX provenance fallback (existing /api/history endpoint)
  const [batchReview, setBatchReview] = useState(null); // R3 bulk-accept: generated picks awaiting confirmation
  const [selectedAsset, setSelectedAsset] = useState(null); // R3 asset-picker selection (real assets from loan.assets)
  const [picking, setPicking] = useState(false); // R3 "Fix manually" picker toggle

  const loadStages = async () => {
    const data = await getJSON("/api/review/stages");
    setStages(data.stages);
    setActiveRule((cur) => cur ?? (data.stages.find((s) => s.queue > 0) || data.stages[0])?.rule ?? null);
  };

  const loadRunFx = async () => {
    try {
      const h = await getJSON("/api/history");
      const run = h.runs?.[0];
      if (run) setRunFx({ source: run.fx_source, as_of: run.fx_rate_date, stale: !!run.fx_stale });
    } catch {
      // non-critical fallback display only — leave runFx null on failure
    }
  };

  const loadSummaryAndOverall = async (rule) => {
    if (rule == null) return;
    const data = await getJSON(`/api/review/summary?rule=${rule}`);
    setSummary(data.queue);
    setOverall(data.overall);
  };

  const loadQueue = async () => {
    if (activeRule == null) return;
    setQueueLoading(true);
    try {
      const params = new URLSearchParams({
        bucket: String(activeRule),
        limit: String(PER_PAGE),
        offset: String((filters.page - 1) * PER_PAGE),
        sort: filters.sort,
      });
      if (filters.ccy !== "All") params.set("ccy", filters.ccy);
      if (filters.min) params.set("min_value", filters.min);
      if (filters.max) params.set("max_value", filters.max);
      if (filters.lowConf) params.set("low_conf", "true");
      if (filters.q) params.set("q", filters.q);
      const data = await getJSON(`/api/review/loans?${params.toString()}`);
      setLoans(data.loans.map((l) => ({
        id: l.loan_id, co: l.company_name,
        value: fmtMoney(l.loan_value),
        num: Number(l.loan_value), ccy: l.loan_currency,
        risk: riskFor(l), conf: l.confidence != null ? Math.round(l.confidence) : null,
        alsoFails: [1, 2, 3].filter((r) => r !== activeRule && !l[`rule${r}_pass`]),
        pledged: l.asset_description ? { description: l.asset_description, value: Number(l.asset_value) } : null,
      })));
      setFilteredTotal(data.filtered_total);
      setStageTotal(data.total);
    } finally {
      setQueueLoading(false);
    }
  };

  const openLoan = async (loanId) => {
    setPick(loanId);
    let detail = await getJSON(`/api/review/loan/${loanId}`);
    // Rule 3 suggestions are lazy - generate the REAL suggestion (via the
    // actual LLM + this company's real asset catalog) up front, then
    // re-fetch so the panel only ever shows genuine data, never a mock.
    if (detail.rule_failed === 3 && detail.fix?.type !== "substitute_asset") {
      try {
        await postJSON(`/api/review/${loanId}/rule3/generate`, {});
        detail = await getJSON(`/api/review/loan/${loanId}`);
      } catch (e) {
        console.error("rule3 generate failed:", e);
      }
    }
    const row = loans.find((l) => l.id === loanId);
    setLoan({ ...detail, pledged: row?.pledged || null });
  };

  useEffect(() => { loadStages(); loadRunFx(); }, []);
  useEffect(() => {
    if (loan?.rule_failed === 3 && loan.fix?.type === "substitute_asset") {
      const assets = loan.assets || [];
      const def = assets.find((a) => a.name === loan.fix.asset_description)
        || assets.filter((a) => a.qualifies && !a.current).sort((a, b) => a.value - b.value)[0]
        || null;
      setSelectedAsset(def);
    } else {
      setSelectedAsset(null);
    }
  }, [loan?.id]);
  useEffect(() => { setPicking(false); }, [loan?.id]);
  useEffect(() => {
    if (activeRule == null) return;
    setFilters((f) => ({ ...f, page: 1 }));
    setSel(new Set());
    setSelectAllMatching(false);
    setLoan(null);
    setPick(null);
    loadSummaryAndOverall(activeRule);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeRule]);
  useEffect(() => {
    loadQueue();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeRule, filters.ccy, filters.min, filters.max, filters.lowConf, filters.q, filters.sort, filters.page]);

  const refreshAfterChange = async () => {
    await Promise.all([loadStages(), loadSummaryAndOverall(activeRule), loadQueue()]);
    if (onRefresh) await onRefresh();
  };

  const decide = async (action) => {
    if (!loan) return;
    setBusy(true);
    try {
      const rule = loan.rule_failed;
      if (rule === 1) {
        await postJSON(`/api/review/${loan.id}/rule1/decide`, { decision: action === "manual" ? "accept" : action });
      } else if (rule === 2) {
        let manual_currency;
        if (action === "manual") {
          manual_currency = window.prompt("Correct currency code (e.g. EUR):");
          if (!manual_currency) { setBusy(false); return; }
        }
        await postJSON(`/api/review/${loan.id}/rule2/decide`, { decision: action, manual_currency });
      } else if (rule === 3) {
        let manual_asset;
        if (action === "manual") {
          // The picker (not window.prompt) already put a real, qualifying
          // asset into selectedAsset - Fix-manually just applies that.
          if (!selectedAsset) { setBusy(false); return; }
          manual_asset = { asset_description: selectedAsset.name, asset_value: selectedAsset.value };
        }
        // Plain "accept" sends no manual_asset - the backend applies the
        // REAL suggestion already generated (and paused) when this loan
        // was opened via openLoan()'s /rule3/generate call above.
        await postJSON(`/api/review/${loan.id}/rule3/decide`, { decision: action, manual_asset });
      }
      setToast({ text: `${loan.id}: ${action} applied — re-checked through OPA`, type: "success" });
      setLoan(null);
      setPick(null);
      await refreshAfterChange();
    } catch (e) {
      console.error("decide failed:", e);
      setToast({ text: `Failed to apply decision for ${loan.id}`, type: "error" });
    } finally {
      setBusy(false);
    }
  };

  const bulkDecide = async (decision) => {
    const selection = {};
    if (selectAllMatching) {
      selection.select_all_matching = true;
      selection.filter = {
        ccy: filters.ccy !== "All" ? filters.ccy : null,
        min: filters.min ? Number(filters.min) : null,
        max: filters.max ? Number(filters.max) : null,
        low_conf: filters.lowConf,
        q: filters.q || null,
      };
    } else {
      selection.loan_ids = [...sel];
    }

    // Rule 3 accept is a two-step flow: generate every pick and let the
    // reviewer see them BEFORE anything is applied - never generate-and-apply
    // a batch of LLM picks in one uninspectable call.
    if (decision === "accept" && activeRule === 3) {
      setBusy(true);
      try {
        const data = await postJSON("/api/review/bulk-generate", { ...selection, max_loans: 100 });
        setBatchReview({ results: data.results, selection });
      } catch (e) {
        console.error("bulk generate failed:", e);
        setToast({ text: "Bulk generate failed", type: "error" });
      } finally {
        setBusy(false);
      }
      return;
    }

    setBusy(true);
    try {
      const body = { decision, rule: activeRule, max_loans: null, ...selection };
      const result = await postJSON("/api/review/bulk-decide", body);
      setToast({
        text: `${result.applied} ${decision === "accept" ? "accepted" : "ignored"} — re-checked through OPA${result.errors.length ? `, ${result.errors.length} errors` : ""}`,
        type: result.errors.length ? "error" : "success",
      });
      setSel(new Set());
      setSelectAllMatching(false);
      await refreshAfterChange();
    } catch (e) {
      console.error("bulk decide failed:", e);
      setToast({ text: "Bulk action failed", type: "error" });
    } finally {
      setBusy(false);
    }
  };

  const confirmBatchApply = async () => {
    if (!batchReview) return;
    setBusy(true);
    try {
      const result = await postJSON("/api/review/bulk-decide", { decision: "accept", rule: 3, max_loans: null, ...batchReview.selection });
      setToast({
        text: `${result.applied} accepted — re-checked through OPA${result.errors.length ? `, ${result.errors.length} errors` : ""}`,
        type: result.errors.length ? "error" : "success",
      });
      setSel(new Set());
      setSelectAllMatching(false);
      setBatchReview(null);
      await refreshAfterChange();
    } catch (e) {
      console.error("bulk apply failed:", e);
      setToast({ text: "Bulk apply failed", type: "error" });
    } finally {
      setBusy(false);
    }
  };

  const cancelBatchReview = () => setBatchReview(null);

  if (activeRule == null) {
    return <div style={{ padding: 32, color: C.mute, fontSize: 13 }}>Loading review queue…</div>;
  }

  const loanIndex = loans.findIndex((l) => l.id === pick);
  const selCount = selectAllMatching ? filteredTotal : sel.size;

  return (
    <div style={{ fontFamily: FONT, background: C.paper, color: C.text, minHeight: "100vh", display: "flex" }}>
      <style>{`*{box-sizing:border-box}button:focus-visible,input:focus-visible,textarea:focus-visible{outline:2px solid ${C.coral};outline-offset:1px}::-webkit-scrollbar{width:10px;height:10px}::-webkit-scrollbar-thumb{background:${C.lineStrong};border-radius:6px}.spin{animation:sp 1s linear infinite}@keyframes sp{to{transform:rotate(360deg)}}@media (max-width:1200px){.jr-grid{grid-template-columns:1fr !important}}`}</style>
      <div style={{ width: 216, background: C.railBg, color: C.railText, position: "sticky", top: 0, height: "100vh", display: "flex", flexDirection: "column", flexShrink: 0 }}>
        <div style={{ padding: "20px 18px 22px" }}><div style={{ fontSize: 18, fontWeight: 800, letterSpacing: -0.3, color: "#fff" }}>Kyndryl</div><div style={{ fontSize: 11, color: C.railMute, marginTop: 2 }}>Loan Compliance</div></div>
        <div style={{ padding: "0 12px", display: "flex", flexDirection: "column", gap: 2 }}>
          {OUTER_NAV.map((n) => { const Icon = n.icon; const active = n.id === "review"; return (
            <button key={n.id} onClick={() => setTab && setTab(n.id)} style={{ ...row(10), padding: "10px 12px", borderRadius: 8, border: "none", cursor: "pointer", textAlign: "left", fontFamily: FONT, fontSize: 13.5, fontWeight: active ? 700 : 500, background: active ? "rgba(255,76,52,0.16)" : "transparent", color: active ? "#fff" : C.railText, borderLeft: active ? `2px solid ${C.coral}` : "2px solid transparent" }}>
              <Icon size={17} color={active ? C.coral : C.railMute} /><span style={{ flex: 1 }}>{n.label}</span>{n.id === "review" && overall.total > 0 && <span style={{ fontFamily: MONO, fontSize: 10.5, fontWeight: 700, background: C.railEl, color: C.railMute, padding: "1px 6px", borderRadius: 7 }}>{fmtNum(overall.total - overall.reviewed)}</span>}
            </button>); })}
        </div>
      </div>
      <div style={{ flex: 1, minWidth: 0, padding: 22, height: "100vh", overflowY: "auto" }}>
        <FxStrip fx={loan?.impact?.fx || (runFx ? { source: runFx.source, as_of: runFx.as_of, stale: runFx.stale } : null)} />
        <StagePipeline stages={stages} activeRule={activeRule} onPick={setActiveRule} overall={overall} />
        <BatchBar
          count={selCount}
          matchTotal={filteredTotal}
          onSelectAllMatch={() => setSelectAllMatching(true)}
          onClear={() => { setSel(new Set()); setSelectAllMatching(false); }}
          onAccept={() => bulkDecide("accept")}
          onIgnore={() => bulkDecide("ignore")}
          busy={busy}
        />
        <BatchReviewPanel batchReview={batchReview} onConfirm={confirmBatchApply} onCancel={cancelBatchReview} busy={busy} />
        {toast && (
          <div style={{ ...row(9), background: toast.type === "error" ? C.coralSoft : C.greenSoft, border: `1px solid ${toast.type === "error" ? C.coral + "66" : C.greenBright + "66"}`, borderRadius: 10, padding: "10px 14px", marginBottom: 14 }}>
            {toast.type === "error" ? <CircleAlert size={16} color={C.coralDark} /> : <CircleCheck size={16} color={C.green} />}
            <span style={{ fontSize: 12.5, color: C.text }}>{toast.text}</span>
            <button onClick={() => setToast(null)} style={{ marginLeft: "auto", background: "none", border: "none", cursor: "pointer", color: C.mute, display: "flex" }}><X size={15} /></button>
          </div>
        )}
        <div className="jr-grid" style={{ display: "grid", gridTemplateColumns: loan?.rule_failed === 3 ? "340px minmax(0,1fr) 230px" : "340px minmax(0,1fr) 290px", gap: 16, alignItems: "start" }}>
          <Queue
            activeRule={activeRule} stages={stages} rows={loans} stageTotal={stageTotal} filteredTotal={filteredTotal}
            summary={summary} filters={filters} setFilters={setFilters}
            activeId={pick} onPick={openLoan} sel={sel} setSel={setSel} loading={queueLoading}
          />
          <div style={{ ...col(16), position: "sticky", top: 0 }}>
            <Detail
              loan={loan} index={loanIndex} stageTotal={stageTotal} selectedAsset={selectedAsset} onSelectAsset={setSelectedAsset}
              picking={picking} onToggleManual={() => setPicking((p) => !p)} onApply={() => decide("manual")} onReload={() => openLoan(loan.id)}
            />
            <DecisionBar
              loan={loan} onDecide={decide} busy={busy}
              acceptDisabled={loan?.rule_failed === 3 && loan?.fix?.type !== "substitute_asset"}
              showRemove={loan?.rule_failed === 3 && loan?.fix?.type !== "substitute_asset" && !!loan?.computed}
              picking={picking} onToggleManual={() => setPicking((p) => !p)}
            />
          </div>
          <div style={{ position: "sticky", top: 0 }}>
            <Impact loan={loan} />
          </div>
        </div>
      </div>
    </div>
  );
}

export default Review;
