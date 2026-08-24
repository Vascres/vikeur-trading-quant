from ml_engine.comparison import ModelEvaluation, select_best_model


def test_select_best_model_picks_highest_expectancy():
    evaluations = [
        ModelEvaluation("model_a", profit_factor=1.2, expectancy=0.001, total_simulated_trades=20),
        ModelEvaluation("model_b", profit_factor=1.5, expectancy=0.005, total_simulated_trades=15),
    ]
    best = select_best_model(evaluations)
    assert best.model_name == "model_b"


def test_select_best_model_ignores_models_with_too_few_trades():
    evaluations = [
        ModelEvaluation("model_a", profit_factor=2.0, expectancy=0.01, total_simulated_trades=3),
    ]
    assert select_best_model(evaluations) is None


def test_select_best_model_returns_none_when_no_eligible_model():
    assert select_best_model([]) is None
