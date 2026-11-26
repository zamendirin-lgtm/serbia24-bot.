"""Read-only smoke test of the optional science copy-editor. Never posts."""
import os
import polish

src_title = "World's fastest animal could gain more suitable habitat in Britain by 2080"
src_summary = (
    "The area suitable for peregrine falcons in the United Kingdom could "
    "increase by 74% by 2080 under a high-emissions climate scenario. "
    "More suitable territory does not automatically mean more falcons."
)
draft_title = "Самое быстрое животное может почти удвоить пригодную территорию к 2080 году"
draft_summary = (
    "Согласно исследованию, территория, пригодная для обитания сапсанов "
    "в Великобритании, может увеличиться на 74% к 2080 году. "
    "Это не обязательно увеличит количество самих птиц."
)
print("SCIENCE_GROQ_KEY_CONFIGURED", bool(os.environ.get("GROQ_API_KEY")))
result = polish.polish(src_title, src_summary, draft_title, draft_summary)
if result is None:
    print("SCIENCE_EDITOR_SMOKE_RESULT REJECTED; bot will skip doubtful article")
else:
    title, body = result
    print("SCIENCE_EDITOR_SMOKE_RESULT OK")
    print("TITLE", title[:130])
    print("BODY", body[:550])
