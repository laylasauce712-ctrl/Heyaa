import unittest
from unittest.mock import patch

from cloud.worker import _progress_from_line


class CloudWorkerTests(unittest.TestCase):
    def test_renderer_progress_line_becomes_agent_room_event(self):
        with patch("cloud.worker.record_event") as record:
            _progress_from_line(
                "job-id",
                "[progress:source_preparation] running: Preparing selected sources.",
            )
        record.assert_called_once_with(
            "job-id", "source_preparation", "running", "Preparing selected sources."
        )

    def test_agent_lifecycle_line_becomes_named_agent_event(self):
        with patch("cloud.worker.record_event") as record:
            _progress_from_line(
                "job-id",
                "[agent:render_critic] needs_review: Encoded true peak is above target.",
            )
        record.assert_called_once_with(
            "job-id", "agent:render_critic", "needs_review",
            "Encoded true peak is above target."
        )

    def test_non_progress_line_is_ignored(self):
        with patch("cloud.worker.record_event") as record:
            _progress_from_line("job-id", "[sources] Downloading source video.")
        record.assert_not_called()

    def test_malformed_progress_line_is_ignored(self):
        with patch("cloud.worker.record_event") as record:
            _progress_from_line("job-id", "[progress:source_preparation")
        record.assert_not_called()


if __name__ == "__main__":
    unittest.main()
