from ml_engine.label_builder import align_features_and_labels, build_labels


def test_build_labels_positive_return_is_one():
    closes = [100.0, 101.0, 105.0]
    labels = build_labels(closes, horizon_periods=2, threshold=0.0)
    assert labels[0] == 1  # (105-100)/100 = 5% > 0


def test_build_labels_negative_return_is_zero():
    closes = [100.0, 99.0, 95.0]
    labels = build_labels(closes, horizon_periods=2, threshold=0.0)
    assert labels[0] == 0


def test_build_labels_none_when_horizon_exceeds_data():
    closes = [100.0, 101.0]
    labels = build_labels(closes, horizon_periods=5)
    assert all(label is None for label in labels)


def test_build_labels_respects_threshold():
    closes = [100.0, 100.5]  # +0.5%
    labels = build_labels(closes, horizon_periods=1, threshold=0.01)  # seuil 1%
    assert labels[0] == 0  # sous le seuil malgré un rendement positif


def test_align_features_and_labels_filters_none():
    features = [[1.0], [2.0], [3.0]]
    labels = [1, None, 0]
    X, y = align_features_and_labels(features, labels)
    assert X == [[1.0], [3.0]]
    assert y == [1, 0]
