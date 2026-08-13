from core.providers.event_provider import CalendarEconomicEventProvider


class CalendarStub:
    def snapshot(self):
        return {
            "provider": "Official calendars",
            "retrieved_at": "2026-08-13T12:00:00+00:00",
            "live": True,
            "stale": False,
            "events": [
                {
                    "title": "U.S. consumer price index",
                    "category": "Inflation",
                    "date": "2026-09-01",
                    "confidence": 95,
                    "affected": [],
                    "rationale": "Inflation can move rates and equity valuations.",
                    "source": "FRED release calendar",
                    "source_url": "https://fred.stlouisfed.org/releases/calendar",
                    "source_live": True,
                },
                {"title": "Stale earnings", "source_live": True, "source_stale": True},
                {"title": "Illustrative event", "source_live": False},
            ],
        }


def test_calendar_events_are_live_traceable_and_neutral():
    snapshot = CalendarEconomicEventProvider(CalendarStub()).snapshot()

    assert snapshot["live"] is True
    assert snapshot["provider"] == "Official calendars"
    assert len(snapshot["events"]) == 1
    event = snapshot["events"][0]
    assert event["direction"] == 0
    assert event["event_date"] == "2026-09-01"
    assert event["source"] == "FRED release calendar"
    assert event["source_url"].startswith("https://fred.stlouisfed.org/")