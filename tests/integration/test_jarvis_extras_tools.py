"""Integration tests for jarvis_extras write tools (mocked Garmin client)."""

import json
from unittest.mock import MagicMock

import pytest
from mcp.server.fastmcp import FastMCP

from garmin_mcp import jarvis_extras


@pytest.fixture
def app(mock_garmin_client):
    jarvis_extras.configure(mock_garmin_client)
    return jarvis_extras.register_tools(FastMCP("Test Jarvis"))


def _text(result):
    return result[0][0].text


def _resp(status=200, body=None):
    r = MagicMock(status_code=status)
    r.content = b"x" if body is not None else b""
    r.json.return_value = body
    return r


@pytest.mark.asyncio
async def test_send_scheduled_workouts(app, mock_garmin_client):
    mock_garmin_client.client.put.return_value = _resp(204)
    data = json.loads(_text(await app.call_tool("send_scheduled_workouts_to_devices", {})))
    assert data["status"] == "success"
    assert mock_garmin_client.client.put.call_args.args[1] == "/workout-service/schedule/sendtodevices"


@pytest.mark.asyncio
async def test_send_scheduled_workouts_http_error(app, mock_garmin_client):
    mock_garmin_client.client.put.return_value = _resp(500)
    assert json.loads(_text(await app.call_tool("send_scheduled_workouts_to_devices", {})))["status"] == "failed"


@pytest.mark.asyncio
async def test_create_note(app, mock_garmin_client):
    mock_garmin_client.client.post.return_value = {"id": 42}
    data = json.loads(_text(await app.call_tool(
        "create_calendar_note", {"date": "2026-11-24", "name": "Ajuste", "content": "x"})))
    assert data["note_id"] == 42
    assert mock_garmin_client.client.post.call_args.kwargs["json"]["noteName"] == "Ajuste"


@pytest.mark.asyncio
async def test_create_note_bad_date(app, mock_garmin_client):
    out = _text(await app.call_tool("create_calendar_note", {"date": "24/11", "name": "x"}))
    assert "YYYY-MM-DD" in out
    mock_garmin_client.client.post.assert_not_called()


@pytest.mark.asyncio
async def test_update_note(app, mock_garmin_client):
    mock_garmin_client.client.put.return_value = _resp(204)
    data = json.loads(_text(await app.call_tool(
        "update_calendar_note", {"note_id": 42, "date": "2026-11-25", "name": "Ajuste"})))
    assert data["status"] == "success"
    assert mock_garmin_client.client.put.call_args.args[1] == "/calendar-service/note/42"


@pytest.mark.asyncio
async def test_delete_note_requires_confirm(app, mock_garmin_client):
    data = json.loads(_text(await app.call_tool("delete_calendar_note", {"note_id": 42})))
    assert data["status"] == "preview"
    mock_garmin_client.client.delete.assert_not_called()


@pytest.mark.asyncio
async def test_delete_note(app, mock_garmin_client):
    mock_garmin_client.client.delete.return_value = _resp(204)
    data = json.loads(_text(await app.call_tool("delete_calendar_note", {"note_id": 42, "confirm": True})))
    assert data["status"] == "success"


@pytest.mark.asyncio
async def test_set_daily_goal(app, mock_garmin_client):
    mock_garmin_client.client.put.return_value = _resp(200, {"goalValue": 20})
    data = json.loads(_text(await app.call_tool(
        "set_daily_goal", {"goal_type": "floors_climbed", "value": 20, "date": "2026-11-24"})))
    assert data["status"] == "success"
    assert mock_garmin_client.client.put.call_args.args[1] == "/goal-service/goal/user/effective/floors-climbed/2026-11-24"


@pytest.mark.asyncio
async def test_set_daily_goal_rejects_type(app, mock_garmin_client):
    out = _text(await app.call_tool("set_daily_goal", {"goal_type": "STEPS", "value": 1}))
    assert "goal_type must be one of" in out
    mock_garmin_client.client.put.assert_not_called()


@pytest.mark.asyncio
async def test_set_steps_goal_manual_and_auto(app, mock_garmin_client):
    mock_garmin_client.client.connectapi.return_value = {"goalType": "STEPS", "userGoal": 0}
    mock_garmin_client.client.put.return_value = _resp(200, {})
    data = json.loads(_text(await app.call_tool("set_steps_goal", {"steps": 9000, "date": "2026-11-24"})))
    assert data["user_goal"] == 9000 and data["category"] == "manual"
    data = json.loads(_text(await app.call_tool("set_steps_goal", {"date": "2026-11-24"})))
    assert data["user_goal"] == 0 and data["category"] == "my-auto"


@pytest.mark.asyncio
async def test_copy_workout(app, mock_garmin_client):
    mock_garmin_client.client.post.return_value = {"workoutId": 9, "workoutName": "Copia"}
    data = json.loads(_text(await app.call_tool("copy_workout", {"workout_id": 5, "name": "Copia"})))
    assert data["workout_id"] == 9
    assert mock_garmin_client.client.post.call_args.kwargs["data"] == b"Copia"


@pytest.mark.asyncio
async def test_update_workout_requires_segments(app, mock_garmin_client):
    out = _text(await app.call_tool("update_workout", {"workout_id": 5, "workout_json": "{}"}))
    assert "workoutSegments" in out
    mock_garmin_client.client.put.assert_not_called()


@pytest.mark.asyncio
async def test_update_workout(app, mock_garmin_client):
    mock_garmin_client.client.put.return_value = _resp(204)
    wj = json.dumps({"workoutId": 1, "workoutSegments": [{"segmentOrder": 1}]})
    data = json.loads(_text(await app.call_tool("update_workout", {"workout_id": 5, "workout_json": wj})))
    assert data["status"] == "success"
    assert mock_garmin_client.client.put.call_args.kwargs["json"]["workoutId"] == 5


@pytest.mark.asyncio
async def test_read_tools_exception(app, mock_garmin_client):
    mock_garmin_client.client.connectapi.side_effect = Exception("boom")
    for name in ("get_effective_goals", "get_steps_goal", "get_user_settings"):
        assert "failed" in _text(await app.call_tool(name, {}))


@pytest.mark.asyncio
async def test_set_sleep_schedule(app, mock_garmin_client):
    mock_garmin_client.client.connectapi.return_value = {
        "id": 1, "userData": {}, "userSleep": {"sleepTime": 79200, "wakeTime": 21600}}
    mock_garmin_client.client.put.return_value = _resp(204)
    data = json.loads(_text(await app.call_tool("set_sleep_schedule", {"sleep_time": "00:00", "wake_time": "08:00"})))
    assert data["status"] == "success"
    sent = mock_garmin_client.client.put.call_args.kwargs["json"]
    assert sent["userSleep"]["sleepTime"] == 0 and sent["userSleep"]["wakeTime"] == 28800
    assert sent["userData"] == {}


@pytest.mark.asyncio
async def test_set_sleep_schedule_bad_time(app, mock_garmin_client):
    out = _text(await app.call_tool("set_sleep_schedule", {"sleep_time": "25:00", "wake_time": "08:00"}))
    assert "HH:MM" in out
    mock_garmin_client.client.put.assert_not_called()
