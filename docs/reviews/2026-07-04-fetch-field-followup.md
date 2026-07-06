# PIM Fetch Field-Test Follow-up

- Ran at: `2026-07-04T14:20:36+00:00`
- Mode: direct local dry-run, no HTTP server or scheduler
- Scope: follow-up for `36kr`, `Engadget`, `Lex Fridman`, and `CNN` rows from `2026-07-02-fetch-field-test.md`

| Source | Collector | Valid | Would Store | Skip Summary | Conclusion |
|---|---:|---:|---:|---|---|
| 36kr | 20 | 13 | 13 | `duplicate_external_id=7` | Feed is healthy; previous `would-store=0` row was not a collector failure. |
| Engadget | 20 | 4 | 4 | `duplicate_external_id=16` | Feed is healthy; most latest RSS entries were already in the local DB. |
| Lex Fridman | 3 | 1 | 1 | `stale=2` | Fixed: YouTube collector now prefers YouTube RSS feed candidates and ignores channel-tab stubs from yt-dlp. The latest episode would store; older RSS entries are correctly skipped as stale. |
| CNN | 30 | 29 | 29 | `stale=1` | Fixed: website fallback now tries common news sitemap paths and treats same registered-domain sibling subdomains as same-site, so `edition.cnn.com/business` can use `www.cnn.com` sitemap article URLs after the configured RSS parse failure. |

## Notes

- The dry-run API now returns `diagnostics.normalizer_skip_summary` and `diagnostics.normalizer_skips`.
- `backend/scripts/run_fetch_field_test.py` now surfaces all-item normalizer skips in the Markdown report and can filter by `--source-type` / `--exclude-type`.
- YouTube dry-run for `Lex Fridman` now fetches from `https://www.youtube.com/feeds/videos.xml?channel_id=UCSHZKyawb77ixDdsGog4iWA` when the source's legacy `/c/...` URL only yields channel tabs through yt-dlp.
- CNN dry-run still sees the configured `https://edition.cnn.com/rss` parse error first, but the website collector now falls through to `https://edition.cnn.com/sitemap/news.xml` and hydrates article bodies.
- A full direct local refresh was intentionally stopped because the local shell environment did not provide X GraphQL cookies; X sources fell back to RSSHub/Nitter and would not be comparable with the previous service-mode report.
