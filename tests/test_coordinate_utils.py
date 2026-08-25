import pytest
from coordinate_utils import denormalize_x, denormalize_y, normalize_x, normalize_y


def test_denormalize_x_and_y():
    assert denormalize_x(500, 1000) == 500
    assert denormalize_x(500, 1440) == 720
    assert denormalize_x(0, 1920) == 0
    assert denormalize_x(1000, 1920) == 1920

    assert denormalize_y(500, 900) == 450
    assert denormalize_y(0, 1080) == 0
    assert denormalize_y(1000, 1080) == 1080


def test_normalize_x_and_y():
    assert normalize_x(720, 1440) == 500
    assert normalize_y(450, 900) == 500
