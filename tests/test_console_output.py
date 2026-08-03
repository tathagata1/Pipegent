import unittest

from console_output import display_message


class ConsoleOutputTests(unittest.TestCase):
    def test_structured_reply_displays_only_message(self):
        reply = '''{
          "message": "As of 2026-08-03, you are 36 years old.",
          "completed_outputs": ["Computed age: 36"],
          "decision_summary": "Compared the dates."
        }'''

        self.assertEqual(
            display_message(reply),
            "As of 2026-08-03, you are 36 years old.",
        )

    def test_fenced_structured_reply_displays_only_message(self):
        reply = '```json\n{"message":"Done.","completed_outputs":[]}\n```'

        self.assertEqual(display_message(reply), "Done.")

    def test_plain_text_reply_is_unchanged(self):
        self.assertEqual(display_message("  A plain answer.  "), "A plain answer.")

    def test_json_without_message_is_unchanged(self):
        reply = '{"completed_outputs":["Done"]}'

        self.assertEqual(display_message(reply), reply)


if __name__ == "__main__":
    unittest.main()
