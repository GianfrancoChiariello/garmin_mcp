"""Write tools that python-garminconnect 0.3.2 does not wrap.

Endpoints follow python-garminconnect 0.3.20, where each one is documented
(and most verified live) by the library maintainers. They are called through
the 0.3.2 HTTP client so the pinned dependency does not change.
"""

import datetime
import json
import re
from typing import Any, Optional

garmin_client = None

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")

_DAILY_GOAL_TYPES = ("INTENSITY_MINUTES", "FLOORS_CLIMBED", "HYDRATION")


def configure(client):
    global garmin_client
    garmin_client = client


def _date_or_today(value: Optional[str]) -> str:
    if value is None:
        return datetime.date.today().isoformat()
    if not _DATE_RE.match(value):
        raise ValueError(f"date must be YYYY-MM-DD, got: {value}")
    datetime.date.fromisoformat(value)
    return value


def _body(resp: Any) -> Any:
    if resp is None:
        return None
    if isinstance(resp, (dict, list)):
        return resp
    status = getattr(resp, "status_code", None)
    if status == 204 or not getattr(resp, "content", b""):
        return None
    try:
        return resp.json()
    except Exception:
        return None


def _ok(resp: Any) -> bool:
    status = getattr(resp, "status_code", 200)
    return 200 <= status < 300


def _fail(message: str, **extra: Any) -> str:
    return json.dumps({"status": "failed", "message": message, **extra}, indent=2)


def register_tools(app):
    @app.tool()
    async def send_scheduled_workouts_to_devices() -> str:
        """Push every scheduled workout in the Garmin calendar to the user's devices.

        Same as Garmin Connect's "send to devices" for the schedule. The watch
        receives them at its next sync.
        """
        try:
            resp = garmin_client.client.put(
                "connectapi", "/workout-service/schedule/sendtodevices"
            )
            if not _ok(resp):
                return _fail(f"HTTP {resp.status_code}")
            return json.dumps(
                {"status": "success", "message": "Scheduled workouts queued for the devices", "response": _body(resp)},
                indent=2,
            )
        except Exception as e:
            return _fail(f"Failed to send scheduled workouts: {e}")

    @app.tool()
    async def create_calendar_note(date: str, name: str, content: str = "") -> str:
        """Add a note to a day of the Garmin Connect calendar.

        Args:
            date: Day in YYYY-MM-DD.
            name: Note title (shown in the calendar).
            content: Optional note body.
        """
        try:
            date = _date_or_today(date)
            if not name or not name.strip():
                return _fail("name must not be empty")
            note = garmin_client.client.post(
                "connectapi",
                "/calendar-service/note",
                json={"noteName": name.strip(), "content": content, "date": date},
                api=True,
            )
            return json.dumps(
                {"status": "success", "note_id": (note or {}).get("id"), "date": date, "name": name.strip()},
                indent=2,
            )
        except Exception as e:
            return _fail(f"Failed to create calendar note: {e}")

    @app.tool()
    async def update_calendar_note(note_id: int, date: str, name: str, content: str = "") -> str:
        """Change the date, title or body of a Garmin calendar note.

        Args:
            note_id: ID returned by create_calendar_note (or seen in get_calendar_events).
            date: Day in YYYY-MM-DD (the note moves there).
            name: Note title.
            content: Note body.
        """
        try:
            date = _date_or_today(date)
            if not name or not name.strip():
                return _fail("name must not be empty")
            resp = garmin_client.client.put(
                "connectapi",
                f"/calendar-service/note/{int(note_id)}",
                json={"id": int(note_id), "noteName": name.strip(), "content": content, "date": date},
            )
            if not _ok(resp):
                return _fail(f"HTTP {resp.status_code}", note_id=note_id)
            return json.dumps({"status": "success", "note_id": note_id, "date": date}, indent=2)
        except Exception as e:
            return _fail(f"Failed to update calendar note: {e}", note_id=note_id)

    @app.tool()
    async def delete_calendar_note(note_id: int, confirm: bool = False) -> str:
        """Delete a Garmin calendar note. Cannot be undone.

        Call with confirm=false (default) to preview, then confirm=true to delete.

        Args:
            note_id: ID of the note.
            confirm: Must be true to delete.
        """
        try:
            if not confirm:
                return json.dumps(
                    {"status": "preview", "note_id": note_id, "message": "Call again with confirm=true to delete this note."},
                    indent=2,
                )
            resp = garmin_client.client.delete("connectapi", f"/calendar-service/note/{int(note_id)}")
            if not _ok(resp):
                return _fail(f"HTTP {resp.status_code}", note_id=note_id)
            return json.dumps({"status": "success", "note_id": note_id, "message": "Note deleted"}, indent=2)
        except Exception as e:
            return _fail(f"Failed to delete calendar note: {e}", note_id=note_id)

    @app.tool()
    async def get_effective_goals(date: Optional[str] = None) -> str:
        """Daily goals in effect on a day: intensity minutes, floors, hydration, weight.

        Args:
            date: Day in YYYY-MM-DD; defaults to today.
        """
        try:
            date = _date_or_today(date)
            data = garmin_client.client.connectapi(f"/goal-service/goal/user/effective/{date}")
            return json.dumps({"date": date, "goals": data}, indent=2, default=str)
        except Exception as e:
            return _fail(f"Failed to get goals: {e}")

    @app.tool()
    async def set_daily_goal(goal_type: str, value: float, date: Optional[str] = None) -> str:
        """Set a daily wellness goal.

        Args:
            goal_type: INTENSITY_MINUTES (weekly minutes), FLOORS_CLIMBED or HYDRATION (ml).
            value: New goal value (positive).
            date: Day the goal takes effect, YYYY-MM-DD; defaults to today.
        """
        try:
            goal_type = (goal_type or "").upper()
            if goal_type not in _DAILY_GOAL_TYPES:
                return _fail(f"goal_type must be one of {', '.join(_DAILY_GOAL_TYPES)}")
            if value is None or value <= 0:
                return _fail("value must be positive")
            date = _date_or_today(date)
            slug = goal_type.lower().replace("_", "-")
            resp = garmin_client.client.put(
                "connectapi",
                f"/goal-service/goal/user/effective/{slug}/{date}",
                json={"goalValue": value, "goalType": goal_type},
            )
            if not _ok(resp):
                return _fail(f"HTTP {resp.status_code}")
            return json.dumps(
                {"status": "success", "goal_type": goal_type, "value": value, "date": date, "response": _body(resp)},
                indent=2,
                default=str,
            )
        except Exception as e:
            return _fail(f"Failed to set goal: {e}")

    @app.tool()
    async def get_steps_goal(date: Optional[str] = None) -> str:
        """Step goal in effect on a day (manual or the device's automatic goal).

        Args:
            date: Day in YYYY-MM-DD; defaults to today.
        """
        try:
            date = _date_or_today(date)
            data = garmin_client.client.connectapi(
                f"/wellness-service/wellness/wellness-goals/consolidated/steps/{date}"
            )
            return json.dumps({"date": date, "goal": data}, indent=2, default=str)
        except Exception as e:
            return _fail(f"Failed to get steps goal: {e}")

    @app.tool()
    async def set_steps_goal(steps: Optional[int] = None, date: Optional[str] = None) -> str:
        """Set a manual daily step goal, or go back to the automatic goal.

        Args:
            steps: Positive step count for a manual goal; omit or 0 for the automatic goal.
            date: Day the goal takes effect, YYYY-MM-DD; defaults to today.
        """
        try:
            date = _date_or_today(date)
            url = f"/wellness-service/wellness/wellness-goals/consolidated/steps/{date}"
            current = garmin_client.client.connectapi(url)
            payload = dict(current) if isinstance(current, dict) else {"goalType": "STEPS"}
            if steps:
                if int(steps) <= 0:
                    return _fail("steps must be positive")
                payload["userGoal"] = int(steps)
                payload["userGoalCategory"] = "manual"
            else:
                payload["userGoal"] = 0
                payload["userGoalCategory"] = "my-auto"
            resp = garmin_client.client.put("connectapi", url, json=payload)
            if not _ok(resp):
                return _fail(f"HTTP {resp.status_code}")
            return json.dumps(
                {"status": "success", "date": date, "user_goal": payload["userGoal"],
                 "category": payload["userGoalCategory"], "response": _body(resp)},
                indent=2,
                default=str,
            )
        except Exception as e:
            return _fail(f"Failed to set steps goal: {e}")

    @app.tool()
    async def copy_workout(workout_id: int, name: str) -> str:
        """Duplicate a workout of the library under a new name.

        Args:
            workout_id: Workout to copy (from get_workouts).
            name: Name of the copy.
        """
        try:
            if not name or not name.strip():
                return _fail("name must not be empty")
            copy = garmin_client.client.post(
                "connectapi",
                f"/workout-service/workout/copy/{int(workout_id)}",
                data=name.strip().encode("utf-8"),
                headers={"Content-Type": "text/plain"},
                api=True,
            )
            return json.dumps(
                {"status": "success", "source_workout_id": workout_id,
                 "workout_id": (copy or {}).get("workoutId"), "name": (copy or {}).get("workoutName")},
                indent=2,
            )
        except Exception as e:
            return _fail(f"Failed to copy workout: {e}", workout_id=workout_id)

    @app.tool()
    async def update_workout(workout_id: int, workout_json: str) -> str:
        """Replace an existing workout in place, keeping its id (and its schedules).

        Garmin replaces the whole workout, so send the complete structure:
        start from get_workout_by_id's raw form or build it like upload_workout.

        Args:
            workout_id: Workout to replace.
            workout_json: Complete workout JSON (object) as a string.
        """
        try:
            payload = json.loads(workout_json) if isinstance(workout_json, str) else workout_json
            if not isinstance(payload, dict) or not payload.get("workoutSegments"):
                return _fail("workout_json must be a full workout object with workoutSegments")
            payload["workoutId"] = int(workout_id)
            resp = garmin_client.client.put(
                "connectapi", f"/workout-service/workout/{int(workout_id)}", json=payload
            )
            if not _ok(resp):
                return _fail(f"HTTP {resp.status_code}", workout_id=workout_id)
            return json.dumps({"status": "success", "workout_id": workout_id}, indent=2)
        except Exception as e:
            return _fail(f"Failed to update workout: {e}", workout_id=workout_id)

    @app.tool()
    async def get_user_settings() -> str:
        """Raw Garmin user settings (userData, sleep schedule, formats, units)."""
        try:
            data = garmin_client.client.connectapi("/userprofile-service/userprofile/user-settings")
            return json.dumps(data, indent=2, default=str)
        except Exception as e:
            return _fail(f"Failed to get user settings: {e}")

    @app.tool()
    async def set_sleep_schedule(sleep_time: str, wake_time: str) -> str:
        """Set the usual bedtime and wake time in the Garmin profile (used for sleep tracking).

        Args:
            sleep_time: Bedtime as HH:MM (24 h), e.g. "00:00".
            wake_time: Wake time as HH:MM (24 h), e.g. "08:00".
        """
        try:
            def _secs(value: str) -> int:
                m = _TIME_RE.match(value or "")
                if not m:
                    raise ValueError(f"time must be HH:MM, got: {value}")
                return int(m.group(1)) * 3600 + int(m.group(2)) * 60

            sleep_s, wake_s = _secs(sleep_time), _secs(wake_time)
            url = "/userprofile-service/userprofile/user-settings"
            current = garmin_client.client.connectapi(url)
            if not isinstance(current, dict) or "userSleep" not in current:
                return _fail("Garmin did not return the current user settings")
            payload = dict(current)
            payload["userSleep"] = {
                **(current.get("userSleep") or {}),
                "sleepTime": sleep_s,
                "wakeTime": wake_s,
                "defaultSleepTime": False,
                "defaultWakeTime": False,
            }
            resp = garmin_client.client.put("connectapi", url, json=payload)
            if not _ok(resp):
                return _fail(f"HTTP {resp.status_code}")
            return json.dumps(
                {"status": "success", "sleep_time": sleep_time, "wake_time": wake_time},
                indent=2,
            )
        except Exception as e:
            return _fail(f"Failed to set sleep schedule: {e}")

    return app
