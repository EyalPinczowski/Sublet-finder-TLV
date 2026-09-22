import pytest

from src.config import (
    Config,
    FacebookGroup,
    LLMConfig,
    SearchConfig,
    ZoneConfig,
    validate,
)


def make_config(**overrides) -> Config:
    defaults = dict(
        facebook_groups=[FacebookGroup(name="g", url="https://facebook.com/groups/1")],
        posts_per_group=10,
        search=SearchConfig(price_min=2500, price_max=3600),
        telegram=None,
        llm=LLMConfig(),
        zone=ZoneConfig(target_lat=32.0768, target_lon=34.7742, max_distance_meters=1000),
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
        validate(make_config(search=SearchConfig(price_min=4000, price_max=3000)))


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


def test_llm_config_active_requires_key_and_enabled():
    assert LLMConfig(enabled=True, api_key="x").active is True
    assert LLMConfig(enabled=True, api_key=None).active is False
    assert LLMConfig(enabled=False, api_key="x").active is False


def test_zone_config_active_requires_both_coordinates():
    assert ZoneConfig(target_lat=32.0, target_lon=None).active is False
    assert ZoneConfig(target_lat=32.0, target_lon=34.7).active is True
