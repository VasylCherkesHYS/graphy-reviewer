# AI Code Review — GitHub App

A GitHub App that reviews pull requests (OpenAI or Anthropic, your choice), holds
discussions in the threads of its own comments, and on command **applies the suggested
fixes itself**, commits them, and pushes to the PR branch.

## Features

- **PR review** — inline comments on changed lines + an overall summary.
  Uses the dependency graph (`code-review-graph`) as "blast radius" context.
- **Review triggers:**
  - the bot is requested as a PR reviewer (`review_requested`) — `AUTO_REVIEW_ON_REQUEST=true`;
  - the `/review` command in a PR comment;
  - optionally, automatically when a PR is opened — `AUTO_REVIEW_ON_OPEN=true`;
  - optionally, on new commits to the PR head branch (`git push` **or** commits from
    the GitHub UI, e.g. "Commit suggestion") — `AUTO_REVIEW_ON_SYNC=true`; the bot's own
    pushes (from `/apply`) are skipped to avoid a loop.
- **Dialog** — reply in the thread of the bot's comment and it will respond on the merits.
- **Applying fixes:**
  - `/apply` — as a reply **in the thread of a specific finding**: the bot generates the fix,
    applies it, commits, and pushes to the PR branch (as a separate commit);
  - `/apply-all` — as a PR comment: applies all of its findings, each as a separate commit;
  - or don't apply — the developer fixes it themselves.

## Commands

| Command      | Where to write it                            | What it does                                |
|--------------|----------------------------------------------|---------------------------------------------|
| `/review`    | a PR comment                                 | (re)run the review                          |
| `/apply`     | a reply in the thread of my inline finding   | apply this fix, commit, and push            |
| `/apply-all` | a PR comment                                 | apply all findings (one commit each)        |
| `/help`      | a PR comment                                 | show the list of commands                   |

## Configuration

Copy `.env.example` → `.env` and fill it in. Key variables:

- `LLM_PROVIDER` — `openai` (default) or `anthropic`.
- `OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_COMPLEX_MODEL`.
- `GITHUB_APP_ID`, `GITHUB_WEBHOOK_SECRET`.
- **GitHub App private key** — set *one* of the two ways:
  - `GITHUB_PRIVATE_KEY` — PEM inline, newlines as `\n`;
  - `GITHUB_PRIVATE_KEY_PATH` — path to a `.pem` file (**takes precedence**; for
    docker-compose this is a host path that is mounted into the container).
- `NGROK_AUTHTOKEN` — needed only for the docker-compose tunnel
  ([free token](https://dashboard.ngrok.com/get-started/your-authtoken)).
- `AUTO_REVIEW_ON_REQUEST`, `AUTO_REVIEW_ON_OPEN`, `AUTO_REVIEW_ON_SYNC`.
- `GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL` — the identity used for fix commits.
- `LOG_LEVEL` — `DEBUG` / `INFO` (default) / `WARNING` / `ERROR`.
- `OBSERVABILITY_TOKEN` — if set, the monitoring endpoints below require it.

## Monitoring & logs

The app tracks every webhook delivery in memory (reset on restart) and keeps the
most recent log lines, so you can see what's happening without SSHing into the host:

| Endpoint     | What it returns                                                        |
|--------------|------------------------------------------------------------------------|
| `/healthz`   | liveness + uptime + counters (`received` / `ok` / `error` / `skipped`) |
| `/stats`     | the same counters plus the last error                                  |
| `/events`    | recent deliveries (event, action, repo, PR, status, duration, error)   |
| `/logs`      | recent log lines                                                       |
| `/dashboard` | an HTML page combining all of the above, auto-refreshing every 5s      |

Query params: `/events?limit=50&status=error`, `/logs?limit=100&level=ERROR`.

If `OBSERVABILITY_TOKEN` is set, pass it as `?token=...` or the
`X-Observability-Token` header on `/stats`, `/events`, `/logs`, `/dashboard`
(`/healthz` and `/webhook` are never gated). Set the token whenever the app is
reachable publicly — the logs and event list may contain repo and PR identifiers.

```bash
curl http://localhost:8000/stats
curl "http://localhost:8000/events?status=error&token=$OBSERVABILITY_TOKEN"
# open the dashboard in a browser:
#   http://localhost:8000/dashboard?token=...
```

## Running locally

There are two ways: via **Docker Compose** (recommended — the server and the ngrok
tunnel in one command) or **manually** on the host.

### Option A — Docker Compose (recommended)

You need: Docker + Docker Compose, a filled-in `.env`, an `NGROK_AUTHTOKEN`.

`docker-compose.yml` brings up two services:
- `app` — built from `Dockerfile`, listens on port `8000`, healthcheck on `/healthz`;
- `tunnel` — ngrok, exposes `app:8000` to the outside; starts only after `app`
  becomes healthy. Web inspector: `http://localhost:4040`.

**1. Fill in `.env`** (see the "Configuration" section), including `NGROK_AUTHTOKEN`.
If you set the key via a file — write the host path to the `.pem`:

```bash
echo 'GITHUB_PRIVATE_KEY_PATH=./reviewer-bot.private-key.pem' >> .env
```

> Note: with an inline key you can remove the `environment: GITHUB_PRIVATE_KEY_PATH`
> and `volumes` blocks from the `app` service in `docker-compose.yml`.

**2. Start it:**

```bash
docker compose up --build
```

**3. Find the public tunnel URL** — open `http://localhost:4040` (or
`curl -s http://localhost:4040/api/tunnels`). It looks like
`https://<random>.ngrok-free.app`.

**4. Configure the webhook** (see step 4 below), Payload URL = `<ngrok-url>/webhook`.

### Option B — manually on the host

You need: Python 3.12+, Node.js (for the tunnel), a filled-in `.env`.

**1. Install dependencies** (once):

```bash
# full setup (with code-review-graph for graph context)
pip install -e .

# or a minimal runtime if code-review-graph won't install:
pip install "fastapi>=0.115" "uvicorn[standard]>=0.30" "httpx>=0.27" \
            "openai>=1.50" "anthropic>=0.40" "pyjwt[crypto]>=2.9" "pydantic-settings>=2.5"
```

**2. Start the server** (terminal #1, leave it open):

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Check: `curl http://localhost:8000/healthz` → `{"status":"ok"}`.

**3. Start a public tunnel** (terminal #2, leave it open):

```bash
npx --yes localtunnel --port 8000 --subdomain graphy-reviewer-bot
```

It prints: `your url is: https://graphy-reviewer-bot.loca.lt`.
If that subdomain is taken, localtunnel gives a random one — then **update the Webhook URL in GitHub**.

### Common steps (for both options)

**4. Configure the webhook** in GitHub App → General → Webhook:

- **Payload URL:** `<public-url>/webhook` (loca.lt or ngrok — see above)
- **Content type:** `application/json`
- **Secret:** the value from `.env` → `GITHUB_WEBHOOK_SECRET`

**5. Trigger a review:** in the PR, request the bot as a reviewer or write `/review`.

> The server and the tunnel must be running while you use the bot. For continuous
> operation without a local machine — deploy to Railway (`railway.toml` is already in
> the project); the variables from `.env` are set in the Railway dashboard.

**If the bot doesn't respond** — check GitHub App → Advanced → **Recent Deliveries**:
it shows whether the event was sent and the response code (401 = Secret mismatch,
timeout = server/tunnel unreachable).

## GitHub App setup

See the setup section (permissions, events, how to add the bot as a reviewer).
In short — permissions: **Contents: Read & Write**, **Pull requests: Read & Write**,
**Metadata: Read**; events: **Pull request**, **Issue comment**,
**Pull request review comment**.
