"""Preview detection for JSON and plain TXT ingest files."""

from __future__ import annotations

import unittest

from foxengine.services.format_detect import (
    LINE_VALUE_HEADER,
    analyze_text_payload,
)


class FormatDetectPreviewTest(unittest.TestCase):
    def test_json_array_samples_limited_objects(self) -> None:
        rows = [{"mail": f"user{i}@example.com", "phone": f"+1555000{i:04d}"} for i in range(40)]
        data = __import__("json").dumps(rows).encode()
        d = analyze_text_payload("leads.json", data)
        self.assertEqual(d.format, "jsonl")
        self.assertLessEqual(len(d.sample_rows), 12)
        self.assertIn("mail", d.headers or [])
        self.assertIn("phone", d.headers or [])

    def test_txt_one_value_per_line(self) -> None:
        data = b"user1@example.com\nuser2@example.com\n"
        d = analyze_text_payload("emails.txt", data)
        self.assertEqual(d.format, "txt")
        self.assertEqual(d.headers, [LINE_VALUE_HEADER])
        self.assertEqual(len(d.sample_rows), 2)
        self.assertEqual(d.sample_rows[0][LINE_VALUE_HEADER], "user1@example.com")

    def test_jsonl_includes_headers_from_sample(self) -> None:
        lines = "\n".join(
            [
                '{"email":"a@example.com","name":"Ann"}',
                '{"email":"b@example.com","name":"Bob"}',
            ]
        )
        d = analyze_text_payload("leads.jsonl", lines.encode())
        self.assertEqual(d.format, "jsonl")
        self.assertEqual(set(d.headers or []), {"email", "name"})
        self.assertEqual(len(d.sample_rows), 2)


if __name__ == "__main__":
    unittest.main()
