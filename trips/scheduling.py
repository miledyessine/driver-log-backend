from datetime import datetime, timedelta

# --- Constants ---
AVG_SPEED_MPH = 55.0
FUEL_RANGE_MILES = 1000.0
FUEL_STOP_MIN = 45
PICKUP_MIN = 60
DROPOFF_MIN = 60
MAX_DRIVE_HRS = 11.0
MAX_ON_DUTY_HRS = 14.0
BREAK_AFTER_HRS = 8.0
OFF_DUTY_RESET_HRS = 10.0
CYCLE_LIMIT_HRS = 70.0
RESTART_OFF_DUTY_HRS = 34.0


def compute_schedule_for_route(route_geojson: dict, current_cycle_used_hours: float):
    """
    Generate a realistic FMCSA HOS-compliant trip schedule
    based on route distance/duration.
    """
    features = route_geojson.get("features", [])
    if not features:
        return {"schedule": [], "total_miles": 0, "estimated_drive_hours": 0}

    # --- Sum all segments for total distance and duration ---
    props = features[0]["properties"]
    segments = props.get("segments", [])
    total_meters = sum(seg["distance"] for seg in segments)
    total_seconds = sum(seg["duration"] for seg in segments)

    total_miles = total_meters / 1609.34
    est_drive_hours = total_seconds / 3600.0

    # --- Initialize schedule ---
    now = datetime.utcnow()
    t = now
    schedule = []

    miles_driven = 0.0
    driving_today = on_duty_today = driving_since_break = 0
    cycle_used = current_cycle_used_hours
    miles_until_fuel = FUEL_RANGE_MILES

    # --- Helper to append schedule entry ---
    def append(status, start, end, note=""):
        schedule.append({
            "status": status,
            "start": start.isoformat() + "Z",
            "end": end.isoformat() + "Z",
            "note": note,
            "miles_since_start": miles_driven
        })

    # --- Pre-trip inspection ---
    append("OnDutyNotDriving", t, t + timedelta(minutes=30), "Pre-trip inspection")
    t += timedelta(minutes=30)
    on_duty_today += 0.5
    cycle_used += 0.5

    # --- Drive from current location to pickup ---
    if segments:
        first_leg_distance_mi = segments[0]["distance"] / 1609.34
        hours_to_pickup = first_leg_distance_mi / AVG_SPEED_MPH
        append("Driving", t, t + timedelta(hours=hours_to_pickup),
               f"Drive {first_leg_distance_mi:.0f} mi to pickup")
        t += timedelta(hours=hours_to_pickup)
        miles_driven += first_leg_distance_mi
        driving_since_break += hours_to_pickup
        driving_today += hours_to_pickup
        on_duty_today += hours_to_pickup
        cycle_used += hours_to_pickup

    # --- Pickup cargo ---
    append("OnDutyNotDriving", t, t + timedelta(minutes=PICKUP_MIN), "Pickup cargo")
    t += timedelta(minutes=PICKUP_MIN)
    on_duty_today += PICKUP_MIN / 60
    cycle_used += PICKUP_MIN / 60

    # --- Remaining distance after pickup ---
    remaining_miles = sum(seg["distance"] for seg in segments[1:]) / 1609.34

    # --- Driving simulation ---
    while remaining_miles > 0:
        # Mandatory 30 min break after 8 hours driving
        if driving_since_break >= BREAK_AFTER_HRS:
            append("OffDuty", t, t + timedelta(minutes=30),
                   "30 min mandatory break (after 8 hrs driving)")
            t += timedelta(minutes=30)
            driving_since_break = 0
            continue

        # Max drive/on-duty rules
        if driving_today >= MAX_DRIVE_HRS or on_duty_today >= MAX_ON_DUTY_HRS:
            if remaining_miles > 50:
                s1 = min(7, MAX_ON_DUTY_HRS - on_duty_today)
                sb_start, sb_end = t, t + timedelta(hours=s1)
                append("Sleeper", sb_start, sb_end, "Sleeper berth (split rest)")
                t = sb_end
                driving_today = on_duty_today = driving_since_break = 0
                cycle_used += s1

                s2 = min(3, OFF_DUTY_RESET_HRS)
                if remaining_miles > 100:
                    rest_start, rest_end = t, t + timedelta(hours=s2)
                    append("OffDuty", rest_start, rest_end,
                           "Off-duty completion of split rest")
                    t = rest_end
                    cycle_used += s2
            else:
                reset_start, reset_end = t, t + timedelta(hours=OFF_DUTY_RESET_HRS)
                append("OffDuty", reset_start, reset_end,
                       "10 hr off-duty reset (11/14 hr rule)")
                t = reset_end
                cycle_used += OFF_DUTY_RESET_HRS

            driving_today = on_duty_today = driving_since_break = 0
            continue

        # Cycle limit check
        if cycle_used >= CYCLE_LIMIT_HRS:
            append("OffDuty", t, t + timedelta(hours=RESTART_OFF_DUTY_HRS),
                   "34 hr restart (70 hr / 8-day rule)")
            t += timedelta(hours=RESTART_OFF_DUTY_HRS)
            cycle_used = 0
            continue

        # Driving leg
        miles_this_leg = min(remaining_miles, AVG_SPEED_MPH)
        hours_this_leg = miles_this_leg / AVG_SPEED_MPH
        hours_this_leg = min(hours_this_leg, MAX_DRIVE_HRS - driving_today,
                             MAX_ON_DUTY_HRS - on_duty_today)

        drive_start, drive_end = t, t + timedelta(hours=hours_this_leg)
        append("Driving", drive_start, drive_end, f"Drive {miles_this_leg:.0f} mi")
        t = drive_end

        remaining_miles -= miles_this_leg
        miles_driven += miles_this_leg
        driving_today += hours_this_leg
        on_duty_today += hours_this_leg
        driving_since_break += hours_this_leg
        cycle_used += hours_this_leg
        miles_until_fuel -= miles_this_leg

        # Fuel stop
        if miles_until_fuel <= 0 and remaining_miles > 0:
            fuel_start, fuel_end = t, t + timedelta(minutes=FUEL_STOP_MIN)
            append("OnDutyNotDriving", fuel_start, fuel_end, "Fuel stop")
            t = fuel_end
            on_duty_today += FUEL_STOP_MIN / 60
            cycle_used += FUEL_STOP_MIN / 60
            miles_until_fuel = FUEL_RANGE_MILES

    # --- Dropoff & Post-trip ---
    append("OnDutyNotDriving", t, t + timedelta(minutes=DROPOFF_MIN), "Unload cargo")
    t += timedelta(minutes=DROPOFF_MIN)
    append("OffDuty", t, t + timedelta(hours=OFF_DUTY_RESET_HRS),
           "10 hr rest after trip")

    return {
        "schedule": schedule,
        "total_miles": round(total_miles, 2),
        "estimated_drive_hours": round(est_drive_hours, 2)
    }
