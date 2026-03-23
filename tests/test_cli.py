"""Tests for the TradeArena CLI battle, tournament, matchmaking, and rating commands."""

from __future__ import annotations

import json
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from tradearena.cli import cli


@pytest.fixture()
def runner():
    return CliRunner()


@pytest.fixture()
def config_dir(tmp_path):
    config_dir = tmp_path / ".tradearena"
    config_dir.mkdir()
    config_file = config_dir / "config.json"
    config_file.write_text(
        json.dumps(
            {
                "api_key": "ta-test-key-1234",
                "base_url": "http://localhost:8000",
                "creator_id": "creator-abc",
            }
        )
    )
    return config_dir


def _patched(config_dir, api_mock=None):
    """Context manager that patches CONFIG_DIR, CONFIG_FILE, and optionally _api."""
    stack = ExitStack()
    stack.enter_context(patch("tradearena.cli.CONFIG_DIR", config_dir))
    stack.enter_context(patch("tradearena.cli.CONFIG_FILE", config_dir / "config.json"))
    if api_mock is not None:
        if callable(api_mock) and not isinstance(api_mock, MagicMock):
            stack.enter_context(patch("tradearena.cli._api", side_effect=api_mock))
        else:
            stack.enter_context(patch("tradearena.cli._api", return_value=api_mock))
    return stack


def _mock_response(status_code=200, json_data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = json.dumps(json_data or {})
    return resp


# ---------------------------------------------------------------------------
# battle challenge
# ---------------------------------------------------------------------------


class TestBattleChallenge:
    def test_challenge_success(self, runner, config_dir):
        resp_data = {
            "battle_id": "abc123def456",
            "creator1_id": "creator-abc",
            "creator2_id": "bot-xyz",
            "window_days": 7,
            "status": "ACTIVE",
        }
        with _patched(config_dir, _mock_response(201, resp_data)):
            result = runner.invoke(cli, ["battle", "challenge", "bot-xyz"])
        assert result.exit_code == 0
        assert "Battle created!" in result.output
        assert "abc123def456" in result.output
        assert "bot-xyz" in result.output

    def test_challenge_not_found(self, runner, config_dir):
        with _patched(config_dir, _mock_response(404, {"detail": "Not found"})):
            result = runner.invoke(cli, ["battle", "challenge", "nonexistent"])
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_challenge_conflict(self, runner, config_dir):
        with _patched(config_dir, _mock_response(409, {"detail": "Already exists"})):
            result = runner.invoke(cli, ["battle", "challenge", "bot-xyz"])
        assert result.exit_code != 0
        assert "already exists" in result.output

    def test_challenge_self(self, runner, config_dir):
        with _patched(config_dir, _mock_response(422, {"detail": "Cannot battle yourself"})):
            result = runner.invoke(cli, ["battle", "challenge", "creator-abc"])
        assert result.exit_code != 0
        assert "cannot battle against yourself" in result.output.lower()


# ---------------------------------------------------------------------------
# battle list
# ---------------------------------------------------------------------------


class TestBattleList:
    def test_list_active(self, runner, config_dir):
        resp_data = {
            "total": 1,
            "battles": [
                {
                    "battle_id": "bat-001",
                    "creator1_id": "alice",
                    "creator2_id": "bob",
                    "status": "ACTIVE",
                }
            ],
        }
        with _patched(config_dir, _mock_response(200, resp_data)):
            result = runner.invoke(cli, ["battle", "list"])
        assert result.exit_code == 0
        assert "bat-001" in result.output
        assert "alice" in result.output

    def test_list_no_battles(self, runner, config_dir):
        with _patched(config_dir, _mock_response(200, {"total": 0, "battles": []})):
            result = runner.invoke(cli, ["battle", "list"])
        assert result.exit_code == 0
        assert "No active battles" in result.output


# ---------------------------------------------------------------------------
# battle status
# ---------------------------------------------------------------------------


class TestBattleStatus:
    def test_status_active(self, runner, config_dir):
        resp_data = {
            "battle_id": "bat-001",
            "status": "ACTIVE",
            "creator1_id": "alice",
            "creator2_id": "bob",
            "window_days": 7,
            "battle_type": "MANUAL",
            "created_at": "2026-03-20T12:00:00",
        }
        with _patched(config_dir, _mock_response(200, resp_data)):
            result = runner.invoke(cli, ["battle", "status", "bat-001"])
        assert result.exit_code == 0
        assert "bat-001" in result.output
        assert "ACTIVE" in result.output
        assert "alice" in result.output

    def test_status_resolved(self, runner, config_dir):
        resp_data = {
            "battle_id": "bat-002",
            "status": "RESOLVED",
            "creator1_id": "alice",
            "creator2_id": "bob",
            "window_days": 7,
            "battle_type": "AUTO",
            "created_at": "2026-03-18T10:00:00",
            "resolved_at": "2026-03-20T10:00:00",
            "winner_id": "alice",
            "creator1_score": 0.7500,
            "creator2_score": 0.6200,
            "margin": 0.1300,
            "creator1_details": {"win_rate": 0.8, "consistency": 0.7},
            "creator2_details": {"win_rate": 0.6, "consistency": 0.5},
        }
        with _patched(config_dir, _mock_response(200, resp_data)):
            result = runner.invoke(cli, ["battle", "status", "bat-002"])
        assert result.exit_code == 0
        assert "RESOLVED" in result.output
        assert "alice" in result.output
        assert "0.7500" in result.output
        assert "0.1300" in result.output

    def test_status_not_found(self, runner, config_dir):
        with _patched(config_dir, _mock_response(404, {"detail": "Not found"})):
            result = runner.invoke(cli, ["battle", "status", "nonexistent"])
        assert result.exit_code != 0
        assert "not found" in result.output


# ---------------------------------------------------------------------------
# matchmaking join
# ---------------------------------------------------------------------------


class TestMatchmakingJoin:
    def test_join_success(self, runner, config_dir):
        resp_data = {
            "bot_id": "creator-abc",
            "queued": True,
            "message": "Joined matchmaking queue.",
        }
        with _patched(config_dir, _mock_response(200, resp_data)):
            result = runner.invoke(cli, ["matchmaking", "join"])
        assert result.exit_code == 0
        assert "Joined matchmaking queue" in result.output

    def test_join_not_found(self, runner, config_dir):
        with _patched(config_dir, _mock_response(404, {"detail": "Not found"})):
            result = runner.invoke(cli, ["matchmaking", "join"])
        assert result.exit_code != 0
        assert "not found" in result.output


# ---------------------------------------------------------------------------
# matchmaking status
# ---------------------------------------------------------------------------


class TestMatchmakingStatus:
    def test_status_success(self, runner, config_dir):
        resp_data = {
            "bot_id": "creator-abc",
            "elo": 1350,
            "matches_played": 12,
            "wins": 8,
            "losses": 3,
            "draws": 1,
        }
        with _patched(config_dir, _mock_response(200, resp_data)):
            result = runner.invoke(cli, ["matchmaking", "status"])
        assert result.exit_code == 0
        assert "1350" in result.output
        assert "Wins:" in result.output
        assert "8" in result.output


# ---------------------------------------------------------------------------
# tournament list
# ---------------------------------------------------------------------------


class TestTournamentList:
    def test_list_tournaments(self, runner, config_dir):
        resp_data = {
            "total": 2,
            "tournaments": [
                {
                    "id": "tourn-001aaaa",
                    "name": "Weekly Championship",
                    "format": "single_elimination",
                    "status": "registering",
                    "max_participants": 16,
                    "entries": [{"creator_id": "a"}, {"creator_id": "b"}],
                    "matches": [],
                },
                {
                    "id": "tourn-002bbbb",
                    "name": "Round Robin Cup",
                    "format": "round_robin",
                    "status": "in_progress",
                    "max_participants": 8,
                    "entries": [{"creator_id": "c"}],
                    "matches": [],
                },
            ],
        }
        with _patched(config_dir, _mock_response(200, resp_data)):
            result = runner.invoke(cli, ["tournament", "list"])
        assert result.exit_code == 0
        assert "Weekly Championship" in result.output
        assert "Round Robin Cup" in result.output
        assert "2/16" in result.output

    def test_list_no_tournaments(self, runner, config_dir):
        with _patched(config_dir, _mock_response(200, {"total": 0, "tournaments": []})):
            result = runner.invoke(cli, ["tournament", "list"])
        assert result.exit_code == 0
        assert "No tournaments found" in result.output

    def test_list_filter_status(self, runner, config_dir):
        with _patched(config_dir, _mock_response(200, {"total": 0, "tournaments": []})):
            result = runner.invoke(cli, ["tournament", "list", "--status", "registering"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# tournament register
# ---------------------------------------------------------------------------


class TestTournamentRegister:
    def test_register_success(self, runner, config_dir):
        resp_data = {
            "id": "tourn-001",
            "name": "Weekly Championship",
            "format": "single_elimination",
            "status": "registering",
            "max_participants": 16,
            "entries": [{"creator_id": "creator-abc", "seed": 1}],
            "matches": [],
        }
        with _patched(config_dir, _mock_response(201, resp_data)):
            result = runner.invoke(cli, ["tournament", "register", "tourn-001"])
        assert result.exit_code == 0
        assert "Registered" in result.output
        assert "Weekly Championship" in result.output

    def test_register_full_tournament(self, runner, config_dir):
        resp_data = {"detail": "Tournament is full"}
        with _patched(config_dir, _mock_response(409, resp_data)):
            result = runner.invoke(cli, ["tournament", "register", "tourn-001"])
        assert result.exit_code != 0
        assert "Tournament is full" in result.output

    def test_register_not_found(self, runner, config_dir):
        with _patched(config_dir, _mock_response(404, {"detail": "Not found"})):
            result = runner.invoke(cli, ["tournament", "register", "nonexistent"])
        assert result.exit_code != 0
        assert "not found" in result.output


# ---------------------------------------------------------------------------
# tournament bracket
# ---------------------------------------------------------------------------


class TestTournamentBracket:
    def test_bracket_display(self, runner, config_dir):
        resp_data = {
            "id": "tourn-001",
            "name": "Weekly Championship",
            "format": "single_elimination",
            "status": "in_progress",
            "current_round": 1,
            "max_participants": 4,
            "entries": [
                {"creator_id": "alice", "seed": 1, "eliminated_at": None, "points": 0},
                {"creator_id": "bob", "seed": 2, "eliminated_at": None, "points": 0},
                {
                    "creator_id": "carol",
                    "seed": 3,
                    "eliminated_at": "2026-03-20T12:00:00",
                    "points": 0,
                },
                {
                    "creator_id": "dave",
                    "seed": 4,
                    "eliminated_at": "2026-03-20T12:00:00",
                    "points": 0,
                },
            ],
            "matches": [
                {"round": 1, "match_order": 1, "battle_id": "bat-m1", "winner_bot_id": "alice"},
                {"round": 1, "match_order": 2, "battle_id": "bat-m2", "winner_bot_id": "bob"},
            ],
        }
        with _patched(config_dir, _mock_response(200, resp_data)):
            result = runner.invoke(cli, ["tournament", "bracket", "tourn-001"])
        assert result.exit_code == 0
        assert "Weekly Championship" in result.output
        assert "alice" in result.output
        assert "Round 1" in result.output
        assert "eliminated" in result.output

    def test_bracket_not_found(self, runner, config_dir):
        with _patched(config_dir, _mock_response(404, {"detail": "Not found"})):
            result = runner.invoke(cli, ["tournament", "bracket", "nonexistent"])
        assert result.exit_code != 0
        assert "not found" in result.output


# ---------------------------------------------------------------------------
# rating
# ---------------------------------------------------------------------------


class TestRating:
    def test_rating_with_rank(self, runner, config_dir):
        rating_data = {
            "bot_id": "creator-abc",
            "elo": 1450,
            "matches_played": 20,
            "wins": 14,
            "losses": 5,
            "draws": 1,
        }
        lb_data = {
            "total": 50,
            "entries": [
                {"bot_id": "top-player", "elo": 1600},
                {"bot_id": "second", "elo": 1500},
                {"bot_id": "creator-abc", "elo": 1450},
            ],
        }

        def _mock_api(cfg, method, path, **kwargs):
            if "/leaderboard/" in path:
                return _mock_response(200, lb_data)
            return _mock_response(200, rating_data)

        with _patched(config_dir, _mock_api):
            result = runner.invoke(cli, ["rating"])
        assert result.exit_code == 0
        assert "1450" in result.output
        assert "#3" in result.output
        assert "W: 14" in result.output

    def test_rating_unranked(self, runner, config_dir):
        rating_data = {
            "bot_id": "creator-abc",
            "elo": 1200,
            "matches_played": 0,
            "wins": 0,
            "losses": 0,
            "draws": 0,
        }
        lb_data = {"total": 10, "entries": []}

        def _mock_api(cfg, method, path, **kwargs):
            if "/leaderboard/" in path:
                return _mock_response(200, lb_data)
            return _mock_response(200, rating_data)

        with _patched(config_dir, _mock_api):
            result = runner.invoke(cli, ["rating"])
        assert result.exit_code == 0
        assert "1200" in result.output
        assert "unranked" in result.output


# ---------------------------------------------------------------------------
# help text
# ---------------------------------------------------------------------------


class TestHelpText:
    @pytest.mark.parametrize(
        "args",
        [
            ["battle", "--help"],
            ["battle", "challenge", "--help"],
            ["battle", "list", "--help"],
            ["battle", "status", "--help"],
            ["matchmaking", "--help"],
            ["matchmaking", "join", "--help"],
            ["matchmaking", "status", "--help"],
            ["tournament", "--help"],
            ["tournament", "list", "--help"],
            ["tournament", "register", "--help"],
            ["tournament", "bracket", "--help"],
            ["rating", "--help"],
        ],
    )
    def test_help_text(self, runner, args):
        result = runner.invoke(cli, args)
        assert result.exit_code == 0
        assert "Usage:" in result.output or "usage:" in result.output.lower()


# ---------------------------------------------------------------------------
# missing config
# ---------------------------------------------------------------------------


class TestMissingConfig:
    def test_battle_challenge_no_creator(self, runner, config_dir):
        (config_dir / "config.json").write_text(
            json.dumps({"api_key": "ta-test", "base_url": "http://localhost:8000"})
        )
        with _patched(config_dir):
            result = runner.invoke(cli, ["battle", "challenge", "bot-xyz"])
        assert result.exit_code != 0
        assert "creator_id not set" in result.output

    def test_matchmaking_join_no_api_key(self, runner, config_dir):
        (config_dir / "config.json").write_text(json.dumps({}))
        with _patched(config_dir):
            result = runner.invoke(cli, ["matchmaking", "join"])
        assert result.exit_code != 0
        assert "missing config" in result.output
