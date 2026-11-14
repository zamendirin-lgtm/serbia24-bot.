"""One-off smoke test for Commons real fursuit video transcodes."""
from datetime import datetime, timezone

from video_only import query_video_category, lookup_candidates, video_from_page, permitted_license, media_url_allowed

def main():
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
