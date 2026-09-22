from src.config import ZoneConfig
from src.zones import distance_to_target, haversine_m, within_zone


def test_haversine_zero_for_same_point():
    assert haversine_m(32.0768, 34.7742, 32.0768, 34.7742) == 0


def test_haversine_known_distance_roughly_correct():
    # Dizengoff Square to Rothschild/Allenby corner is roughly 1.5-2km.
    d = haversine_m(32.0768, 34.7742, 32.0645, 34.7719)
    assert 1000 < d < 2500


def test_distance_to_target_none_when_zone_inactive():
    zone = ZoneConfig()  # no target configured
    assert distance_to_target(32.0, 34.8, zone) is None


def test_distance_to_target_computes_when_active():
    zone = ZoneConfig(target_lat=32.0768, target_lon=34.7742, max_distance_meters=1000)
    assert distance_to_target(32.0768, 34.7742, zone) == 0


def test_within_zone_true_under_cutoff():
    zone = ZoneConfig(target_lat=32.0768, target_lon=34.7742, max_distance_meters=1000)
    assert within_zone(500, zone) is True


def test_within_zone_false_over_cutoff():
    zone = ZoneConfig(target_lat=32.0768, target_lon=34.7742, max_distance_meters=1000)
    assert within_zone(1500, zone) is False


def test_within_zone_false_when_distance_unknown():
    zone = ZoneConfig(target_lat=32.0768, target_lon=34.7742, max_distance_meters=1000)
    assert within_zone(None, zone) is False


def test_within_zone_false_when_zone_inactive():
    zone = ZoneConfig()
    assert within_zone(100, zone) is False
