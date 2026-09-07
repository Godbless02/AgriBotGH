import unittest
from unittest.mock import Mock, patch

import requests

import app as app_module
from services.weather_service import FORECAST_URL, GEOCODING_URL, WeatherService


def location_payload():
    return {
        "results": [
            {"name": "Kumasi", "country": "United States", "country_code": "US", "latitude": 35.0, "longitude": -80.0},
            {"name": "Kumasi", "admin1": "Ashanti", "country": "Ghana", "country_code": "GH", "latitude": 6.6885, "longitude": -1.6244},
        ]
    }


def forecast_payload():
    return {
        "timezone": "Africa/Accra",
        "current": {
            "time": "2026-08-30T10:00", "temperature_2m": 28.4,
            "relative_humidity_2m": 74, "precipitation": 0.2,
            "wind_speed_10m": 9.6, "weather_code": 2,
        },
        "daily": {
            "time": ["2026-08-30", "2026-08-31", "2026-09-01"],
            "weather_code": [2, 61, 3],
            "temperature_2m_max": [30, 29, 31],
            "temperature_2m_min": [21, 20, 21],
            "precipitation_probability_max": [35, 70, 20],
            "precipitation_sum": [0.3, 8.4, 0],
        },
    }


def response_with(payload):
    response = Mock()
    response.status_code = 200
    response.url = "https://example.test/open-meteo"
    response.headers = {}
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


def http_error_response(status, *, retry_after=None):
    response = Mock(status_code=status, url="https://example.test/open-meteo")
    response.headers = {} if retry_after is None else {"Retry-After": retry_after}
    response.raise_for_status.side_effect = requests.HTTPError(
        f"HTTP {status}", response=response
    )
    return response


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class WeatherServiceTests(unittest.TestCase):
    def test_fresh_cache_avoids_repeat_provider_calls_and_returns_defensive_copies(self):
        clock = FakeClock()
        session = Mock()
        session.get.side_effect = [
            response_with(location_payload()), response_with(forecast_payload())
        ]
        service = WeatherService(session=session, clock=clock)

        first = service.get_weather("Kumasi")
        first["current"]["temperature"] = -999
        second = service.get_weather("  KUMASI  ")

        self.assertEqual(session.get.call_count, 2)
        self.assertEqual(second["current"]["temperature"], 28.4)
        self.assertFalse(second["stale"])
        self.assertEqual(second["cache_status"], "fresh")

    def test_geocoding_cache_ttl_and_forecast_refresh_use_fake_time(self):
        clock = FakeClock()
        session = Mock()
        refreshed = forecast_payload()
        refreshed["current"]["temperature_2m"] = 29.5
        session.get.side_effect = [
            response_with(location_payload()),
            response_with(forecast_payload()),
            response_with(refreshed),
            response_with(location_payload()),
            response_with(refreshed),
        ]
        service = WeatherService(session=session, clock=clock)

        service.get_weather("Kumasi")
        clock.advance(601)
        refreshed_result = service.get_weather("kumasi")
        self.assertEqual(refreshed_result["current"]["temperature"], 29.5)
        self.assertEqual(
            [call.args[0] for call in session.get.call_args_list],
            [GEOCODING_URL, FORECAST_URL, FORECAST_URL],
        )

        clock.advance(24 * 60 * 60)
        after_geocode_expiry = service.get_weather("KUMASI")
        self.assertTrue(after_geocode_expiry["success"])
        self.assertEqual(
            [call.args[0] for call in session.get.call_args_list].count(GEOCODING_URL),
            2,
        )

    def test_forecast_cache_key_reuses_resolved_coordinates(self):
        session = Mock()
        session.get.side_effect = [response_with(forecast_payload())]
        service = WeatherService(session=session)
        first_place = {
            "name": "Kumasi", "country": "Ghana", "country_code": "GH",
            "latitude": 6.6885001, "longitude": -1.6244001,
        }
        alias_place = {
            "name": "Kumasi, Ghana", "country": "Ghana", "country_code": "GH",
            "latitude": 6.6885, "longitude": -1.6244,
        }
        service.fetch_weather(first_place)
        service.fetch_weather(alias_place)
        self.assertEqual(session.get.call_count, 1)

    def test_expired_forecast_refresh_success_replaces_cached_value(self):
        clock = FakeClock()
        session = Mock()
        newer = forecast_payload()
        newer["current"]["temperature_2m"] = 31
        session.get.side_effect = [
            response_with(location_payload()), response_with(forecast_payload()),
            response_with(newer),
        ]
        service = WeatherService(session=session, clock=clock)
        service.get_weather("Kumasi")
        clock.advance(601)
        result = service.get_weather("Kumasi")
        self.assertEqual(result["current"]["temperature"], 31.0)
        self.assertFalse(result["stale"])
        self.assertEqual(session.get.call_count, 3)

    def test_rate_limit_is_classified_and_cooldown_blocks_repeat_calls(self):
        clock = FakeClock()
        session = Mock()
        session.get.side_effect = [
            response_with(location_payload()), http_error_response(429)
        ]
        service = WeatherService(session=session, clock=clock)

        first = service.get_weather("Kumasi")
        second = service.get_weather("kumasi")
        self.assertEqual(first["code"], "rate_limited")
        self.assertEqual(second["code"], "rate_limited")
        self.assertEqual(session.get.call_count, 2)
        self.assertNotIn("Open-Meteo", first["error"])

    def test_forecast_cooldown_expires_and_allows_refresh(self):
        clock = FakeClock()
        session = Mock()
        session.get.side_effect = [
            response_with(location_payload()), http_error_response(429),
            response_with(forecast_payload()),
        ]
        service = WeatherService(session=session, clock=clock)
        self.assertEqual(service.get_weather("Kumasi")["code"], "rate_limited")
        clock.advance(61)
        self.assertTrue(service.get_weather("Kumasi")["success"])
        self.assertEqual(session.get.call_count, 3)

    def test_recent_stale_forecast_is_used_for_temporary_failures(self):
        temporary_failures = (
            (http_error_response(429), "rate_limited"),
            (requests.Timeout("late"), "timeout"),
            (requests.ConnectionError("down"), "service_unavailable"),
            (http_error_response(503), "api_http_error"),
        )
        for failure, expected_reason in temporary_failures:
            with self.subTest(reason=expected_reason):
                clock = FakeClock()
                session = Mock()
                session.get.side_effect = [
                    response_with(location_payload()),
                    response_with(forecast_payload()),
                    failure,
                ]
                service = WeatherService(session=session, clock=clock)
                original = service.get_weather("Kumasi")
                clock.advance(601)
                stale = service.get_weather("Kumasi")
                self.assertTrue(stale["success"])
                self.assertTrue(stale["stale"])
                self.assertEqual(stale["cache_status"], "stale")
                self.assertEqual(stale["stale_reason"], expected_reason)
                self.assertEqual(stale["current"], original["current"])

    def test_too_old_forecast_is_never_used_after_rate_limit(self):
        clock = FakeClock()
        session = Mock()
        session.get.side_effect = [
            response_with(location_payload()), response_with(forecast_payload()),
            http_error_response(429),
        ]
        service = WeatherService(session=session, clock=clock)
        service.get_weather("Kumasi")
        clock.advance(3601)
        result = service.get_weather("Kumasi")
        self.assertFalse(result["success"])
        self.assertEqual(result["code"], "rate_limited")

    def test_unknown_location_never_uses_an_unrelated_stale_forecast(self):
        clock = FakeClock()
        session = Mock()
        session.get.side_effect = [
            response_with(location_payload()), response_with(forecast_payload()),
            response_with({"results": []}),
        ]
        service = WeatherService(session=session, clock=clock)
        service.get_weather("Kumasi")
        clock.advance(601)
        result = service.get_weather("Unknown Farm")
        self.assertFalse(result["success"])
        self.assertEqual(result["code"], "location_not_found")

    def test_malformed_forecast_is_not_cached(self):
        session = Mock()
        session.get.side_effect = [
            response_with(location_payload()),
            response_with({"current": {}, "daily": {}}),
            response_with(forecast_payload()),
        ]
        service = WeatherService(session=session)
        self.assertEqual(service.get_weather("Kumasi")["code"], "invalid_response")
        self.assertTrue(service.get_weather("Kumasi")["success"])
        self.assertEqual(
            [call.args[0] for call in session.get.call_args_list].count(FORECAST_URL),
            2,
        )

    def test_retry_after_is_respected_defaulted_and_capped(self):
        cases = (("120", 120), ("invalid", 60), ("9999", 300))
        for header, expected in cases:
            with self.subTest(header=header):
                clock = FakeClock()
                session = Mock()
                session.get.return_value = http_error_response(429, retry_after=header)
                service = WeatherService(session=session, clock=clock)
                result = service.get_weather("Kumasi")
                self.assertEqual(result["code"], "rate_limited")
                self.assertEqual(service._cooldown_until["geocoding"], expected)

    def test_geocoding_cache_is_lru_bounded(self):
        def place(name, latitude):
            return {"results": [{
                "name": name, "country": "Ghana", "country_code": "GH",
                "latitude": latitude, "longitude": -1,
            }]}

        session = Mock()
        session.get.side_effect = [
            response_with(place("Accra", 5.5)),
            response_with(place("Tamale", 9.4)),
            response_with(place("Kumasi", 6.6)),
            response_with(place("Tamale", 9.4)),
        ]
        service = WeatherService(session=session, geocoding_cache_size=2)
        service.search_location("Accra")
        service.search_location("Tamale")
        service.search_location("Accra")  # refresh Accra recency
        service.search_location("Kumasi")
        service.search_location("Tamale")
        self.assertEqual(session.get.call_count, 4)
        self.assertEqual(len(service._geocoding_cache), 2)

    def test_weather_cache_is_lru_bounded(self):
        session = Mock()
        session.get.side_effect = [
            response_with(forecast_payload()), response_with(forecast_payload()),
            response_with(forecast_payload()),
        ]
        service = WeatherService(session=session, weather_cache_size=2)
        places = [
            {"name": name, "country": "Ghana", "country_code": "GH", "latitude": lat, "longitude": -1}
            for name, lat in (("Accra", 5.5), ("Tamale", 9.4), ("Kumasi", 6.6))
        ]
        for item in places:
            service.fetch_weather(item)
        self.assertEqual(len(service._weather_cache), 2)
        self.assertNotIn(service._forecast_cache_key(places[0], "Africa/Accra"), service._weather_cache)

    def test_success_prefers_ghana_and_returns_current_and_three_days(self):
        session = Mock()
        session.get.side_effect = [response_with(location_payload()), response_with(forecast_payload())]
        result = WeatherService(session=session).get_weather("  Kumasi  ")

        self.assertTrue(result["success"])
        self.assertEqual(result["location"]["country"], "Ghana")
        self.assertEqual(result["location"]["timezone"], "Africa/Accra")
        self.assertEqual(result["current"]["rain_probability"], 35.0)
        self.assertEqual(len(result["forecast"]), 3)
        self.assertEqual(session.get.call_args_list[0].args[0], GEOCODING_URL)
        self.assertEqual(session.get.call_args_list[1].args[0], FORECAST_URL)

    def test_every_location_is_dynamically_geocoded(self):
        session = Mock()
        accra = {"results": [{"name": "Accra", "country": "Ghana", "country_code": "GH", "latitude": 5.56, "longitude": -0.21}]}
        tamale = {"results": [{"name": "Tamale", "country": "Ghana", "country_code": "GH", "latitude": 9.40, "longitude": -0.84}]}
        session.get.side_effect = [response_with(accra), response_with(forecast_payload()), response_with(tamale), response_with(forecast_payload())]
        service = WeatherService(session=session)

        accra_result = service.get_weather("Accra")
        tamale_result = service.get_weather("Tamale")

        self.assertEqual(accra_result["location"]["latitude"], 5.56)
        self.assertEqual(tamale_result["location"]["latitude"], 9.40)
        geocoding_queries = [call.kwargs["params"]["name"] for call in session.get.call_args_list if call.args[0] == GEOCODING_URL]
        self.assertEqual(geocoding_queries, ["Accra", "Tamale"])

    def test_ghana_collision_preference_does_not_override_foreign_queries(self):
        service = WeatherService(session=Mock())
        tarkwa_results = [
            {"name": "Tarkwa", "country": "Elsewhere", "country_code": "XX", "latitude": 1, "longitude": 1},
            {"name": "Tarkwa", "country": "Ghana", "country_code": "GH", "latitude": 5.3, "longitude": -2.0},
        ]
        paris_results = [
            {"name": "Paris", "country": "France", "country_code": "FR", "latitude": 48.86, "longitude": 2.35},
            {"name": "Paris", "country": "Ghana", "country_code": "GH", "latitude": 7, "longitude": -1},
        ]

        self.assertEqual(service._select_location("Tarkwa", tarkwa_results)["country_code"], "GH")
        self.assertEqual(service._select_location("Paris", paris_results)["country_code"], "FR")
        self.assertEqual(service._select_location("Paris, Ghana", paris_results)["country_code"], "GH")

    def test_empty_and_too_long_locations_are_rejected_without_network(self):
        session = Mock()
        service = WeatherService(session=session)
        self.assertEqual(service.get_weather("  ")["code"], "empty_location")
        self.assertEqual(service.get_weather("x" * 101)["code"], "invalid_location")
        session.get.assert_not_called()

    def test_unknown_location_returns_friendly_error(self):
        session = Mock()
        session.get.return_value = response_with({"results": []})
        result = WeatherService(session=session).get_weather("No Such Farm")
        self.assertFalse(result["success"])
        self.assertEqual(result["code"], "location_not_found")

    def test_timeout_and_transport_failure_are_contained(self):
        for failure, code in ((requests.Timeout("late"), "timeout"), (requests.ConnectionError("down"), "service_unavailable")):
            with self.subTest(code=code):
                session = Mock()
                session.get.side_effect = failure
                result = WeatherService(session=session).get_weather("Kumasi")
                self.assertEqual(result["code"], code)
                self.assertNotIn("late", result["error"])
                self.assertNotIn("down", result["error"])

    def test_http_failure_is_not_misreported_as_location_not_found(self):
        session = Mock()
        response = Mock(status_code=503, url=GEOCODING_URL)
        response.raise_for_status.side_effect = requests.HTTPError("provider down", response=response)
        session.get.return_value = response
        result = WeatherService(session=session).get_weather("Accra")
        self.assertEqual(result["code"], "api_http_error")
        self.assertNotIn("find that location", result["error"])

    def test_invalid_json_and_incomplete_weather_are_contained(self):
        bad_json = response_with({})
        bad_json.json.side_effect = ValueError("broken")
        session = Mock()
        session.get.return_value = bad_json
        self.assertEqual(WeatherService(session=session).get_weather("Kumasi")["code"], "invalid_response")

        session = Mock()
        session.get.side_effect = [response_with(location_payload()), response_with({"current": {}, "daily": {}})]
        self.assertEqual(WeatherService(session=session).get_weather("Kumasi")["code"], "invalid_response")


class WeatherEndpointTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()

    def test_missing_location_is_400(self):
        response = self.client.get("/api/weather")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["code"], "empty_location")

    def test_success_is_returned_as_json(self):
        service = Mock()
        service.get_weather.return_value = {"success": True, "location": {"name": "Kumasi"}}
        with patch.object(app_module, "WEATHER_SERVICE", service):
            response = self.client.get("/api/weather?location=Kumasi")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["location"]["name"], "Kumasi")
        service.get_weather.assert_called_once_with("Kumasi")

    def test_stale_success_is_http_200(self):
        service = Mock()
        service.get_weather.return_value = {
            "success": True, "stale": True, "cache_status": "stale",
            "location": {"name": "Kumasi"},
        }
        with patch.object(app_module, "WEATHER_SERVICE", service):
            response = self.client.get("/api/weather?location=Kumasi")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["stale"])

    def test_rate_limit_without_stale_result_is_http_503(self):
        service = Mock()
        service.get_weather.return_value = {
            "success": False,
            "error": "Weather information is temporarily rate-limited. Please try again shortly.",
            "code": "rate_limited",
        }
        with patch.object(app_module, "WEATHER_SERVICE", service):
            response = self.client.get("/api/weather?location=Kumasi")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["code"], "rate_limited")

    def test_service_errors_have_stable_http_statuses(self):
        cases = (("location_not_found", 404), ("timeout", 504), ("api_http_error", 502), ("service_unavailable", 503), ("invalid_response", 502))
        for code, expected_status in cases:
            with self.subTest(code=code):
                service = Mock()
                service.get_weather.return_value = {"success": False, "error": "Friendly message", "code": code}
                with patch.object(app_module, "WEATHER_SERVICE", service):
                    response = self.client.get("/api/weather?location=Kumasi")
                self.assertEqual(response.status_code, expected_status)
                self.assertEqual(response.get_json()["error"], "Friendly message")


if __name__ == "__main__":
    unittest.main()
