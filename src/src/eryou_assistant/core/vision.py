from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AngleResult:
    angle: float
    confidence: float


@dataclass(frozen=True, slots=True)
class LocationResult:
    x: float
    y: float
    confidence: float
    matches: int


def ai_dependencies_available() -> bool:
    try:
        import cv2  # noqa: F401
        import numpy  # noqa: F401
        import onnxruntime  # noqa: F401
    except ImportError:
        return False
    return True


def model_resource_path(name: str) -> Path:
    return Path(str(files("eryou_assistant.resources").joinpath("models", name)))


class ConeAngleDetector:
    def __init__(self, model_path: Path | None = None) -> None:
        import numpy as np
        import onnxruntime as ort

        self._np = np
        self.session = ort.InferenceSession(
            str(model_path or model_resource_path("model_improved.onnx")),
            providers=["CPUExecutionProvider"],
        )
        self.input_name = self.session.get_inputs()[0].name
        self.output_name = self.session.get_outputs()[0].name
        self.mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
        self.std = np.array([0.229, 0.224, 0.225], dtype=np.float32)

    def predict(self, image) -> AngleResult:
        import cv2

        if image.ndim == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        elif image.shape[2] == 4:
            image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
        image = cv2.resize(image, (152, 152), interpolation=cv2.INTER_CUBIC)
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB).astype(self._np.float32) / 255.0
        image = (image - self.mean) / self.std
        tensor = self._np.expand_dims(self._np.transpose(image, (2, 0, 1)), axis=0)
        output = self.session.run([self.output_name], {self.input_name: tensor})[0]
        sin_value, cos_value = float(output[0, 0]), float(output[0, 1])
        angle = float((self._np.degrees(self._np.arctan2(sin_value, cos_value)) + 360) % 360)
        confidence = float(self._np.sqrt(sin_value**2 + cos_value**2))
        return AngleResult(angle, confidence)


class FeatureLocator:
    def __init__(self, *, edge_enhance: bool = False) -> None:
        self.edge_enhance = edge_enhance
        self._session = None
        self.last_backend = ""

    def locate(self, large_image, small_image) -> LocationResult | None:

        large = _ensure_bgr(large_image)
        small = _ensure_bgr(small_image)
        if self.edge_enhance:
            large, small = _joined_clahe(large, small)
        result = self._locate_xfeat(large, small)
        if result is not None and result.confidence >= 0.35:
            self.last_backend = "xfeat"
            return result
        self.last_backend = "orb-fallback"
        return self._locate_orb(large, small)

    def _locate_xfeat(self, large, small) -> LocationResult | None:
        import cv2
        import numpy as np
        import onnxruntime as ort

        if self._session is None:
            self._session = ort.InferenceSession(
                str(model_resource_path("model_xfeat.onnx")),
                providers=["CPUExecutionProvider"],
            )
        points_small, descriptors_small = self._extract_xfeat(small)
        points_large, descriptors_large = self._extract_xfeat(large)
        if len(points_small) < 8 or len(points_large) < 8:
            return None
        similarities = descriptors_small @ descriptors_large.T
        nearest_large = similarities.argmax(axis=1)
        nearest_small = similarities.argmax(axis=0)
        source_indices = np.arange(len(points_small))
        mutual = nearest_small[nearest_large] == source_indices
        strong = similarities[source_indices, nearest_large] >= 0.82
        selected = source_indices[mutual & strong]
        if len(selected) < 8:
            return None
        source = points_small[selected].reshape(-1, 1, 2).astype(np.float32)
        target = points_large[nearest_large[selected]].reshape(-1, 1, 2).astype(np.float32)
        homography, mask = cv2.findHomography(source, target, cv2.RANSAC, 5.0)
        if homography is None or mask is None:
            return None
        height, width = small.shape[:2]
        corners = np.float32([[[0, 0]], [[width, 0]], [[width, height]], [[0, height]]])
        mapped_corners = cv2.perspectiveTransform(corners, homography).reshape(4, 2)
        max_deviation = _quad_angle_max_deviation(mapped_corners)
        geometry_weight = max(0.0, 1.0 - max_deviation / 45.0)
        confidence = float(mask.ravel().mean() * geometry_weight)
        center = cv2.perspectiveTransform(np.float32([[[width / 2, height / 2]]]), homography)[0, 0]
        if not (0 <= center[0] < large.shape[1] and 0 <= center[1] < large.shape[0]):
            return None
        return LocationResult(
            float(center[0] / large.shape[1]),
            float(center[1] / large.shape[0]),
            confidence,
            len(selected),
        )

    def _extract_xfeat(self, image):
        import cv2
        import numpy as np

        original_height, original_width = image.shape[:2]
        resized = cv2.resize(image, (640, 640), interpolation=cv2.INTER_AREA)
        tensor = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        tensor = np.transpose(tensor, (2, 0, 1))[None]
        descriptor_map, logits, reliability = self._session.run(
            None, {self._session.get_inputs()[0].name: tensor}
        )
        descriptor_map = descriptor_map[0]
        raw = logits[0]
        raw -= raw.max(axis=0, keepdims=True)
        probabilities = np.exp(raw)
        probabilities /= probabilities.sum(axis=0, keepdims=True) + 1e-8
        cells = probabilities[:64].reshape(8, 8, 80, 80)
        score = cells.transpose(2, 0, 3, 1).reshape(640, 640)
        reliability_map = cv2.resize(reliability[0, 0], (640, 640))
        score *= reliability_map
        maxima = score == cv2.dilate(score, np.ones((5, 5), np.uint8))
        ys, xs = np.where(maxima & (score > 0.001))
        if len(xs) == 0:
            return np.empty((0, 2), np.float32), np.empty((0, 64), np.float32)
        values = score[ys, xs]
        order = np.argsort(values)[-2048:]
        xs, ys = xs[order], ys[order]
        descriptors = descriptor_map[:, np.clip(ys // 8, 0, 79), np.clip(xs // 8, 0, 79)].T
        descriptors /= np.linalg.norm(descriptors, axis=1, keepdims=True) + 1e-8
        points = np.column_stack(
            (xs * original_width / 640.0, ys * original_height / 640.0)
        ).astype(np.float32)
        return points, descriptors.astype(np.float32)

    @staticmethod
    def _locate_orb(large, small) -> LocationResult | None:
        import cv2
        import numpy as np

        gray_large = cv2.cvtColor(large, cv2.COLOR_BGR2GRAY)
        gray_small = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        detector = cv2.ORB_create(nfeatures=3000, fastThreshold=8)
        key_small, descriptor_small = detector.detectAndCompute(gray_small, None)
        key_large, descriptor_large = detector.detectAndCompute(gray_large, None)
        if descriptor_small is None or descriptor_large is None:
            return None
        pairs = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(descriptor_small, descriptor_large, k=2)
        good = [first for first, second in pairs if first.distance < 0.75 * second.distance]
        if len(good) < 8:
            return None
        source = np.float32([key_small[item.queryIdx].pt for item in good]).reshape(-1, 1, 2)
        target = np.float32([key_large[item.trainIdx].pt for item in good]).reshape(-1, 1, 2)
        homography, mask = cv2.findHomography(source, target, cv2.RANSAC, 5.0)
        if homography is None or mask is None:
            return None
        height, width = small.shape[:2]
        center = np.float32([[[width / 2, height / 2]]])
        mapped = cv2.perspectiveTransform(center, homography)[0, 0]
        confidence = float(mask.ravel().mean())
        return LocationResult(
            float(mapped[0] / large.shape[1]),
            float(mapped[1] / large.shape[0]),
            confidence,
            len(good),
        )


def _ensure_bgr(image):
    import cv2

    if image.ndim == 2:
        return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    if image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
    return image


def _sobel(image):
    import cv2

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    x_axis = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    y_axis = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    magnitude = cv2.magnitude(x_axis, y_axis)
    normalized = cv2.normalize(magnitude, None, 0, 255, cv2.NORM_MINMAX).astype("uint8")
    return cv2.cvtColor(normalized, cv2.COLOR_GRAY2BGR)


def _joined_clahe(large, small):
    import cv2
    import numpy as np

    target_height = max(large.shape[0], small.shape[0])

    def pad(image):
        return cv2.copyMakeBorder(
            image,
            0,
            target_height - image.shape[0],
            0,
            0,
            cv2.BORDER_REFLECT,
        )

    joined = np.concatenate((pad(large), pad(small)), axis=1)
    lab = cv2.cvtColor(joined, cv2.COLOR_BGR2LAB)
    contrast = float(lab[:, :, 0].std())
    clip_limit = 3.0 if contrast < 35 else 2.0
    lab[:, :, 0] = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(8, 8)).apply(lab[:, :, 0])
    enhanced = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
    split = large.shape[1]
    return enhanced[: large.shape[0], :split], enhanced[: small.shape[0], split:]


def _quad_angle_max_deviation(corners) -> float:
    import numpy as np

    deviations = []
    for index in range(4):
        previous = corners[(index - 1) % 4] - corners[index]
        following = corners[(index + 1) % 4] - corners[index]
        denominator = np.linalg.norm(previous) * np.linalg.norm(following)
        if denominator <= 1e-8:
            return 90.0
        cosine = float(np.clip(np.dot(previous, following) / denominator, -1.0, 1.0))
        deviations.append(abs(float(np.degrees(np.arccos(cosine))) - 90.0))
    return max(deviations)
