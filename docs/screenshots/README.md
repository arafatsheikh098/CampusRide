# Screenshots

This directory holds the six screenshots embedded in the top-level
[`README.md`](../../README.md). They are produced by
[`scripts/capture_screenshots.py`](../../scripts/capture_screenshots.py)
and are not committed by default — run the script yourself, or
expect a `404 Not Found` for each image until you do.

| File | Captures |
|---|---|
| `01-home.png` | Anonymous home page in English, signed-out nav. |
| `02-search.png` | Rider signed in, search results with seeded trips. |
| `03-booking.png` | A trip detail page with the rider having booked a seat. |
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