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
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


class WeatherServiceTests(unittest.TestCase):
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
