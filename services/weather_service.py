"""Resilient Open-Meteo geocoding and forecast integration for AgriBotGH."""

from __future__ import annotations

import logging
import re
import time
from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass
from threading import RLock
from typing import Any

import requests


LOGGER = logging.getLogger(__name__)
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
DEFAULT_TIMEOUT_SECONDS = 8
MAX_LOCATION_LENGTH = 100
DEFAULT_GEOCODING_TTL_SECONDS = 24 * 60 * 60
DEFAULT_WEATHER_FRESH_TTL_SECONDS = 10 * 60
DEFAULT_WEATHER_STALE_MAX_AGE_SECONDS = 60 * 60
DEFAULT_GEOCODING_CACHE_SIZE = 128
DEFAULT_WEATHER_CACHE_SIZE = 64
DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS = 60
MAX_RATE_LIMIT_COOLDOWN_SECONDS = 300
GHANA_LOCATION_HINTS = {
    "accra", "kumasi", "sunnyani", "sunyani", "wenchi", "techiman",
    "tamale", "cape coast", "ho", "koforidua", "bolgatanga", "wa",
    "takoradi", "sekondi", "tarkwa", "tema", "obuasi", "yendi", "savelugu",
}

CURRENT_FIELDS = (
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "wind_speed_10m",
    "weather_code",
)
DAILY_FIELDS = (
    "weather_code",
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_probability_max",
    "precipitation_sum",
)

WEATHER_DESCRIPTIONS = {
    0: "Clear sky",
    1: "Mostly clear",
    2: "Partly cloudy",
    3: "Cloudy",
    45: "Foggy",
    48: "Foggy",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Heavy drizzle",
    56: "Freezing drizzle",
    57: "Freezing drizzle",
    61: "Light rain",
    63: "Rain",
    65: "Heavy rain",
    66: "Freezing rain",
    67: "Freezing rain",
    71: "Light snow",
    73: "Snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Light rain showers",
    81: "Rain showers",
    82: "Heavy rain showers",
    85: "Snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with hail",
    99: "Thunderstorm with hail",
}


@dataclass
class WeatherServiceError(Exception):
    code: str
    user_message: str
    technical_message: str = ""
    temporary: bool = False

    def __str__(self) -> str:
        return self.technical_message or self.user_message


class WeatherService:
    """Retrieve location and weather data without leaking transport errors."""

    def __init__(
        self,
        session: Any = None,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
        *,
        clock: Any = time.monotonic,
        geocoding_ttl: float = DEFAULT_GEOCODING_TTL_SECONDS,
        weather_fresh_ttl: float = DEFAULT_WEATHER_FRESH_TTL_SECONDS,
        weather_stale_max_age: float = DEFAULT_WEATHER_STALE_MAX_AGE_SECONDS,
        geocoding_cache_size: int = DEFAULT_GEOCODING_CACHE_SIZE,
        weather_cache_size: int = DEFAULT_WEATHER_CACHE_SIZE,
        rate_limit_cooldown: float = DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS,
    ):
        self.session = session or requests.Session()
        self.timeout = timeout
        self._clock = clock
        self.geocoding_ttl = geocoding_ttl
        self.weather_fresh_ttl = weather_fresh_ttl
        self.weather_stale_max_age = weather_stale_max_age
        self.geocoding_cache_size = max(1, geocoding_cache_size)
        self.weather_cache_size = max(1, weather_cache_size)
        self.rate_limit_cooldown = rate_limit_cooldown
        self._geocoding_cache: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()
        self._weather_cache: OrderedDict[tuple[Any, ...], tuple[float, dict[str, Any]]] = OrderedDict()
        self._cooldown_until: dict[str, float] = {}
        self._cache_lock = RLock()

    def get_weather(self, location: str) -> dict[str, Any]:
        """Return a structured success/error payload for a location name."""
        try:
            place = self.search_location(location)
            return self.fetch_weather(place)
        except WeatherServiceError as error:
            LOGGER.warning(
                "Weather request failed (%s): %s", error.code, str(error)
            )
            return {
                "success": False,
                "error": error.user_message,
                "code": error.code,
            }
        except Exception:
            LOGGER.exception("Unexpected weather service failure")
            return {
                "success": False,
                "error": "Weather information is temporarily unavailable.",
                "code": "unexpected_error",
            }

    def search_location(self, location: str) -> dict[str, Any]:
        if not isinstance(location, str) or not location.strip():
            raise WeatherServiceError(
                "empty_location", "Please enter a town, city, or farming area."
            )
        query = " ".join(location.split())
        if len(query) > MAX_LOCATION_LENGTH:
            raise WeatherServiceError(
                "invalid_location", "Location must not exceed 100 characters."
            )
        cache_key = query.casefold()
        cached = self._cache_get(
            self._geocoding_cache, cache_key, self.geocoding_ttl
        )
        if cached is not None:
            return cached
        payload = self._request_json(
            GEOCODING_URL,
            {"name": query, "count": 10, "language": "en", "format": "json"},
            "geocoding",
        )
        results = payload.get("results")
        if results is None:
            results = []
        if not isinstance(results, list):
            raise WeatherServiceError(
                "invalid_response",
                "The location service returned an invalid response.",
                "Geocoding results is not a list",
            )
        valid = [item for item in results if self._valid_location_result(item)]
        if not valid:
            raise WeatherServiceError(
                "location_not_found",
                "I couldn't find that location. Check the spelling or add the region or country.",
            )
        selected = self._select_location(query, valid)
        place = {
            "name": selected["name"],
            "admin1": selected.get("admin1"),
            "country": selected.get("country", ""),
            "country_code": selected.get("country_code", ""),
            "latitude": float(selected["latitude"]),
            "longitude": float(selected["longitude"]),
            "timezone": selected.get("timezone"),
        }
        self._cache_put(
            self._geocoding_cache,
            cache_key,
            place,
            self.geocoding_cache_size,
        )
        return deepcopy(place)

    def fetch_weather(self, place: dict[str, Any]) -> dict[str, Any]:
        is_ghana = str(place.get("country_code", "")).upper() == "GH"
        timezone = "Africa/Accra" if is_ghana else "auto"
        cache_key = self._forecast_cache_key(place, timezone)
        cached_entry = self._cache_get_with_age(
            self._weather_cache, cache_key, self.weather_stale_max_age
        )
        if cached_entry is not None:
            cached, age = cached_entry
            if not self._valid_cached_weather(cached):
                self._cache_delete(self._weather_cache, cache_key)
                cached_entry = None
            elif age <= self.weather_fresh_ttl:
                cached.update({"stale": False, "cache_status": "fresh"})
                cached.pop("stale_reason", None)
                return cached
        try:
            payload = self._request_json(
                FORECAST_URL,
                {
                    "latitude": place["latitude"],
                    "longitude": place["longitude"],
                    "current": ",".join(CURRENT_FIELDS),
                    "daily": ",".join(DAILY_FIELDS),
                    "timezone": timezone,
                    "forecast_days": 3,
                },
                "forecast",
            )
        except WeatherServiceError as error:
            if cached_entry is not None and error.temporary:
                cached, _age = cached_entry
                cached.update({
                    "stale": True,
                    "cache_status": "stale",
                    "stale_reason": error.code,
                })
                return cached
            raise
        current = payload.get("current")
        daily = payload.get("daily")
        if not isinstance(current, dict) or not isinstance(daily, dict):
            raise WeatherServiceError(
                "invalid_response",
                "The weather service returned incomplete information.",
                "Missing current or daily object",
            )
        self._require_fields(current, CURRENT_FIELDS, "current")
        self._require_fields(daily, ("time", *DAILY_FIELDS), "daily")
        forecast = self._build_forecast(daily)
        if not forecast:
            raise WeatherServiceError(
                "invalid_response",
                "The weather forecast is currently incomplete.",
                "Daily arrays contain no complete rows",
            )
        current_code = self._integer_code(current["weather_code"])
        rain_probability = forecast[0]["precipitation_probability"]
        result = {
            "success": True,
            "location": {
                "name": place["name"],
                "admin1": place.get("admin1"),
                "country": place.get("country", ""),
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "timezone": "Africa/Accra" if is_ghana else payload.get("timezone"),
            },
            "current": {
                "time": current.get("time"),
                "temperature": self._number(current["temperature_2m"], "temperature"),
                "humidity": self._number(current["relative_humidity_2m"], "humidity"),
                "precipitation": self._number(current["precipitation"], "precipitation"),
                "wind_speed": self._number(current["wind_speed_10m"], "wind speed"),
                "weather_code": current_code,
                "condition": WEATHER_DESCRIPTIONS.get(current_code, "Current conditions"),
                "rain_probability": rain_probability,
            },
            "forecast": forecast,
            "units": {
                "temperature": "°C",
                "humidity": "%",
                "precipitation": "mm",
                "wind_speed": "km/h",
                "precipitation_probability": "%",
            },
            "source": "Open-Meteo",
            "guidance": "Weather forecasts can change. Check again before time-sensitive farm work.",
            "stale": False,
            "cache_status": "fresh",
        }
        self._cache_put(
            self._weather_cache,
            cache_key,
            result,
            self.weather_cache_size,
        )
        return deepcopy(result)

    def _request_json(
        self, url: str, params: dict[str, Any], operation: str
    ) -> dict[str, Any]:
        if self._cooldown_active(operation):
            raise WeatherServiceError(
                "rate_limited",
                "Weather information is temporarily rate-limited. Please try again shortly.",
                f"Open-Meteo {operation} request skipped during cooldown",
                temporary=True,
            )
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
        except requests.Timeout as error:
            raise WeatherServiceError(
                "timeout",
                "The weather service took too long to respond. Please try again.",
                f"Open-Meteo {operation} timed out: {error}",
                temporary=True,
            ) from error
        except requests.HTTPError as error:
            status = getattr(error.response, "status_code", "unknown")
            if status == 429:
                self._start_cooldown(
                    operation, self._retry_after_seconds(error.response)
                )
                raise WeatherServiceError(
                    "rate_limited",
                    "Weather information is temporarily rate-limited. Please try again shortly.",
                    f"Open-Meteo {operation} returned HTTP 429",
                    temporary=True,
                ) from error
            raise WeatherServiceError(
                "api_http_error",
                "The weather provider returned an error. Please try again shortly.",
                f"Open-Meteo {operation} returned HTTP {status}: {error}",
                temporary=isinstance(status, int) and status >= 500,
            ) from error
        except requests.RequestException as error:
            raise WeatherServiceError(
                "service_unavailable",
                "Weather information is temporarily unavailable. Please try again.",
                f"Open-Meteo {operation} request failed: {error}",
                temporary=True,
            ) from error
        LOGGER.debug(
            "Open-Meteo %s succeeded: status=%s url=%s",
            operation,
            response.status_code,
            response.url,
        )
        try:
            payload = response.json()
        except (ValueError, TypeError) as error:
            raise WeatherServiceError(
                "invalid_response",
                "The weather service returned an invalid response.",
                f"Open-Meteo {operation} returned non-JSON data",
            ) from error
        if not isinstance(payload, dict):
            raise WeatherServiceError(
                "invalid_response",
                "The weather service returned an invalid response.",
                f"Open-Meteo {operation} payload is not an object",
            )
        return payload

    def _cache_get(
        self, cache: OrderedDict, key: Any, max_age: float
    ) -> Any:
        entry = self._cache_get_with_age(cache, key, max_age)
        return entry[0] if entry is not None else None

    def _cache_get_with_age(
        self, cache: OrderedDict, key: Any, max_age: float
    ) -> tuple[Any, float] | None:
        now = self._clock()
        with self._cache_lock:
            entry = cache.get(key)
            if entry is None:
                return None
            stored_at, value = entry
            age = max(0.0, now - stored_at)
            if age > max_age:
                cache.pop(key, None)
                return None
            cache.move_to_end(key)
            return deepcopy(value), age

    def _cache_put(
        self, cache: OrderedDict, key: Any, value: Any, maximum_size: int
    ) -> None:
        with self._cache_lock:
            cache[key] = (self._clock(), deepcopy(value))
            cache.move_to_end(key)
            while len(cache) > maximum_size:
                cache.popitem(last=False)

    def _cache_delete(self, cache: OrderedDict, key: Any) -> None:
        with self._cache_lock:
            cache.pop(key, None)

    def _cooldown_active(self, operation: str) -> bool:
        now = self._clock()
        with self._cache_lock:
            until = self._cooldown_until.get(operation, 0.0)
            if until <= now:
                self._cooldown_until.pop(operation, None)
                return False
            return True

    def _start_cooldown(self, operation: str, seconds: float) -> None:
        with self._cache_lock:
            self._cooldown_until[operation] = self._clock() + seconds

    def _retry_after_seconds(self, response: Any) -> float:
        headers = getattr(response, "headers", None)
        raw_value = headers.get("Retry-After") if hasattr(headers, "get") else None
        try:
            seconds = float(raw_value)
            if seconds < 0:
                raise ValueError
        except (TypeError, ValueError):
            seconds = self.rate_limit_cooldown
        return min(max(1.0, seconds), MAX_RATE_LIMIT_COOLDOWN_SECONDS)

    @staticmethod
    def _forecast_cache_key(
        place: dict[str, Any], timezone: str
    ) -> tuple[float, float, str]:
        return (
            round(float(place["latitude"]), 5),
            round(float(place["longitude"]), 5),
            timezone,
        )

    @staticmethod
    def _valid_cached_weather(value: Any) -> bool:
        return (
            isinstance(value, dict)
            and value.get("success") is True
            and isinstance(value.get("location"), dict)
            and isinstance(value.get("current"), dict)
            and isinstance(value.get("forecast"), list)
            and bool(value["forecast"])
        )

    @staticmethod
    def _valid_location_result(item: Any) -> bool:
        return (
            isinstance(item, dict)
            and isinstance(item.get("name"), str)
            and isinstance(item.get("latitude"), (int, float))
            and isinstance(item.get("longitude"), (int, float))
            and not isinstance(item.get("latitude"), bool)
            and not isinstance(item.get("longitude"), bool)
        )

    @staticmethod
    def _select_location(query: str, results: list[dict[str, Any]]) -> dict[str, Any]:
        """Select a geocoder result; this is never a coordinate allowlist.

        Explicit Ghana queries and well-known ambiguous Ghanaian place names get
        a Ghana preference. All other queries retain Open-Meteo's relevance
        order, so a foreign location is not silently changed to Ghana.
        """
        normalized = re.sub(r"[^a-z0-9 ]", " ", query.casefold())
        normalized = " ".join(normalized.split())
        query_name = re.sub(r"\bghana\b", " ", normalized)
        query_name = " ".join(query_name.split())
        ghana_preferred = (
            "ghana" in normalized
            or query_name in GHANA_LOCATION_HINTS
        )

        indexed_results = list(enumerate(results))

        def rank(indexed_item: tuple[int, dict[str, Any]]) -> tuple[int, int, int]:
            index, item = indexed_item
            name = re.sub(r"[^a-z0-9 ]", " ", item["name"].casefold())
            exact = int(" ".join(name.split()) == query_name)
            ghana = int(str(item.get("country_code", "")).upper() == "GH")
            return exact, ghana if ghana_preferred else 0, -index

        return max(indexed_results, key=rank)[1]

    @staticmethod
    def _require_fields(payload: dict[str, Any], fields: tuple[str, ...], label: str) -> None:
        missing = [field for field in fields if field not in payload]
        if missing:
            raise WeatherServiceError(
                "invalid_response",
                "The weather service returned incomplete information.",
                f"Missing {label} fields: {', '.join(missing)}",
            )

    def _build_forecast(self, daily: dict[str, Any]) -> list[dict[str, Any]]:
        arrays = {field: daily[field] for field in ("time", *DAILY_FIELDS)}
        if any(not isinstance(value, list) for value in arrays.values()):
            raise WeatherServiceError(
                "invalid_response",
                "The weather forecast has an unexpected format.",
                "One or more daily fields is not an array",
            )
        row_count = min(len(value) for value in arrays.values())
        forecast = []
        for index in range(row_count):
            code = self._integer_code(arrays["weather_code"][index])
            forecast.append({
                "date": arrays["time"][index],
                "temperature_max": self._number(arrays["temperature_2m_max"][index], "maximum temperature"),
                "temperature_min": self._number(arrays["temperature_2m_min"][index], "minimum temperature"),
                "precipitation_probability": self._number(arrays["precipitation_probability_max"][index], "rain probability"),
                "precipitation_sum": self._number(arrays["precipitation_sum"][index], "rain total"),
                "weather_code": code,
                "condition": WEATHER_DESCRIPTIONS.get(code, "Forecast conditions"),
            })
        return forecast

    @staticmethod
    def _number(value: Any, field: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise WeatherServiceError(
                "invalid_response",
                "The weather service returned incomplete information.",
                f"Invalid numeric weather field: {field}",
            )
        return float(value)

    @staticmethod
    def _integer_code(value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise WeatherServiceError(
                "invalid_response",
                "The weather service returned incomplete information.",
                "Invalid weather code",
            )
        return int(value)


def format_service_test(payload: dict[str, Any]) -> str:
    """Return readable standalone-test output without hard-coded values."""
    if not payload.get("success"):
        return f"Weather service test failed: {payload.get('error', 'Unknown error')}"
    location = payload["location"]
    current = payload["current"]
    return "\n".join((
        "=" * 50,
        "AgriBotGH WEATHER SERVICE TEST",
        "=" * 50,
        f"Location: {location['name']}, {location['country']}",
        f"Latitude: {location['latitude']}",
        f"Longitude: {location['longitude']}",
        "",
        f"Current temperature: {current['temperature']} °C",
        f"Humidity: {current['humidity']} %",
        f"Wind speed: {current['wind_speed']} km/h",
        f"Precipitation: {current['precipitation']} mm",
        f"Rain probability: {current['rain_probability']} %",
        "",
        "Weather service working successfully.",
    ))


if __name__ == "__main__":
    print(format_service_test(WeatherService().get_weather("Kumasi, Ghana")))
