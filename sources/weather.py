"""
Weather data source — Open-Meteo (completely free, no API key required).
Provides current conditions, forecasts, and historical data for any location.
"""

import requests

_GEO_API = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST_API = "https://api.open-meteo.com/v1/forecast"
_HISTORICAL_API = "https://archive-api.open-meteo.com/v1/archive"
_HEADERS = {"User-Agent": "PolyMarket-Research-Bot/1.0"}

# WMO weather code descriptions
_WMO_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
    77: "Snow grains", 80: "Slight showers", 81: "Moderate showers", 82: "Violent showers",
    85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Thunderstorm with heavy hail",
}


def _geocode(city: str) -> dict | None:
    """Resolve city name to lat/lon."""
    try:
        r = requests.get(_GEO_API, params={"name": city, "count": 1, "language": "en"}, headers=_HEADERS, timeout=10)
        r.raise_for_status()
        results = r.json().get("results", [])
        if results:
            return {
                "lat": results[0]["latitude"],
                "lon": results[0]["longitude"],
                "name": results[0].get("name"),
                "country": results[0].get("country"),
            }
        return None
    except Exception:
        return None


def get_weather_forecast(city: str, days: int = 7) -> dict:
    """
    Weather forecast for a city (1-14 days).
    Returns daily max/min temp (°C), precipitation (mm), and weather description.
    Useful for markets related to weather events, record temperatures, rainfall, etc.
    """
    location = _geocode(city)
    if not location:
        return {"error": f"Could not geocode city: '{city}'. Try a major city name."}

    try:
        r = requests.get(
            _FORECAST_API,
            params={
                "latitude": location["lat"],
                "longitude": location["lon"],
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode,windspeed_10m_max",
                "forecast_days": min(days, 14),
                "timezone": "auto",
            },
            headers=_HEADERS,
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return {"error": str(e)}

    daily = data.get("daily", {})
    dates = daily.get("time", [])
    forecast = []
    for i, date in enumerate(dates):
        wcode = (daily.get("weathercode") or [None] * (i + 1))[i]
        forecast.append({
            "date": date,
            "temp_max_c": (daily.get("temperature_2m_max") or [None] * (i + 1))[i],
            "temp_min_c": (daily.get("temperature_2m_min") or [None] * (i + 1))[i],
            "precipitation_mm": (daily.get("precipitation_sum") or [None] * (i + 1))[i],
            "wind_max_kmh": (daily.get("windspeed_10m_max") or [None] * (i + 1))[i],
            "condition": _WMO_CODES.get(wcode, f"WMO code {wcode}"),
        })

    return {
        "city": f"{location['name']}, {location['country']}",
        "lat": location["lat"],
        "lon": location["lon"],
        "forecast_days": len(forecast),
        "forecast": forecast,
    }


def get_current_weather(city: str) -> dict:
    """
    Current weather conditions for a city.
    Returns temperature, apparent temperature, precipitation, wind speed, and conditions.
    """
    location = _geocode(city)
    if not location:
        return {"error": f"Could not geocode city: '{city}'"}

    try:
        r = requests.get(
            _FORECAST_API,
            params={
                "latitude": location["lat"],
                "longitude": location["lon"],
                "current": "temperature_2m,apparent_temperature,precipitation,weathercode,windspeed_10m,relativehumidity_2m",
                "timezone": "auto",
            },
            headers=_HEADERS,
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return {"error": str(e)}

    curr = data.get("current", {})
    wcode = curr.get("weathercode")
    return {
        "city": f"{location['name']}, {location['country']}",
        "time": curr.get("time"),
        "temperature_c": curr.get("temperature_2m"),
        "feels_like_c": curr.get("apparent_temperature"),
        "precipitation_mm": curr.get("precipitation"),
        "wind_kmh": curr.get("windspeed_10m"),
        "humidity_pct": curr.get("relativehumidity_2m"),
        "condition": _WMO_CODES.get(wcode, f"WMO code {wcode}"),
    }
