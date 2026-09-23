import pytest

from src.config import (
    Config,
    FacebookGroup,
    LLMConfig,
    ScanWindowConfig,
    SearchConfig,
    StayConfig,
    ZoneConfig,
    load_config,
    validate,
)


def make_config(**overrides) -> Config:
    defaults = dict(
        facebook_groups=[FacebookGroup(name="g", url="https://facebook.com/groups/1")],
        posts_per_group=10,
        searches=[SearchConfig(name="default", price_min=2500, price_max=3600)],
        telegram=None,
        llm=LLMConfig(),
        zone=ZoneConfig(target_lat=32.0768, target_lon=34.7742, max_distance_meters=1000),
        stay=StayConfig(),
        scan_window=ScanWindowConfig(),
    )
    defaults.update(overrides)
    return Config(**defaults)


def test_valid_config_passes():
    validate(make_config())  # no raise


def test_empty_groups_rejected():
    with pytest.raises(SystemExit):
        validate(make_config(facebook_groups=[]))


def test_zero_posts_per_group_rejected():
    with pytest.raises(SystemExit):
        validate(make_config(posts_per_group=0))


def test_price_min_over_price_max_rejected():
    with pytest.raises(SystemExit):
        validate(make_config(searches=[SearchConfig(price_min=4000, price_max=3000)]))


def test_empty_searches_rejected():
    with pytest.raises(SystemExit):
        validate(make_config(searches=[]))


def test_duplicate_search_profile_names_rejected():
    with pytest.raises(SystemExit):
        validate(
            make_config(
                searches=[SearchConfig(name="a"), SearchConfig(name="a")]
            )
        )


def test_min_available_rooms_over_max_rejected():
    with pytest.raises(SystemExit):
        validate(
            make_config(
                searches=[SearchConfig(min_available_rooms=3, max_available_rooms=1)]
            )
        )


def test_comma_in_search_profile_name_rejected():
    with pytest.raises(SystemExit):
        validate(make_config(searches=[SearchConfig(name="Rothschild, Center")]))


def test_comma_in_neighborhood_name_rejected():
    with pytest.raises(SystemExit):
        validate(
            make_config(searches=[SearchConfig(neighborhoods=["Florentin", "Rothschild, Center"])])
        )


def test_telegram_bot_token_set_alone_rejected(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    with pytest.raises(SystemExit):
        validate(make_config())


def test_telegram_chat_id_set_alone_rejected(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    with pytest.raises(SystemExit):
        validate(make_config())


def test_telegram_both_set_passes(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    validate(make_config())  # no raise


def test_telegram_neither_set_passes(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    validate(make_config())  # no raise


def test_multiple_distinct_profiles_pass():
    validate(
        make_config(
            searches=[
                SearchConfig(name="single room", min_available_rooms=1, max_available_rooms=1),
                SearchConfig(name="two rooms", min_available_rooms=2),
            ]
        )
    )


def test_zero_max_distance_rejected_when_zone_active():
    with pytest.raises(SystemExit):
        validate(
            make_config(
                zone=ZoneConfig(target_lat=32.0, target_lon=34.7, max_distance_meters=0)
            )
        )


def test_inactive_zone_skips_distance_validation():
    validate(make_config(zone=ZoneConfig()))  # no target configured — no raise


def test_out_of_range_lat_rejected():
    with pytest.raises(SystemExit):
        validate(
            make_config(zone=ZoneConfig(target_lat=200, target_lon=34.7, max_distance_meters=1000))
        )


def test_negative_llm_budget_rejected():
    with pytest.raises(SystemExit):
        validate(make_config(llm=LLMConfig(daily_budget=-1)))


def test_zero_min_stay_days_rejected():
    with pytest.raises(SystemExit):
        validate(make_config(stay=StayConfig(min_days=0)))


def test_zero_search_window_days_rejected():
    with pytest.raises(SystemExit):
        validate(make_config(stay=StayConfig(search_window_days=0)))


def test_zero_initial_lookback_days_rejected():
    with pytest.raises(SystemExit):
        validate(make_config(scan_window=ScanWindowConfig(initial_lookback_days=0)))


def test_scan_window_config_defaults():
    assert ScanWindowConfig().initial_lookback_days == 4


def test_stay_config_defaults():
    stay = StayConfig()
    assert stay.min_days == 14
    assert stay.search_window_days == 21


def test_llm_config_active_requires_key_and_enabled():
    assert LLMConfig(enabled=True, api_key="x").active is True
    assert LLMConfig(enabled=True, api_key=None).active is False
    assert LLMConfig(enabled=False, api_key="x").active is False


def test_zone_config_active_requires_both_coordinates():
    assert ZoneConfig(target_lat=32.0, target_lon=None).active is False
    assert ZoneConfig(target_lat=32.0, target_lon=34.7).active is True


def test_all_neighborhoods_is_the_union_across_profiles():
    config = make_config(
        searches=[
            SearchConfig(name="single room", neighborhoods=["florentin", "rothschild"]),
            SearchConfig(name="two rooms", neighborhoods=["rothschild", "habima"]),
        ]
    )
    assert config.all_neighborhoods == ["florentin", "rothschild", "habima"]


def test_search_config_defaults():
    profile = SearchConfig()
    assert profile.name == "default"
    assert profile.min_available_rooms is None
    assert profile.max_available_rooms is None


_BASE_YAML = """
facebook_groups:
  - name: "g"
    url: "https://facebook.com/groups/1"
posts_per_group: 10
"""


def test_load_config_reads_multiple_named_profiles(tmp_path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    path = tmp_path / "config.yaml"
    path.write_text(
        _BASE_YAML
        + """
searches:
  - name: "single room"
    emoji: "🟢"
    price_min: 2500
    price_max: 3600
    min_available_rooms: 1
    max_available_rooms: 1
  - name: "two rooms"
    emoji: "🔵"
    price_min: 5000
    min_available_rooms: 2
"""
    )
    config = load_config(path)
    assert [p.name for p in config.searches] == ["single room", "two rooms"]
    assert config.searches[0].emoji == "\U0001F7E2"
    assert config.searches[1].min_available_rooms == 2


def test_load_config_supports_legacy_single_search_block(tmp_path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    path = tmp_path / "config.yaml"
    path.write_text(
        _BASE_YAML
        + """
search:
  price_min: 2500
  price_max: 3600
"""
    )
    config = load_config(path)
    assert len(config.searches) == 1
    assert config.searches[0].name == "default"


def test_load_config_reads_stay_block(tmp_path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    path = tmp_path / "config.yaml"
    path.write_text(
        _BASE_YAML
        + """
stay:
  min_days: 10
  search_window_days: 30
"""
    )
    config = load_config(path)
    assert config.stay.min_days == 10
    assert config.stay.search_window_days == 30


def test_load_config_stay_defaults_without_a_stay_block(tmp_path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    path = tmp_path / "config.yaml"
    path.write_text(_BASE_YAML)
    config = load_config(path)
    assert config.stay.min_days == 14
    assert config.stay.search_window_days == 21


def test_load_config_reads_scan_window_block(tmp_path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    path = tmp_path / "config.yaml"
    path.write_text(
        _BASE_YAML
        + """
scan_window:
  initial_lookback_days: 7
"""
    )
    config = load_config(path)
    assert config.scan_window.initial_lookback_days == 7


def test_load_config_scan_window_defaults_without_a_block(tmp_path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    path = tmp_path / "config.yaml"
    path.write_text(_BASE_YAML)
    config = load_config(path)
    assert config.scan_window.initial_lookback_days == 4
