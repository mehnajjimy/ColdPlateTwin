"""Circular radiometric ROI statistics with invalid/occluded pixels excluded."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ROIStatistics:
    mean_c: float
    maximum_c: float
    standard_deviation_k: float
    peak_to_peak_k: float
    valid_pixel_count: int
    total_roi_pixel_count: int


def circular_roi_statistics(
    temperature_c: np.ndarray | np.ma.MaskedArray,
    roi_diameter_px: float,
    center_xy: tuple[float, float] | None = None,
    occlusion_mask: np.ndarray | None = None,
) -> ROIStatistics:
    """Calculate statistics over an explicit circular analysis region."""

    image = np.ma.masked_invalid(np.ma.asarray(temperature_c, dtype=float))
    if image.ndim != 2:
        raise ValueError("ROI input must be a two-dimensional temperature array")
    if not np.isfinite(roi_diameter_px) or roi_diameter_px <= 0:
        raise ValueError("ROI diameter must be positive and finite")
    height, width = image.shape
    cx, cy = center_xy or ((width - 1) / 2.0, (height - 1) / 2.0)
    if not np.isfinite([cx, cy]).all():
        raise ValueError("ROI center must be finite")
    yy, xx = np.indices(image.shape)
    circle = (xx - cx) ** 2 + (yy - cy) ** 2 <= (roi_diameter_px / 2.0) ** 2
    mask = ~circle | np.ma.getmaskarray(image)
    if occlusion_mask is not None:
        if occlusion_mask.shape != image.shape:
            raise ValueError("Occlusion mask shape must match temperature array")
        mask |= occlusion_mask.astype(bool)
    values = np.ma.array(image.data, mask=mask).compressed()
    if not len(values):
        raise ValueError("Circular ROI contains no valid temperature pixels")
    return ROIStatistics(
        mean_c=float(values.mean()),
        maximum_c=float(values.max()),
        standard_deviation_k=float(values.std(ddof=1)) if len(values) > 1 else 0.0,
        peak_to_peak_k=float(values.max() - values.min()),
        valid_pixel_count=int(len(values)),
        total_roi_pixel_count=int(circle.sum()),
    )
