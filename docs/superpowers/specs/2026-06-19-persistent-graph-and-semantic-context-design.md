# Persistent code graph (rebuilt on merge to main) + semantic vector context in PR review

Date: 2026-06-19
Status: approved for implementation

## Problem

Today the review flow rebuilds the `code-review-graph` from scratch inside an
ephemeral clone on **every** PR, and uses only `detect-changes --brief` (pure
graph traversal). Vector embeddings exist in `code-review-graph` but are never
installed nor used, so reviews get no semantic ("find related code") context.

We want two things:

1. **Persistent graph**: the graph (with embeddings) is rebuilt only when `main`
   changes (a merge / push to the default branch) and stored per-repo, so PR
   reviews reuse it instead of paying a full rebuild each time.
2. **Semantic context in reviews**: feed code that is *semantically related* to
   the diff (via vector search) into the LLM prompt, not just dependency-graph
   blast radius.

## Decisions (locked)

- **Embedding provider**: OpenAI, reusing the already-configured `OPENAI_API_KEY`.
  The OpenAI provider in `code-review-graph` is `urllib`-based, so the heavy
  `[embeddings]` extra (torch/sentence-transformers) is **not** needed — the
  Docker/Railway image stays small.
- **Storage**: a dedicated orphan service branch `crg-cache` in the same repo
  holds a single `graph.db` (graph + embeddings in one SQLite file). Force-pushed
  as a single commit each rebuild so it never grows unbounded and `main` stays
  clean.
- **Rebuild trigger**: GitHub `push` event to the default branch.
- **PR-time handling**: restore `graph.db` from `crg-cache`, then run an
  incremental `update` (re-parse + re-embed **only** the PR's changed files), then
  `detect-changes` + semantic search. Cheap and accurate (PR's new code is in the
  graph).

## Flows

### Flow 1 — `push` to default branch → rebuild graph (heavy, infrequent)

```
push(ref=refs/heads/<default>)
  guards: not a branch deletion; sender is not the bot; refresh_graph_on_push
  → installation token
  → clone main @ after-sha (shallow)
  → restore_from_cache(crg-cache → .code-review-graph/graph.db)        [if present]
  → ensure_graph: `update` (incremental) when cache present, else `build`
  → build_embeddings (OpenAI; only nodes whose text changed get re-embedded)
  → save_to_cache: force-push graph.db to crg-cache (single commit)
  → cleanup clone
```

Serialized per `owner/repo` with an in-memory `asyncio.Lock`. Best-effort:
failures are logged and never surface to users.

### Flow 2 — PR review → uses the persistent graph (cheap)

```
clone PR head @ refs/pull/N/head
  → restore_from_cache(crg-cache → .code-review-graph/graph.db)
        ├─ cache present → update (re-parse/re-embed only PR's changed files)
        └─ cache missing → fallback: full build + embed (under max_embed_nodes guard)
  → detect_changes(--base base_sha)        → graph_context
  → semantic_context(diff)                  → related code via vector search
  → cleanup clone
  → review_pr(diff, graph_context, semantic_context) → LLM → post
```

## Components

| File | Change |
|------|--------|
| `app/config.py` | new settings (embeddings + cache branch + guards) |
| `app/main.py` | add `"push"` to `SUPPORTED_EVENTS` |
| `app/github/payload.py` | `PushCtx.from_payload` (ref, after, default_branch, installation, owner/repo, sender, deleted) |
| `app/handlers/events.py` | `push` → `_handle_push` → `_refresh_graph`; rewrite `_run_review` to restore→update |
| `app/review/graph_cache.py` *(new)* | `restore_from_cache`, `save_to_cache` |
| `app/review/graph.py` | `_ensure_embedding_env`, `update_graph`, `build_embeddings`, `semantic_context`; lazy `code_review_graph` imports |
| `app/review/reviewer.py` | `review_pr(diff, graph_context, semantic_context)` |
| `app/review/prompts.py` | new prompt section `=== SEMANTICALLY RELATED CODE (vector search) ===` |
| `app/monitoring.py` | `summarize_payload` understands `push` (show ref) |
| `pyproject.toml` / `Dockerfile` | **no new deps** (OpenAI provider uses urllib) |
| `.env.example`, `README.md` | document new vars + the GitHub App **Push** event subscription |

### New config settings

```
# embeddings / semantic context
enable_semantic_context: bool = True
openai_embedding_model: str = "text-embedding-3-small"
openai_embedding_base_url: str = "https://api.openai.com/v1"
semantic_top_k: int = 10
max_related_chars: int = 8000
embed_timeout: int = 300            # seconds for the embed subprocess/call
max_embed_nodes: int = 6000         # skip embedding above this node count (cost guard)
# persistent graph cache
refresh_graph_on_push: bool = True
graph_cache_branch: str = "crg-cache"
```

### Embedding env (`_ensure_embedding_env`)

Set once before embed/search so both the in-process API and any subprocess pick
them up, derived from existing settings:

```
CRG_OPENAI_API_KEY      = settings.openai_api_key
CRG_OPENAI_BASE_URL     = settings.openai_embedding_base_url
CRG_OPENAI_MODEL        = settings.openai_embedding_model
CRG_ACCEPT_CLOUD_EMBEDDINGS = "1"
```

### Git mechanics (reusing existing token-in-URL + bot identity patterns)

- **restore**: `git fetch --depth 1 origin <branch>` then
  `git show FETCH_HEAD:graph.db` written into `<repo>/.code-review-graph/graph.db`.
  Returns `False` on any failure (branch missing = cache miss).
- **save**: fresh `git init` in a temp dir, add the single `graph.db`, commit with
  the bot identity (`settings.git_author_name/email`), `git push -f origin
  HEAD:<branch>`.

### Semantic search

`semantic_context(repo_dir, diff)`:
1. Build a query from the diff: changed file basenames + the added (`+`) code
   lines, truncated to a safe length (embedding-query token budget).
2. `code_review_graph.tools.query.semantic_search_nodes(query, repo_root=repo_dir,
   limit=semantic_top_k, provider="openai")` (lazy import).
3. Drop results whose `file_path` is already among the diff's changed files
   (avoid echoing the diff back).
4. Render remaining nodes (path, name, kind, code snippet) into a block capped at
   `max_related_chars`; otherwise return a fallback string.

## Concurrency & loop safety

- Per-`owner/repo` `asyncio.Lock` serializes rebuilds (rapid pushes run
  sequentially; force-push means last-one-wins).
- `push` refresh reacts only to the default branch. The bot's own pushes — to
  `crg-cache` and to PR branches via `/apply` — never match the default branch, so
  no rebuild loop. Extra guard: skip when the push `sender` is the bot.

## Error handling

Every new step is wrapped in `try/except` with a fallback string, matching the
existing graceful-degradation style:
- cache restore fails → full build (first-ever review still works), under the
  `max_embed_nodes` guard; if that fails → diff-only fallback.
- embeddings / semantic search fail (no key, API error, package absent) → review
  proceeds with diff + graph context only.
- `_refresh_graph` is best-effort; failures are logged only.

`code_review_graph` imports are lazy (inside `try`) so the documented "minimal
runtime without the package" keeps working.

## Testing (pytest; everything mocked, package not required)

- push-ref filtering (default branch vs other refs, deletions, bot sender)
- restore/save git command construction (argv + cwd)
- PR path branching: cache-present (update) vs cache-missing (build)
- diff → query construction and truncation
- related-code rendering + `max_related_chars` cap + changed-file filtering
- graceful fallbacks on `ImportError` / API error
- `semantic_context` is threaded into the review prompt

## Follow-ups (out of scope for v1)

- gzip `graph.db` in the cache branch to cut transfer/repo size.
- coalesce concurrent push rebuilds (skip in-flight instead of queueing).
- expose cache size/age in `/stats`.
