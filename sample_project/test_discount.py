from discount import discounted_price


def test_discounted_price():
    assert discounted_price(100, 20) == 80
