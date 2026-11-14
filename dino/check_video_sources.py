"""One-off smoke test for Commons real fursuit video transcodes."""
from datetime import datetime, timezone

from video_only import query_video_category, lookup_candidates, video_from_page, permitted_license, media_url_allowed, minimal_caption, credit_document, credit_filename, credit_url

def main():
    from pathlib import Path
    import bot
    state = bot.load_state()
    pyrkon = next(x for x in state["video_search_cache"]["hits"]
                  if x["id"] == "commons-video:195011858")
    credit_file = Path(__file__).resolve().parent / "credits" / credit_filename(pyrkon)
    assert credit_file.exists()
    assert credit_file.read_text(encoding="utf-8") == credit_document(pyrkon)
    caption = minimal_caption(pyrkon)
    assert "Rose Abrams" not in caption
    assert "CC BY" not in caption
    assert "обр." not in caption
    assert "ⓘ" in caption
    assert "195011858.md" in caption
    print("COMPACT_CREDIT_TEST_OK", len(caption))
    rows = query_video_category("Videos of fursuits")
    assert rows, "No community video discovered"
    for hit in rows:
        assert hit["rights"] is not None
        assert hit["id"].startswith("commons-video:")
        assert media_url_allowed(hit["url"])
        print("VALID_VIDEO", hit["title"][:80], "transcoded", hit["transcoded"],
              "src",hit["url"].rsplit("/",1)[-1][:75])
    derivatives = [x for x in rows if x["transcoded"] and
                   ("conga" in x["title"].lower() or "pyrkon" in x["title"].lower())]
    assert derivatives, "No small video transcodes discovered from a large costume-event file"
    print("VIDEO_TRANSCODE_TEST_OK", len(rows), "transcoded", len(derivatives))

if __name__ == "__main__":
    main()
