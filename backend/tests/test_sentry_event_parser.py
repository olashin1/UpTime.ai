import unittest

from app.services.sentry_event_parser import parse_sentry_event


class SentryEventParserTests(unittest.TestCase):
    def test_rejects_non_object_payload(self):
        with self.assertRaisesRegex(ValueError, "JSON object"):
            parse_sentry_event([])  # type: ignore[arg-type]

    def test_event_alert_message_shape(self):
        parsed = parse_sentry_event(
            {
                "action": "triggered",
                "data": {
                    "event": {
                        "event_id": "event-123",
                        "issue_id": "issue-456",
                        "title": "Bogus backend request observed",
                        "culprit": "app.main.me",
                        "level": "warning",
                        "environment": "local",
                        "platform": "python",
                        "project": 12345,
                        "request": {
                            "method": "GET",
                            "url": "http://localhost:8000/me",
                        },
                        "extra": {
                            "event_type": "bogus_backend_request",
                            "status_code": 401,
                            "path": "/me",
                        },
                        "tags": [["http.status_code", "401"]],
                        "web_url": "https://sentry.example/issues/issue-456",
                    },
                    "triggered_rule": "Notify via AI On-Call Webhook",
                },
            }
        )

        self.assertEqual(parsed.issue_id, "issue-456")
        self.assertEqual(parsed.error_type, "bogus_backend_request")
        self.assertEqual(parsed.request_method, "GET")
        self.assertEqual(parsed.request_path, "/me")
        self.assertEqual(parsed.status_code, 401)
        self.assertEqual(parsed.level, "warning")
        self.assertEqual(parsed.culprit, "app.main.me")

    def test_exception_shape_extracts_stacktrace(self):
        parsed = parse_sentry_event(
            {
                "data": {
                    "event": {
                        "issue_id": "issue-789",
                        "exception": {
                            "values": [
                                {
                                    "type": "ValueError",
                                    "value": "bad input",
                                    "stacktrace": {
                                        "frames": [
                                            {
                                                "filename": "app/service.py",
                                                "function": "load_item",
                                                "lineno": 42,
                                                "context_line": "raise ValueError()",
                                                "in_app": True,
                                            }
                                        ]
                                    },
                                }
                            ]
                        },
                    }
                }
            }
        )

        self.assertEqual(parsed.error_type, "ValueError")
        self.assertEqual(parsed.error_value, "bad input")
        self.assertEqual(parsed.title, "bad input")
        self.assertEqual(parsed.stacktrace_frames[0].filename, "app/service.py")
        self.assertEqual(parsed.stacktrace_frames[0].line_number, 42)


if __name__ == "__main__":
    unittest.main()
