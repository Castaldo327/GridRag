"""Command-line validation and exit codes, without provider calls."""

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from gridrag import __main__ as cli
from gridrag.records import State


class CommandLineTests(unittest.TestCase):
    def test_invalid_question_is_a_usage_error_without_calling_the_pipeline(self):
        stderr = io.StringIO()
        with (patch("sys.argv", ["gridrag", "   "]), patch.object(cli.answer, "answer") as answer,
              redirect_stderr(stderr), self.assertRaises(SystemExit) as raised):
            cli.main()
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("question must contain", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())
        answer.assert_not_called()

    def test_failed_queries_return_a_nonzero_exit_code(self):
        for state in (State.FAILED, State.WRITE_FAILED):
            record = {"state": state, "answer": "Could not answer.", "tool_calls": [],
                      "timings": {"total": 0}, "usage": {"calls": 0, "cost_usd": 0}}
            with (self.subTest(state=state), patch("sys.argv", ["gridrag", "question"]),
                  patch.object(cli.answer, "answer", return_value=record), redirect_stdout(io.StringIO()),
                  self.assertRaises(SystemExit) as raised):
                cli.main()
            self.assertEqual(raised.exception.code, 1)
