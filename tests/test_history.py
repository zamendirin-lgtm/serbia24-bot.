import unittest

from scripts.persist_history import merge_states


class HistoryMergeTests(unittest.TestCase):
    def test_union_preserves_both_published_posts(self):
        remote = {
            "seen": {"remote-link": 100},
            "photos": {"remote-photo": 100},
            "phashes": {},
            "posted": [{"title_norm": "remote title", "source": "Danas", "ts": 100}],
        }
        local = {
            "seen": {"local-link": 101},
            "photos": {},
            "phashes": {"abc": 101},
            "posted": [{"title_norm": "local title", "source": "RTS", "ts": 101}],
        }
        combined = merge_states(local, remote)
        self.assertEqual(set(combined["seen"]), {"remote-link", "local-link"})
        self.assertEqual(set(combined["photos"]), {"remote-photo"})
        self.assertEqual(set(combined["phashes"]), {"abc"})
        self.assertEqual(len(combined["posted"]), 2)
        self.assertEqual(combined["posted"][1]["title_norm"], "local title")

    def test_repeated_history_records_collapse(self):
        record = {"title_norm": "same headline", "source": "N1", "ts": 202.1}
        state = {"seen": {"id": 202}, "photos": {}, "phashes": {},
                 "posted": [record]}
        merged = merge_states(state, state)
        self.assertEqual(len(merged["posted"]), 1)
        self.assertEqual(merged["seen"]["id"], 202)

    def test_latest_timestamp_wins_for_same_image(self):
        current = {"photos": {"image": 205}}
        remote = {"photos": {"image": 200}}
        self.assertEqual(merge_states(current, remote)["photos"]["image"], 205)
        self.assertEqual(merge_states(remote, current)["photos"]["image"], 205)


if __name__ == "__main__":
    unittest.main()
