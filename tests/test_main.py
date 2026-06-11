import datetime as dt
from email.message import EmailMessage
import os
import unittest
from unittest.mock import patch

import main


def route_to(code):
    return {
        "departureAirport": {"code": "DUB"},
        "arrivalAirport": {"code": code},
    }


class RyanairSourceTests(unittest.TestCase):
    def test_ryanair_route_filter_uses_configured_direct_destinations(self):
        routes = [
            route_to("BUD"),
            route_to("CPH"),
            route_to("KRK"),
            route_to("BGY"),
            route_to("MXP"),
            route_to("RIX"),
            route_to("ACE"),
        ]

        result = main.filter_ryanair_destination_airports("DUB", routes, main.DESTINATION_AIRPORTS)

        self.assertEqual(result, ["BGY", "BUD", "CPH", "KRK", "MXP", "RIX"])
        self.assertNotIn("LIN", result)
        self.assertNotIn("ACE", result)

    def test_ryanair_fare_normalization_reuses_trip_filters(self):
        fare = {
            "outbound": {
                "departureAirport": {"iataCode": "DUB"},
                "arrivalAirport": {
                    "iataCode": "BUD",
                    "city": {"name": "Budapest"},
                },
                "departureDate": "2026-09-05T08:00:00",
                "arrivalDate": "2026-09-05T11:55:00",
                "flightNumber": "FR1025",
                "price": {"value": 39.99},
            },
            "inbound": {
                "departureAirport": {"iataCode": "BUD"},
                "arrivalAirport": {"iataCode": "DUB"},
                "departureDate": "2026-09-07T12:00:00",
                "arrivalDate": "2026-09-07T14:10:00",
                "flightNumber": "FR1026",
                "price": {"value": 49.99},
            },
            "summary": {
                "price": {
                    "value": 89.98,
                    "currencyCode": "EUR",
                },
            },
        }

        deal = main.normalize_ryanair_fare(fare)
        detailed = main.add_filter_details(deal, dt.date(2026, 5, 30), "Budapest 2026")

        self.assertEqual(deal["source"], "ryanair")
        self.assertEqual(deal["route"], "DUB - BUD")
        self.assertEqual(deal["dates"], "Sat 5 Sep - Mon 7 Sep")
        self.assertEqual(deal["price"], "EUR 89.98")
        self.assertEqual(deal["price_value"], 89.98)
        self.assertEqual(deal["source_key"], "ryanair:DUB-BUD:2026-09-05T08:00:00:2026-09-07T12:00:00:89.98")
        self.assertTrue(detailed["eligible"])
        self.assertEqual(detailed["nights"], 2)
        self.assertEqual(detailed["days_off"], 1)
        self.assertEqual(detailed["destination"], "Budapest")

    def test_ryanair_digest_sorts_by_price_and_limits_results(self):
        deals = [
            {
                "dates": "Sat 5 Sep - Mon 7 Sep",
                "price": "EUR 90.00",
                "price_value": 90.0,
                "airline": "Ryanair",
                "stops": "Non-stop",
                "route": "DUB - BUD",
                "duration": "FR1025 / FR1026",
                "nights": 2,
                "days_off": 1,
            },
            {
                "dates": "Sat 6 Jun - Mon 8 Jun",
                "price": "EUR 40.00",
                "price_value": 40.0,
                "airline": "Ryanair",
                "stops": "Non-stop",
                "route": "DUB - KRK",
                "duration": "FR1901 / FR1902",
                "nights": 2,
                "days_off": 1,
            },
            {
                "dates": "Sat 3 Oct - Mon 5 Oct",
                "price": "EUR 120.00",
                "price_value": 120.0,
                "airline": "Ryanair",
                "stops": "Non-stop",
                "route": "DUB - RIX",
                "duration": "FR1976 / FR1977",
                "nights": 2,
                "days_off": 1,
            },
        ]

        message = main.build_ryanair_digest(deals, limit=2)

        self.assertIn("Ryanair Fare Digest", message)
        self.assertLess(message.find("EUR 40.00"), message.find("EUR 90.00"))
        self.assertNotIn("EUR 120.00", message)
        self.assertIn("Showing 2 cheapest matching fare(s)", message)

    def test_ryanair_source_selection_does_not_require_gmail_credentials(self):
        env = {
            "FLIGHT_SOURCES": "ryanair",
            "DRY_RUN": "true",
        }

        with patch.dict(os.environ, env, clear=True):
            with patch.object(main, "run_gmail_source", side_effect=AssertionError("gmail should not run")):
                with patch.object(main, "run_ryanair_source") as run_ryanair:
                    main.run_configured_sources()

        run_ryanair.assert_called_once_with(dry_run=True)


class GmailAlertParserTests(unittest.TestCase):
    def test_google_flights_parser_keeps_existing_row_format(self):
        body = (
            "Hello, We've found some great prices for one-week trips in July, "
            "from Dublin to Copenhagen. Sun 5 Jul - Sun 12 Jul From \u00a380 "
            "View Ryanair \u00b7 Non-stop \u00b7 DUB - CPH \u00b7 2 hrs 35 min"
        )

        deals = main.parse_flight_deals(body)

        self.assertEqual(deals, [{
            "dates": "Sun 5 Jul - Sun 12 Jul",
            "price": "\u00a380",
            "airline": "Ryanair",
            "stops": "Non-stop",
            "route": "DUB - CPH",
            "duration": "2 hrs 35 min",
        }])

    def test_google_flights_parser_handles_sept_and_compact_save_price(self):
        body = (
            "Hello, We've found some great prices for one-week trips in September, "
            "from Dublin to Copenhagen. 1-week trips in September 6-9 days "
            "Round trip Sun 20 Sept - Sat 26 Sept SAVE 50%From \u00a380 "
            "View Ryanair \u00b7 Non-stop \u00b7 DUB - CPH \u00b7 2 hrs 35 min"
        )

        deals = main.parse_flight_deals(
            body,
            subject="Your tracked route: Dublin to Copenhagen flights from \u00a380",
            from_header="Google Flights <noreply-travel@google.com>",
        )

        self.assertEqual(len(deals), 1)
        self.assertEqual(deals[0]["dates"], "Sun 20 Sept - Sat 26 Sept")
        self.assertEqual(deals[0]["price"], "\u00a380")
        self.assertEqual(deals[0]["airline"], "Ryanair")
        self.assertEqual(deals[0]["stops"], "Non-stop")
        self.assertEqual(deals[0]["route"], "DUB - CPH")
        self.assertEqual(deals[0]["duration"], "2 hrs 35 min")

    def test_google_flights_parser_handles_real_markdown_view_link(self):
        body = (
            "Sun 5 Jul \u2013 Sun 12 Jul\n\n"
            "SAVE 66%From \u00a354\n\n"
            "[View](https://example.com)\n\n"
            "Ryanair \u00b7 Non-stop \u00b7 DUB\u2013CPH \u00b7 3 hrs"
        )

        deals = main.parse_flight_deals(
            body,
            subject="Your tracked route: Dublin to Copenhagen flights from \u00a354",
            from_header="Google Flights <noreply-travel@google.com>",
        )

        self.assertEqual(deals, [{
            "dates": "Sun 5 Jul - Sun 12 Jul",
            "price": "\u00a354",
            "airline": "Ryanair",
            "stops": "Non-stop",
            "route": "DUB-CPH",
            "duration": "3 hrs",
        }])

    def test_skyscanner_price_alert_parses_summary_deal(self):
        body = (
            "Skyscanner Price Alert. Prices changed for Dublin to Copenhagen flights. "
            "Your tracked trip is now from \u00a388. Travel dates: 5 Sept - 7 Sept. "
            "Open Skyscanner to view the latest fares."
        )

        deals = main.parse_flight_deals(
            body,
            subject="Price Alert: Dublin to Copenhagen from \u00a388",
            from_header="Skyscanner <pricealerts@skyscanner.net>",
        )

        self.assertEqual(deals, [{
            "dates": "5 Sept - 7 Sept",
            "price": "\u00a388",
            "airline": "Skyscanner",
            "stops": "Price alert",
            "route": "Dublin -> Copenhagen",
            "duration": "Tracked route",
        }])

    def test_skyscanner_price_alert_reuses_existing_eligibility_filters(self):
        body = (
            "Skyscanner Price Alert. Prices changed for Dublin to Copenhagen flights. "
            "Your tracked trip is now from \u00a388. Travel dates: 5 Sept - 7 Sept."
        )
        deals = main.parse_flight_deals(
            body,
            subject="Price Alert: Dublin to Copenhagen from \u00a388",
            from_header="Skyscanner <pricealerts@skyscanner.net>",
        )

        matching_deals, checked_deals = main.filter_deals(deals, f"Price Alert: Dublin to Copenhagen\n{body}")

        self.assertEqual(len(matching_deals), 1)
        self.assertTrue(checked_deals[0]["eligible"])
        self.assertEqual(checked_deals[0]["destination"], "Copenhagen")
        self.assertEqual(checked_deals[0]["nights"], 2)
        self.assertEqual(checked_deals[0]["days_off"], 1)

    def test_skyscanner_real_alert_parses_multiple_price_cards(self):
        body = skyscanner_real_alert_body()

        deals = main.parse_flight_deals(
            body,
            subject="\u2708\ufe0f Latest prices for your flights",
            from_header="Skyscanner <no-reply@sender.skyscanner.com>",
        )

        self.assertEqual(
            [(deal["route"], deal["dates"], deal["price"], deal["duration"]) for deal in deals],
            [
                ("Dublin -> Budapest", "12 Jun - 14 Jun", "\u00a3220", "Price went up"),
                ("Dublin -> Copenhagen", "19 Jun - 21 Jun", "\u00a3125", "Price went down"),
                ("Dublin -> Krakow", "19 Jun - 21 Jun", "\u00a3158", "Price went up"),
                ("Dublin -> Milan", "19 Jun - 21 Jun", "\u00a3127", "Price went up"),
            ],
        )

    def test_named_route_destination_uses_each_deal_route_before_email_context(self):
        body = skyscanner_real_alert_body()
        deals = main.parse_flight_deals(
            body,
            subject="\u2708\ufe0f Latest prices for your flights",
            from_header="Skyscanner <no-reply@sender.skyscanner.com>",
        )

        detailed = [
            main.add_filter_details(dict(deal), dt.date(2026, 6, 11), body)
            for deal in deals
        ]

        self.assertEqual(
            {deal["route"]: deal["destination"] for deal in detailed},
            {
                "Dublin -> Budapest": "Budapest",
                "Dublin -> Copenhagen": "Copenhagen",
                "Dublin -> Krakow": "Krakow",
                "Dublin -> Milan": "Milan",
            },
        )

    def test_non_parseable_skyscanner_alert_is_marked_read_without_notification(self):
        message = EmailMessage()
        message["Subject"] = "Skyscanner Price Alert"
        message["From"] = "Skyscanner <pricealerts@skyscanner.net>"
        message.set_content("Prices changed, but this message has no route, date range, or price.")

        fake_imap = FakeImap(message)

        env = {
            "GMAIL_USER": "user@example.com",
            "GMAIL_APP_PASSWORD": "abcd efgh ijkl mnop",
            "GMAIL_LABEL": "Holidays/Flight alerts",
            "TELEGRAM_BOT_TOKEN": "telegram-token",
            "TELEGRAM_CHAT_ID": "telegram-chat",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch.object(main, "connect_to_gmail", return_value=fake_imap):
                with patch.object(main, "send_telegram_message", side_effect=AssertionError("should not notify")):
                    main.run_gmail_source()

        self.assertEqual(fake_imap.stored_flags, [(b"1", "+FLAGS", "\\Seen")])
        self.assertTrue(fake_imap.logged_out)

    def test_gmail_source_checks_known_alert_sender_fallbacks_after_empty_label(self):
        message = EmailMessage()
        message["Subject"] = "Your tracked route: Dublin to Copenhagen flights from \u00a354"
        message["From"] = "Google Flights <noreply-travel@google.com>"
        message.set_content(
            "Fri 19 Jun - Sun 21 Jun From \u00a354 "
            "View Ryanair \u00b7 Non-stop \u00b7 DUB - CPH \u00b7 3 hrs"
        )
        fake_imap = FallbackFakeImap({
            "fallback-google": message,
        })

        env = {
            "GMAIL_USER": "user@example.com",
            "GMAIL_APP_PASSWORD": "abcd efgh ijkl mnop",
            "GMAIL_LABEL": "Holidays/Flight alerts",
            "TELEGRAM_BOT_TOKEN": "telegram-token",
            "TELEGRAM_CHAT_ID": "telegram-chat",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch.object(main, "connect_to_gmail", return_value=fake_imap):
                with patch.object(main, "send_telegram_message") as send_telegram:
                    main.run_gmail_source()

        self.assertEqual(send_telegram.call_count, 1)
        self.assertIn(("fallback-google", "+FLAGS", "\\Seen"), fake_imap.stored_flags)
        self.assertIn(("UNSEEN",), fake_imap.search_args)
        self.assertIn(
            ("UNSEEN", "FROM", '"noreply-travel@google.com"'),
            fake_imap.search_args,
        )
        self.assertIn(
            ("UNSEEN", "FROM", '"no-reply@sender.skyscanner.com"', "SUBJECT", '"Latest prices for your flights"'),
            fake_imap.search_args,
        )


class FakeImap:
    def __init__(self, message):
        self.message = message
        self.stored_flags = []
        self.logged_out = False

    def select(self, mailbox):
        self.selected_mailbox = mailbox
        return "OK", [b"1"]

    def search(self, *args):
        self.search_args = args
        if args != (None, "UNSEEN"):
            return "OK", [b""]
        return "OK", [b"1"]

    def fetch(self, num, query):
        self.fetch_args = (num, query)
        return "OK", [(b"1", self.message.as_bytes())]

    def store(self, num, operation, flag):
        self.stored_flags.append((num, operation, flag))
        return "OK", []

    def logout(self):
        self.logged_out = True
        return "OK", []


class FallbackFakeImap:
    def __init__(self, messages):
        self.messages = messages
        self.selected_mailbox = None
        self.search_args = []
        self.stored_flags = []
        self.logged_out = False

    def select(self, mailbox):
        self.selected_mailbox = mailbox.strip('"')
        return "OK", []

    def search(self, charset, *criteria):
        self.search_args.append(criteria)
        if criteria == ("UNSEEN", "FROM", '"noreply-travel@google.com"'):
            return "OK", [b"fallback-google"]
        return "OK", [b""]

    def fetch(self, num, query):
        key = num.decode("utf-8") if isinstance(num, bytes) else str(num)
        return "OK", [(num, self.messages[key].as_bytes())]

    def store(self, num, operation, flag):
        key = num.decode("utf-8") if isinstance(num, bytes) else str(num)
        self.stored_flags.append((key, operation, flag))
        return "OK", []

    def logout(self):
        self.logged_out = True
        return "OK", []


def skyscanner_real_alert_body():
    return (
        "Latest prices for your flights\n\n"
        "Your Price Alert\n\n"
        "[Budapest](https://example.com/budapest)\n\n"
        "Dublin to Budapest\n\n"
        "12 Jun - 14 Jun\n\n"
        "Economy\n\n"
        "Was \u00a3172\n\n"
        "\u00a3220\n\n"
        "Total per traveller\n\n"
        "This price has just gone up\n\n"
        "[View flights](https://example.com/budapest-flights)\n\n"
        "[Copenhagen](https://example.com/copenhagen)\n\n"
        "Dublin to Copenhagen\n\n"
        "19 Jun - 21 Jun\n\n"
        "Economy\n\n"
        "Was \u00a3142\n\n"
        "\u00a3125\n\n"
        "Total per traveller\n\n"
        "This price has just gone down\n\n"
        "[View flights](https://example.com/copenhagen-flights)\n\n"
        "[Krakow](https://example.com/krakow)\n\n"
        "Dublin to Krakow\n\n"
        "19 Jun - 21 Jun\n\n"
        "Economy\n\n"
        "Was \u00a3148\n\n"
        "\u00a3158\n\n"
        "Total per traveller\n\n"
        "This price has just gone up\n\n"
        "[View flights](https://example.com/krakow-flights)\n\n"
        "[Milan](https://example.com/milan)\n\n"
        "Dublin to Milan\n\n"
        "19 Jun - 21 Jun\n\n"
        "Economy\n\n"
        "Was \u00a3104\n\n"
        "\u00a3127\n\n"
        "Total per traveller\n\n"
        "This price has just gone up\n\n"
        "[View flights](https://example.com/milan-flights)\n\n"
        "Fares were tracked on 11 Jun 2026, 09:36 UTC."
    )


if __name__ == "__main__":
    unittest.main()
