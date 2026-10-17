# Screenshots

This directory holds the screenshots embedded in the top-level
[`README.md`](../../README.md). They are produced by
[`scripts/capture_screenshots.py`](../../scripts/capture_screenshots.py).

| File | Captures |
|---|---|
| `01-home.png` | Anonymous home page in English (Light Mode). |
| `01-home-dark.png` | Anonymous home page in English (Dark Mode). |
| `02-search.png` | Rider signed in, search results with seeded trips. |
| `03-booking.png` | Trip detail page with accepted booking & contact reveal. |
| `04-trusted.png` | Trusted-contact public page in an anonymous browser. |
| `05-queue.png` | Moderation queue, signed in as the seed moderator. |
| `06-notifications.png` | Rider's notification list (in-app). |

Regenerating:

```bash
# 1. Bring up the app with the demo seed.
make run &
python -m app.seed

# 2. Capture the screenshots.
python scripts/capture_screenshots.py
```