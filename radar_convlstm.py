import argparse
import glob
import os
from typing import List, Tuple, Any


from config import SAVE_PATHS

TARGET_SIZE = (252, 252)


def _debug_log(message: str):
    try:
        from debug_utils import debug_log as _dbg
        _dbg(message)
    except Exception:
        print(message)

INPUT_FRAMES = 4
OUTPUT_FRAMES = 4
SEQUENCE_LENGTH = INPUT_FRAMES + OUTPUT_FRAMES
MODEL_PATH = os.path.join(SAVE_PATHS["models"], "current", "radar_convlstm.keras")


def _load_and_preprocess_frame(path: str):
    import cv2
    import numpy as np
    frame = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if frame is None:
        raise ValueError(f"Konnte Radarbild nicht laden: {path}")
    resized = cv2.resize(frame, TARGET_SIZE, interpolation=cv2.INTER_AREA)
    return resized.astype(np.float32) / 255.0


def _build_sliding_windows(frames: List[Any]):
    import numpy as np
    x_samples, y_samples = [], []
    for start_idx in range(0, len(frames) - SEQUENCE_LENGTH + 1):
        window = frames[start_idx : start_idx + SEQUENCE_LENGTH]
        x_samples.append(np.stack(window[:INPUT_FRAMES], axis=0))
        y_samples.append(np.stack(window[INPUT_FRAMES:], axis=0))

    if not x_samples:
        return np.empty((0, INPUT_FRAMES, *TARGET_SIZE, 1), dtype=np.float32), np.empty(
            (0, OUTPUT_FRAMES, *TARGET_SIZE, 1), dtype=np.float32
        )

    x_data = np.array(x_samples, dtype=np.float32)[..., np.newaxis]
    y_data = np.array(y_samples, dtype=np.float32)[..., np.newaxis]
    return x_data, y_data


def _load_radar_dataset():
    import numpy as np
    pattern = os.path.join(SAVE_PATHS["radar"], "*.png")
    frame_paths = sorted(glob.glob(pattern))

    if len(frame_paths) < 200:
        _debug_log(
            f"[CONVLSTM] Training übersprungen: nur {len(frame_paths)} Bilder vorhanden (<200)."
        )
        return np.empty((0,)), np.empty((0,))

    frames = [_load_and_preprocess_frame(path) for path in frame_paths]
    x_data, y_data = _build_sliding_windows(frames)
    _debug_log(
        f"[CONVLSTM] Datensatz erstellt: frames={len(frame_paths)}, samples={len(x_data)}"
    )
    return x_data, y_data


def _build_model():
    import tensorflow as tf
    from tensorflow.keras import layers, models

    model = models.Sequential(
        [
            layers.Input(shape=(INPUT_FRAMES, TARGET_SIZE[1], TARGET_SIZE[0], 1)),
            layers.ConvLSTM2D(
                filters=64,
                kernel_size=(3, 3),
                padding="same",
                return_sequences=True,
            ),
            layers.BatchNormalization(),
            layers.ConvLSTM2D(
                filters=64,
                kernel_size=(3, 3),
                padding="same",
                return_sequences=True,
            ),
            layers.BatchNormalization(),
            layers.Conv3D(
                filters=1,
                kernel_size=(3, 3, 3),
                activation="sigmoid",
                padding="same",
            ),
        ]
    )

    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=1e-3),
        loss=tf.keras.losses.MeanAbsoluteError(),
    )
    return model


def train_convlstm(batch_size: int = 4, epochs: int = 30):
    try:
        x_data, y_data = _load_radar_dataset()
    except ModuleNotFoundError as exc:
        _debug_log(f"[CONVLSTM] Training übersprungen: fehlende Abhängigkeit ({exc}).")
        return {"trained": False, "reason": "missing_dependency", "error": str(exc)}
    if x_data.size == 0 or y_data.size == 0:
        return {"trained": False, "reason": "insufficient_data"}

    import tensorflow as tf

    model = _build_model()
    early_stop = tf.keras.callbacks.EarlyStopping(
        monitor="val_loss", patience=5, restore_best_weights=True
    )

    safe_batch_size = 2 if batch_size < 2 else batch_size
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)

    _debug_log(
        f"[CONVLSTM] Training gestartet: samples={len(x_data)}, batch_size={safe_batch_size}, epochs={epochs}"
    )
    try:
        history = model.fit(
            x_data,
            y_data,
            batch_size=safe_batch_size,
            epochs=epochs,
            validation_split=0.2,
            callbacks=[early_stop],
            verbose=1,
        )
    except Exception as exc:
        if "ResourceExhausted" in str(exc) and safe_batch_size > 2:
            _debug_log("[CONVLSTM] Speichermangel erkannt, neuer Versuch mit batch_size=2")
            history = model.fit(
                x_data,
                y_data,
                batch_size=2,
                epochs=epochs,
                validation_split=0.2,
                callbacks=[early_stop],
                verbose=1,
            )
        else:
            raise
    model.save(MODEL_PATH)
    _debug_log(f"[CONVLSTM] Modell gespeichert unter {MODEL_PATH}")

    return {
        "trained": True,
        "model_path": MODEL_PATH,
        "epochs_ran": len(history.history.get("loss", [])),
    }


def predict_radar_convlstm(latest_4_frames: List[Any]):
    import cv2
    import numpy as np
    if len(latest_4_frames) != INPUT_FRAMES:
        raise ValueError("Es müssen genau 4 Frames übergeben werden.")

    processed_frames = []
    original_shape = latest_4_frames[0].shape[:2]

    for frame in latest_4_frames:
        gray = frame
        if frame.ndim == 3:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        resized = cv2.resize(gray, TARGET_SIZE, interpolation=cv2.INTER_AREA)
        processed_frames.append(resized.astype(np.float32) / 255.0)

    input_tensor = np.array([processed_frames], dtype=np.float32)[..., np.newaxis]

    import tensorflow as tf

    if not os.path.exists(MODEL_PATH):
        raise FileNotFoundError(f"Modell nicht gefunden: {MODEL_PATH}")

    model = tf.keras.models.load_model(MODEL_PATH, compile=False)
    prediction = model.predict(input_tensor, verbose=0)[0, :, :, :, 0]

    restored = []
    for pred_frame in prediction:
        back_scaled = np.clip(pred_frame * 255.0, 0, 255).astype(np.uint8)
        restored.append(cv2.resize(back_scaled, (original_shape[1], original_shape[0]), interpolation=cv2.INTER_AREA))

    return np.array(restored)


def _cli():
    parser = argparse.ArgumentParser(description="ConvLSTM Radar-Modell")
    parser.add_argument("--train", action="store_true", help="ConvLSTM trainieren")
    parser.add_argument("--batch-size", type=int, default=4, help="Batch-Größe (Pi: 4 oder 2)")
    parser.add_argument("--epochs", type=int, default=30, help="Anzahl Epochen")
    args = parser.parse_args()

    if args.train:
        result = train_convlstm(batch_size=args.batch_size, epochs=args.epochs)
        _debug_log(f"[CONVLSTM] Trainingsergebnis: {result}")
    else:
        parser.print_help()


if __name__ == "__main__":
    _cli()
