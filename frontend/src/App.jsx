import { useEffect, useMemo, useState } from "react";

const integer = new Intl.NumberFormat("en-GB", { maximumFractionDigits: 0 });
const oneDecimal = new Intl.NumberFormat("en-GB", { maximumFractionDigits: 1 });
const ukTime = new Intl.DateTimeFormat("en-GB", {
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
  timeZone: "Europe/London",
});
const fullDate = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});

function num(value, decimals = false) {
  if (value === null || value === undefined) return "—";
  return (decimals ? oneDecimal : integer).format(value);
}

function stamp(value) {
  return value ? `${fullDate.format(new Date(value))} · ${ukTime.format(new Date(value))} UK` : "—";
}

function Icon({ type, size = 18 }) {
  const props = {
    viewBox: "0 0 24 24",
    width: size,
    height: size,
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.8,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    "aria-hidden": true,
  };
  if (type === "wind") return <svg {...props}><path d="M3 8h12.5a2.5 2.5 0 1 0-2.5-2.5M2 12h17a2.5 2.5 0 1 1-2.5 2.5M4 16h7.5a2.5 2.5 0 1 1-2.5 2.5" /></svg>;
  if (type === "trend") return <svg {...props}><path d="m3 17 6-6 4 4 8-9M15 6h6v6" /></svg>;
  if (type === "calendar") return <svg {...props}><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M16 3v4M8 3v4M3 10h18" /></svg>;
  return <svg {...props}><circle cx="12" cy="12" r="9" /><path d="M12 11v5M12 8h.01" /></svg>;
}

function Metric({ label, value, suffix, detail, tone = "" }) {
  return (
    <article className={`metric ${tone}`}>
      <div className="metric__head"><span>{label}</span><i><Icon type={tone === "blue" ? "trend" : "wind"} /></i></div>
      <strong>{value}<small>{suffix}</small></strong>
      <p>{detail}</p>
    </article>
  );
}

function ComparisonMetric({ label, raw, calibrated, suffix, tone = "" }) {
  const improvement = raw !== null && raw !== undefined && calibrated !== null
    ? ((Math.abs(raw) - Math.abs(calibrated)) / Math.abs(raw)) * 100
    : null;
  return (
    <article className={`metric comparison-metric ${tone}`}>
      <div className="metric__head"><span>{label}</span><i><Icon type={tone === "blue" ? "trend" : "wind"} /></i></div>
      <div className="comparison-values">
        <span><small>RAW</small><strong>{num(raw, true)}<em>{suffix}</em></strong></span>
        <span><small>CALIBRATED</small><strong>{num(calibrated, true)}<em>{suffix}</em></strong></span>
      </div>
      <p className={improvement === null ? "" : improvement >= 0 ? "improved" : "worsened"}>
        {improvement === null ? "No walk-forward calibration coverage" : `${Math.abs(improvement).toFixed(1)}% ${improvement >= 0 ? "lower" : "higher"} absolute error`}
      </p>
    </article>
  );
}

function HourChart({ points }) {
  const width = 840;
  const height = 280;
  const margin = { top: 16, right: 12, bottom: 36, left: 52 };
  const values = points.flatMap((p) => [p.forecast_mw, p.calibrated_forecast_mw, p.actual_mw].filter(Number.isFinite));
  if (!values.length) return <div className="chart-empty">No hourly values available for this date.</div>;
  const low = Math.floor(Math.min(...values) / 5000) * 5000;
  const high = Math.ceil(Math.max(...values) / 5000) * 5000;
  const span = high - low || 1;
  const pw = width - margin.left - margin.right;
  const ph = height - margin.top - margin.bottom;
  const x = (index) => margin.left + index / Math.max(points.length - 1, 1) * pw;
  const y = (value) => margin.top + (high - value) / span * ph;
  const path = (key) => {
    let active = false;
    return points.reduce((result, point, index) => {
      if (!Number.isFinite(point[key])) { active = false; return result; }
      const command = active ? "L" : "M";
      active = true;
      return `${result}${command}${x(index).toFixed(1)},${y(point[key]).toFixed(1)} `;
    }, "");
  };
  return (
    <svg className="chart-svg" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Hourly forecast and actual wind generation in megawatts">
      {[0, 0.25, 0.5, 0.75, 1].map((fraction) => {
        const tick = low + span * fraction;
        const pos = y(tick);
        return <g key={fraction}><line className="gridline" x1={margin.left} x2={width - margin.right} y1={pos} y2={pos} /><text className="axis" x={margin.left - 9} y={pos + 4} textAnchor="end">{Math.round(tick / 1000)}k</text></g>;
      })}
      {points.map((point, index) => index % 6 === 0 || index === points.length - 1
        ? <text className="axis" key={point.start_time} x={x(index)} y={height - 10} textAnchor="middle">{ukTime.format(new Date(point.start_time))}</text>
        : null)}
      {points.length > 1 && <><path className="line forecast-line" d={path("forecast_mw")} /><path className="line calibrated-line" d={path("calibrated_forecast_mw")} /><path className="line actual-line" d={path("actual_mw")} /></>}
    </svg>
  );
}

function DailyErrorChart({ days, onSelect }) {
  const measured = days.filter((day) => day.calibrated_metrics.mae_mw !== null);
  if (!measured.length) return <div className="chart-empty">No matched forecast and actual hours.</div>;
  const width = 840;
  const height = 210;
  const margin = { top: 15, right: 10, bottom: 30, left: 52 };
  const max = Math.max(...measured.map((day) => day.metrics.mae_mw), 1);
  const plotHeight = height - margin.top - margin.bottom;
  const slot = (width - margin.left - margin.right) / measured.length;
  return (
    <svg className="chart-svg" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Daily mean absolute error in megawatts">
      {[0, 0.5, 1].map((fraction) => {
        const y = margin.top + plotHeight * (1 - fraction);
        return <g key={fraction}><line className="gridline" x1={margin.left} x2={width - margin.right} y1={y} y2={y} /><text className="axis" x={margin.left - 9} y={y + 4} textAnchor="end">{num(max * fraction)}</text></g>;
      })}
      {measured.map((day, index) => {
        const rawHeight = day.metrics.mae_mw / max * plotHeight;
        const calibratedHeight = day.calibrated_metrics.mae_mw / max * plotHeight;
        const x = margin.left + index * slot + slot * 0.13;
        const rawY = margin.top + plotHeight - rawHeight;
        const calibratedY = margin.top + plotHeight - calibratedHeight;
        const dayNumber = Number(day.delivery_date.slice(-2));
        return <g key={day.delivery_date} className="error-bar" role="button" tabIndex="0"
          aria-label={`${day.delivery_date}: raw MAE ${num(day.metrics.mae_mw)}, calibrated MAE ${num(day.calibrated_metrics.mae_mw)} megawatts`}
          onClick={() => onSelect(day.delivery_date)}
          onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") onSelect(day.delivery_date); }}>
          <rect className="raw-bar" x={x} y={rawY} width={Math.max(slot * 0.32, 2)} height={Math.max(rawHeight, 1)} rx="2" />
          <rect className="calibrated-bar" x={x + Math.max(slot * 0.36, 3)} y={calibratedY} width={Math.max(slot * 0.32, 2)} height={Math.max(calibratedHeight, 1)} rx="2" />
          {(index === 0 || dayNumber % 5 === 0 || index === measured.length - 1) && <text className="axis" x={x + slot * 0.36} y={height - 8} textAnchor="middle">{dayNumber}</text>}
        </g>;
      })}
    </svg>
  );
}

function App() {
  const [data, setData] = useState(null);
  const [selectedDate, setSelectedDate] = useState("2026-01-31");
  const [tab, setTab] = useState("decision");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/month", { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) {
          const body = await response.json().catch(() => ({}));
          throw new Error(body.detail || `The data service returned ${response.status}.`);
        }
        return response.json();
      })
      .then((payload) => {
        setData(payload);
        if (payload.days?.length) setSelectedDate(payload.days[payload.days.length - 1].delivery_date);
      })
      .catch((cause) => { if (cause.name !== "AbortError") setError(cause.message || "Unable to load Elexon data."); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, []);

  const selected = useMemo(() => data?.days.find((day) => day.delivery_date === selectedDate), [data, selectedDate]);
  const avg = (key) => {
    const values = (selected?.points || []).map((point) => point[key]).filter(Number.isFinite);
    return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
  };
  const matched = selected?.metrics.matched_hours ?? 0;
  const setDay = (value) => {
    if (data?.days.some((day) => day.delivery_date === value)) setSelectedDate(value);
  };

  return (
    <div className="app">
      <aside className="sidebar">
        <a className="brand" href="#" aria-label="Wind Ledger home"><b><Icon type="wind" size={23} /></b><span><strong>wind<span>ledger</span></strong><small>RENEWABLE INTELLIGENCE</small></span></a>
        <div className="nav-label">WORKSPACE</div>
        <button className={`nav-link ${tab === "decision" ? "selected" : ""}`} onClick={() => setTab("decision")}><Icon type="wind" /> <span>Day-ahead view</span></button>
        <button className={`nav-link ${tab === "accuracy" ? "selected" : ""}`} onClick={() => setTab("accuracy")}><Icon type="trend" /> <span>Forecast accuracy</span></button>
        <div className="sidebar-bottom"><div className="connection"><i /><span><b>Connected to Elexon</b><small>National wind · Great Britain</small></span></div><small className="version">WIND LEDGER · PILOT 01</small></div>
      </aside>
      <main>
        <header className="topbar"><div><span>ENERGY TRADING</span><i>/</i> RENEWABLES</div><div className="topbar-right"><span className="historical"><i /> HISTORICAL REPLAY</span><b className="avatar">UK</b></div></header>
        <section className="heading">
          <div><div className="eyebrow"><i /> JANUARY 2026 <span>·</span> WIND GENERATION</div>
            <h1>{tab === "decision" ? "A clearer view of the wind." : "Know your forecast error."}</h1>
            <p>{tab === "decision" ? "See the latest day-ahead wind outlook alongside what actually came through." : "Measure how closely the day-ahead wind forecast tracked actual generation."}</p>
          </div>
          {tab === "decision" && <label className="date-picker"><span><Icon type="calendar" size={15} /> DELIVERY DATE</span><input type="date" min="2026-01-01" max="2026-01-31" value={selectedDate} disabled={!data} onChange={(event) => setDay(event.target.value)} /></label>}
        </section>

        {error && <div className="error" role="alert"><b>Couldn’t load the January data.</b><span>{error}</span><button onClick={() => window.location.reload()}>Retry</button></div>}
        {loading && !data ? <div className="loading"><i /><b>Gathering January wind data</b><span>Connecting to Elexon BMRS actuals and forecast streams…</span></div> : null}
        {data && tab === "decision" && <>
          <section className="metrics">
            <Metric label="DAY-AHEAD WIND FORECAST" value={num(avg("forecast_mw"))} suffix="MW" detail={`Calibrated average ${num(avg("calibrated_forecast_mw"))} MW · latest issue ${selected?.forecast_publish_time ? stamp(selected.forecast_publish_time) : "not available"}`} />
            <Metric label="ACTUAL WIND OUTPUT" value={num(avg("actual_mw"))} suffix="MW" detail={`${matched} of 24 hourly periods matched`} tone="blue" />
            <ComparisonMetric label="DAILY MAE · MW" raw={selected?.metrics.mae_mw} calibrated={selected?.calibrated_metrics.mae_mw} suffix=" MW" tone="blue" />
            <ComparisonMetric label="DAILY BIAS · MW" raw={selected?.metrics.bias_mw} calibrated={selected?.calibrated_metrics.bias_mw} suffix=" MW" />
          </section>
          <section className="columns">
            <article className="panel trend">
              <div className="panel-head"><div><small>HOURLY GENERATION</small><h2>{selected ? fullDate.format(new Date(`${selected.delivery_date}T12:00:00Z`)) : "Selected delivery day"}</h2><p>Forecast at decision time compared with actual output · MW</p></div><span className="badge"><i /> {matched ? `${matched} HOURS MATCHED` : "NO MATCHED HOURS"}</span></div>
              <HourChart points={selected?.points || []} />
              <div className="legend"><span><i className="forecast-dot" /> RAW FORECAST</span><span><i className="calibrated-dot" /> CALIBRATED</span><span><i className="actual-dot" /> ACTUAL</span><small>All times UK · GMT</small></div>
            </article>
            <aside className="side-column">
              <article className="snapshot"><small>DECISION SNAPSHOT</small><b className="snapshot-icon"><Icon type="wind" size={21} /></b><h2>One day ahead.<br />One clearer call.</h2><p>This view uses the latest WINDFOR issue available before the N2EX gate closes at 09:50 UK time on the previous day.</p><div><span>Forecast issued</span><b>{selected?.forecast_publish_time ? stamp(selected.forecast_publish_time) : "Not available"}</b></div><div><span>Daily forecast average</span><b>{num(avg("forecast_mw"))} MW</b></div></article>
              <article className="scope"><Icon type="info" size={16} /><div><b>A focused signal, not a full buy recommendation</b><p>Demand and other generation sources are outside this Elexon-only pilot, so residual procurement volume is not calculated.</p></div></article>
            </aside>
          </section>
          <section className="panel table-panel"><div className="panel-head compact"><div><small>SETTLEMENT DETAIL</small><h2>Hourly forecast and correction</h2></div><span className="unit">GENERATION · MW</span></div><div className="table-scroll"><table><thead><tr><th>TIME (UK)</th><th>LEAD</th><th>RAW</th><th>CALIBRATED</th><th>ACTUAL</th><th>RAW ERROR</th><th>CALIBRATED ERROR</th></tr></thead><tbody>{selected?.points.map((point) => {
            const rawError = point.forecast_mw !== null && point.actual_mw !== null ? point.forecast_mw - point.actual_mw : null;
            const calibratedError = point.calibrated_forecast_mw !== null && point.actual_mw !== null ? point.calibrated_forecast_mw - point.actual_mw : null;
            return <tr key={point.start_time}><td>{ukTime.format(new Date(point.start_time))}</td><td>{point.lead_bin ?? "—"}</td><td>{num(point.forecast_mw)}</td><td>{num(point.calibrated_forecast_mw)}</td><td>{num(point.actual_mw)}</td><td className={rawError === null ? "" : rawError > 0 ? "positive" : "negative"}>{rawError === null ? "—" : `${rawError > 0 ? "+" : ""}${num(rawError)}`}</td><td className={calibratedError === null ? "" : calibratedError > 0 ? "positive" : "negative"}>{calibratedError === null ? "—" : `${calibratedError > 0 ? "+" : ""}${num(calibratedError)}`}</td></tr>;
          })}</tbody></table></div></section>
        </>}
        {data && tab === "accuracy" && <>
          <section className="metrics">
            <ComparisonMetric label="MONTHLY MAE" raw={data.comparison_raw_metrics.mae_mw} calibrated={data.calibrated_metrics.mae_mw} suffix=" MW" tone="blue" />
            <ComparisonMetric label="MONTHLY RMSE" raw={data.comparison_raw_metrics.rmse_mw} calibrated={data.calibrated_metrics.rmse_mw} suffix=" MW" />
            <ComparisonMetric label="MONTHLY WAPE" raw={data.comparison_raw_metrics.wape_pct} calibrated={data.calibrated_metrics.wape_pct} suffix="%" />
            <ComparisonMetric label="MONTHLY BIAS" raw={data.comparison_raw_metrics.bias_mw} calibrated={data.calibrated_metrics.bias_mw} suffix=" MW" />
          </section>
          <section className="panel accuracy"><div className="panel-head"><div><small>DAILY ACCURACY · JAN 2026</small><h2>Did calibration reduce error?</h2><p>Raw and rolling-calibrated daily MAE · lower is better</p></div><span className="unit">MAE · MW</span></div><div className="error-legend"><span><i className="raw-bar-key" /> RAW</span><span><i className="cal-bar-key" /> CALIBRATED</span></div><DailyErrorChart days={data.days} onSelect={(day) => { setDay(day); setTab("decision"); }} /><p className="chart-hint">Select a day to inspect its forecast and actual output.</p></section>
          <section className="panel table-panel"><div className="panel-head compact"><div><small>ERROR BY FORECAST LEAD</small><h2>How lead time affects accuracy</h2></div><span className="unit">UTC LEAD TIME</span></div><div className="table-scroll"><table><thead><tr><th>LEAD BIN</th><th>HOURS</th><th>RAW MAE</th><th>CAL MAE</th><th>RAW BIAS</th><th>CAL BIAS</th><th>RAW WAPE</th><th>CAL WAPE</th></tr></thead><tbody>{data.calibration.lead_time_metrics.map((group) => <tr key={group.lead_bin}><td>{group.lead_bin}</td><td>{group.raw_metrics.matched_hours}</td><td>{num(group.raw_metrics.mae_mw, true)} MW</td><td>{num(group.calibrated_metrics.mae_mw, true)} MW</td><td>{num(group.raw_metrics.bias_mw, true)} MW</td><td>{num(group.calibrated_metrics.bias_mw, true)} MW</td><td>{num(group.raw_metrics.wape_pct, true)}%</td><td>{num(group.calibrated_metrics.wape_pct, true)}%</td></tr>)}</tbody></table></div></section>
          <section className="panel table-panel"><div className="panel-head compact"><div><small>MONTH AT A GLANCE</small><h2>Daily performance comparison</h2></div><button className="text-button" onClick={() => setTab("decision")}>Inspect a day ↗</button></div><div className="table-scroll"><table><thead><tr><th>DELIVERY DATE</th><th>HOURS</th><th>RAW MAE</th><th>CAL MAE</th><th>RAW RMSE</th><th>CAL RMSE</th><th>RAW BIAS</th><th>CAL BIAS</th></tr></thead><tbody>{data.days.map((day) => <tr className="click-row" key={day.delivery_date} onClick={() => { setDay(day.delivery_date); setTab("decision"); }}><td>{fullDate.format(new Date(`${day.delivery_date}T12:00:00Z`))}</td><td>{day.calibrated_metrics.matched_hours} / 24</td><td>{num(day.metrics.mae_mw, true)} MW</td><td>{num(day.calibrated_metrics.mae_mw, true)} MW</td><td>{num(day.metrics.rmse_mw, true)} MW</td><td>{num(day.calibrated_metrics.rmse_mw, true)} MW</td><td className={day.metrics.bias_mw > 0 ? "positive" : "negative"}>{num(day.metrics.bias_mw, true)} MW</td><td className={day.calibrated_metrics.bias_mw > 0 ? "positive" : "negative"}>{num(day.calibrated_metrics.bias_mw, true)} MW</td></tr>)}</tbody></table></div></section>
          <div className="method"><Icon type="info" size={16} /><p><b>Walk-forward calibration:</b> for each delivery day, the correction is the mean prior forecast-minus-actual error over the previous 30 calendar days, grouped by UTC delivery hour and forecast lead-time bin. Historical actual records are limited to those published before the test-day cutoff. Corrected wind MW is clipped at zero. Raw and calibrated metrics use the same test hours; no correction is scored before 30 prior history days are available. Calibration improves this January replay but must be revalidated on later unseen months before operational use.</p></div>
        </>}
        {!loading && !data && !error && <div className="loading">No January data was returned.</div>}
        <footer className="footer"><span>DATA: ELEXON BMRS · FUELHH + WINDFOR</span><span>JAN 2026 · NATIONAL WIND · {data?.coverage.matched_hours ?? 0} MATCHED HOURS</span></footer>
      </main>
    </div>
  );
}

export default App;
