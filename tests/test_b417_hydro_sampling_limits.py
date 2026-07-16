import config

def test_sampling_defaults_are_bounded():
    assert config.HYDRO_ML_MAX_TRAINING_SAMPLES > config.HYDRO_ML_MAX_NO_CELL_SAMPLES_PER_DAY > 0
