from rest_framework.decorators import api_view
from rest_framework.response import Response
import requests, os
from datetime import datetime
from .scheduling import compute_schedule_for_route

@api_view(["POST"])
def plan_trip(request):
    """
    Calls OpenRouteService Directions API to compute a real route
    between the current, pickup, and dropoff locations.
    """
    data = request.data
    print("Received trip data:", data)

    try:
        # 1. Extract coordinates
        coords = [
            [data["current_location"]["lng"], data["current_location"]["lat"]],
            [data["pickup_location"]["lng"], data["pickup_location"]["lat"]],
            [data["dropoff_location"]["lng"], data["dropoff_location"]["lat"]],
        ]

        # 2. Get your API key
        ors_key = os.getenv("ORS_API_KEY")
        if not ors_key:
            return Response({"error": "ORS_API_KEY not found"}, status=500)

        # 3. Call ORS Directions API
        url = "https://api.openrouteservice.org/v2/directions/driving-car/geojson"
        headers = {"Authorization": ors_key, "Content-Type": "application/json"}
        payload = {"coordinates": coords}

        res = requests.post(url, json=payload, headers=headers)
        if res.status_code != 200:
            print(res.text)
            return Response({"error": "ORS request failed", "details": res.text}, status=500)

        route_data = res.json()
        
        
        schedule = compute_schedule_for_route(route_data, data.get("current_cycle_used_hours", 0))
        
        props = route_data["features"][0]["properties"]["segments"][0]
        
        response_data = {
            "route": route_data,
            "summary": {
                "distance_km": round(props["distance"] / 1000, 2),
                "duration_hr": round(props["duration"] / 3600, 2),
            },
            "schedule": schedule,
        }
        return Response(response_data)



    except Exception as e:
        print("Error:", e)
        return Response({"error": str(e)}, status=500)
