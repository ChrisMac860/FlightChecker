import datetime as dt
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


if __name__ == "__main__":
    unittest.main()
