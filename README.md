# Wind Ledger

Wind Ledger is a day-ahead wind intelligence pilot for a UK electricity
trading desk. It brings the latest pre-delivery-day national wind forecast
together with actual generation and makes forecast error visible in a daily
decision view and a January accuracy review.

## Client pitch

> **Make the wind leg of tomorrow's buy with your eyes open.** Wind Ledger
> puts the latest day-ahead Elexon wind forecast beside realised generation,
> then quantifies where the forecast was high, low, or close. Traders can see
> the forecast issue used for each delivery day, inspect hourly differences,
> and review systematic error across January 2026.

This pilot covers the wind component only. Consumer demand and other generation
are outside the requested data scope, so this version does not calculate
residual demand, a thermal dispatch plan, or a market purchase volume.

## Product capabilities

- January 2026, national Great Britain WIND generation from Elexon BMRS.
- Delivery date selector with forecast and actual output by hour.
- Rolling walk-forward bias calibration using the preceding 30 delivery days,
  grouped by delivery hour and forecast lead-time bin.
- One coherent WINDFOR issue per delivery day: the latest issue published
  strictly before the N2EX GB day-ahead gate closure at 09:50 UK time on the
  previous calendar day. Missing hours in that issue remain missing instead
  of silently borrowing values from an older issue.
- Side-by-side raw and calibrated MAE, RMSE, signed bias, and WAPE, tested on
  the same January delivery hours.
- Daily raw-versus-calibrated error chart, lead-time analysis, and auditable
  hourly forecast/correction/actual table.
- Responsive React interface, FastAPI backend, and single-container Docker
  deployment.

## Data and calculation choices

- Actual generation: [FUELHH stream](https://bmrs.elexon.co.uk/api-documentation/endpoint/datasets/FUELHH/stream),
  filtered to `fuelType=WIND` and settlement dates from 2025-12-02 through
  2026-02-01 (the API's upper date bound is inclusive). December actuals train
  the walk-forward correction; January records are used to score the replay.
- Forecast generation: [WINDFOR stream](https://bmrs.elexon.co.uk/api-documentation/endpoint/datasets/WINDFOR/stream),
  requested from 2025-11-30 through 2026-02-01 by `publishTime`; records are
  filtered to the December training window and January delivery hours.
- WINDFOR is hourly while FUELHH is half-hourly. The two actual half-hour
  generation values in each UTC clock hour are averaged to make a comparable
  hourly actual. January is GMT in the UK, so UTC delivery hours map directly
  to UK clock time.
- The day-ahead replay cutoff is 09:50 UK time on D-1, the published N2EX GB
  auction gate closure. The N2EX auction is a daily auction for next-day
  delivery; its gate closure is listed by [Nord Pool](https://support.nordpoolgroup.com/support/solutions/articles/8000088463-about-the-n2ex-day-ahead-auction)
  and confirmed by [National Grid](https://www.northsealink.com/en/trade-with-us/register).
  January 2026 and the December training window are both GMT, making the code's
  UTC cutoff equivalent to 09:50 UK time. Confirm the client's chosen auction
  and any earlier internal order deadline before operational use.
- Forecast bias is forecast minus actual; positive values mean wind was
  overstated. WAPE is the sum of absolute error divided by total actual
  generation. Metrics include only hours with both values present.
- For each January test day, the correction is the mean error from the previous
  30 calendar delivery days, grouped by UTC delivery hour and lead bins
  `0-12h`, `12-24h`, `24-36h`, `36-48h`, and `48h+`. Historic forecast snapshots
  use the same pre-delivery cutoff rule. Historic actual half-hours are only
  used if their FUELHH `publishTime` was before that test day's cutoff. No
  correction is scored until 30 history days are available; a missing group
  gets a zero correction. Corrected generation is clipped at 0 MW.
- January raw-versus-calibrated comparisons are evaluated over the same
  calibrated/matched periods. Hourly error percentages are intentionally not
  used as a headline metric because they become unstable when actual wind is
  near zero.
- API results are cached in-process after the first successful load. Restart
  the service to refresh the January replay.

On the live January 2026 replay using the N2EX cutoff, the rolling correction
reduced MAE from 2,122.8 MW to 1,508.6 MW (28.9%) and WAPE from 18.33% to
13.03%; RMSE changed from 2,616.7 MW to 1,919.2 MW, and bias from +1,840.3 MW
to +539.2 MW across 744 matched hours. This is a historical backtest result,
not a guarantee of future improvement. Validate the approach on later unseen
months and confirm that the client uses the N2EX auction and its gate closure
before using calibrated values for procurement.

The supplied JSON attachments contain October 2026 forecast/actual samples,
not January 2026 records, so they are not used in the January replay.

## Technical design and review notes

- `frontend/` contains the React/Vite user interface. The UI reads one JSON
  payload from `GET /api/month`; charts and summary cards share the same hourly
  records and error definitions.
- `backend/main.py` owns Elexon retrieval, date filtering, forecast snapshot
  selection, as-of actual selection, actual-hour aggregation, walk-forward
  bias calibration, and metric calculation. The two upstream streams are
  fetched concurrently. Upstream failures return HTTP 502 with an actionable
  message rather than a success-shaped empty dashboard.
- `backend/tests/test_analytics.py` covers the as-of cutoff, coherent forecast
  issue selection, timestamp/month filtering, actual generation aggregation,
  calibration training-window requirements, and error metric signs.
- In the container, FastAPI serves the production-built React assets and JSON
  API from one service. This keeps container deployment simple and avoids
  browser-to-Elexon CORS requirements.

## Repository map

```text
.
├── backend/
│   ├── main.py                 FastAPI endpoints, Elexon retrieval and analytics
│   ├── requirements.txt        Python runtime dependencies
│   └── tests/
│       └── test_analytics.py   Forecast selection and metric tests
├── frontend/
│   ├── index.html              Vite HTML entry point
│   ├── package.json            React/Vite scripts and dependencies
│   ├── package-lock.json       Locked frontend dependency tree
│   ├── vite.config.js          Development server and API proxy
│   └── src/
│       ├── App.jsx             Day-ahead and forecast accuracy screens
│       ├── main.jsx            React application entry point
│       └── styles.css          Responsive visual design
├── .dockerignore               Docker build exclusions
├── .gitignore                  Local build and environment exclusions
├── compose.yaml                Local Docker Compose service
├── Dockerfile                  Frontend build and Python runtime image
├── heroku.yml                  Heroku container deployment configuration
└── README.md                   Product, design, setup and submission notes
```

## Challenge submission checklist

- [x] React frontend and Python backend.
- [x] Elexon-only national WIND actual and forecast data for January 2026.
- [x] Docker configuration and local run instructions.
- [x] README documents the product, files, setup, technical design, and AI use.
- [ ] Public anonymous GitHub repository: not created; this workspace is not a
  Git repository and no GitHub repository credentials are configured.
- [ ] Public Vercel or Heroku deployment: not created; deployment needs an
  authenticated provider account and deployment tooling. No public app URL is
  available to submit yet.
- [ ] Unlisted YouTube demo (maximum 10 minutes): not recorded or uploaded.
  Record a customer walkthrough (up to 5 minutes) and technical review (up to
  5 minutes), then add its unlisted URL here.
- [ ] Submission form: not submitted. Submit the public repository, deployed
  app, and video URLs after publishing, and verify each URL in an incognito
  browser session as the brief requests.

Submission links (fill after publishing):

- Demo video: not yet available.
- Public source repository: not yet available.
- Deployed application: not yet available.

## Run locally

Prerequisites: Python 3.11+ and Node.js 20+.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
npm --prefix frontend install
```

In separate terminals:

```powershell
uvicorn backend.main:app --reload --port 8000
```

```powershell
npm --prefix frontend run dev
```

Open `http://localhost:5173`. Vite proxies `/api` to FastAPI on port 8000. The
backend API docs are at `http://localhost:8000/docs`.

## Run with Docker

```powershell
docker compose up --build
```

Open `http://localhost:8000`. The app needs outbound network access to
`data.elexon.co.uk` on its first load.

## Deploy to Heroku

The repository includes `heroku.yml` and a production `Dockerfile`. With the
Heroku CLI installed and an authenticated Heroku account, create a container
stack app, then deploy the repository:

```powershell
heroku login
heroku create YOUR-APP-NAME
heroku stack:set container -a YOUR-APP-NAME
git push heroku main
```

Deployment was not run from this workspace: it has no Heroku CLI, Docker
executable, Git repository, or Heroku account credentials. The app is
container-ready once those account-side prerequisites are supplied.

## Validation

```powershell
python -m unittest discover -s backend\tests -v
npm --prefix frontend run build
```

## AI assistance

AI tools (Copilot SDK in VS Code) were used to assist with domain research,
implementation, documentation, and test design. Elexon endpoint behavior and
January data availability were checked against the live public API.
