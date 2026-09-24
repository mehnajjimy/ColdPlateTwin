"""circular roi statistics on radiometric frames, skipping invalid or occluded pixels."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


# summary numbers for the valid pixels inside a circular region
@dataclass(frozen=True)
class ROIStatistics:
    mean_c: float
    maximum_c: float
    standard_deviation_k: float
    peak_to_peak_k: float
    valid_pixel_count: int
    total_roi_pixel_count: int


# mean, max, spread and pixel counts over a circle drawn on one temperature map
def circular_roi_statistics(
    temperature_c: np.ndarray | np.ma.MaskedArray,
    roi_diameter_px: float,
    center_xy: tuple[float, float] | None = None,
    occlusion_mask: np.ndarray | None = None,
) -> ROIStatistics:
    """calculate statistics over an explicit circular analysis region."""
    # nan and inf pixels are treated as masked
    image = np.ma.masked_invalid(np.ma.asarray(temperature_c, dtype=float))
    if image.ndim != 2:
        raise ValueError("ROI input must be a two-dimensional temperature array")
    if not np.isfinite(roi_diameter_px) or roi_diameter_px <= 0:
        raise ValueError("ROI diameter must be positive and finite")

    # the circle sits on the image middle unless a center is given
    height, width = image.shape
    cx, cy = center_xy or ((width - 1) / 2.0, (height - 1) / 2.0)
    if not np.isfinite([cx, cy]).all():
        raise ValueError("ROI center must be finite")
    yy, xx = np.indices(image.shape)
    circle = (xx - cx) ** 2 + (yy - cy) ** 2 <= (roi_diameter_px / 2.0) ** 2

    # drop pixels outside the circle, invalid pixels and occluded pixels
    mask = ~circle | np.ma.getmaskarray(image)
    if occlusion_mask is not None:
        if occlusion_mask.shape != image.shape:
            raise ValueError("Occlusion mask shape must match temperature array")
        mask |= occlusion_mask.astype(bool)
    values = np.ma.array(image.data, mask=mask).compressed()
    if len(values) == 0:
        raise ValueError("Circular ROI contains no valid temperature pixels")

    # sample standard deviation, or zero when only one pixel is left
    if len(values) > 1:
        standard_deviation = float(values.std(ddof=1))
    else:
        standard_deviation = 0.0

    return ROIStatistics(
        mean_c=float(values.mean()),
        maximum_c=float(values.max()),
        standard_deviation_k=standard_deviation,
        peak_to_peak_k=float(values.max() - values.min()),
        valid_pixel_count=int(len(values)),
        total_roi_pixel_count=int(circle.sum()),
    )
