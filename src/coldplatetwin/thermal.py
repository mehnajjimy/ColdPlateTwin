"""Energy-conserving two-layer finite-volume thermal screening model."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace

import numpy as np
from scipy.sparse import lil_matrix
from scipy.sparse.linalg import spsolve

from .geometry import GeometrySI


@dataclass(frozen=True)
class ThermalInputs:
    grid_size: int = 25
    heater_power_w: float = 180.0
    coolant_temperature_c: float = 24.0
    ambient_temperature_c: float = 22.0
    aluminum_conductivity_w_m_k: float = 167.0
    contact_resistance_m2_k_w: float = 2.0e-4
    coolant_h_w_m2_k: float = 1800.0
    environmental_h_w_m2_k: float = 8.0
    payload_power_fraction: float = 0.5

    def validate(self):
        if type(self.grid_size) is not int or self.grid_size < 7 or self.grid_size % 2 == 0:
            raise ValueError("grid_size must be an odd integer >= 7")
        for name, value in asdict(self).items():
            if not np.isfinite(value):
                raise ValueError(f"Thermal input {name} must be finite")
        for name in ("aluminum_conductivity_w_m_k", "contact_resistance_m2_k_w", "coolant_h_w_m2_k"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.heater_power_w < 0 or self.environmental_h_w_m2_k < 0:
            raise ValueError("Heater power and environmental h must be nonnegative")
        if not 0 <= self.payload_power_fraction <= 1:
            raise ValueError("payload_power_fraction must lie in [0, 1]")


@dataclass
class ThermalResult:
    payload_temperature_c: np.ndarray
    cover_temperature_c: np.ndarray
    active_mask: np.ndarray
    heat_to_coolant_w: float
    heat_to_environment_w: float
    energy_residual_w: float
    inputs: dict
    limitations: list[str]


def _patterns(mask: np.ndarray, scenario: str) -> np.ndarray:
    yy, xx = np.indices(mask.shape)
    x = 2.0 * (xx / (mask.shape[1] - 1) - 0.5)
    y = 2.0 * (yy / (mask.shape[0] - 1) - 0.5)
    if scenario == "uniform":
        pattern = np.ones(mask.shape)
    elif scenario == "broad":
        pattern = 1.0 + 0.35 * np.cos(np.pi * x) * np.cos(np.pi * y)
    elif scenario == "fine":
        pattern = 1.0 + 0.35 * np.cos(5.0 * np.pi * x) * np.cos(5.0 * np.pi * y)
    else:
        raise ValueError("h scenario must be 'uniform', 'broad' or 'fine'")
    pattern[~mask] = np.nan
    return pattern


def solve_two_layer(geometry: GeometrySI, inputs: ThermalInputs = ThermalInputs(), h_scenario: str = "uniform") -> ThermalResult:
    """Solve payload and cover temperatures on the common 160 mm disk.

    The actual 200 mm square cover extends beyond this disk.  The omitted outer
    cover region is treated as adiabatic, an explicit simplification that tends
    to understate lateral spreading and environmental loss.
    """

    inputs.validate()
    n = inputs.grid_size
    side = geometry.payload_diameter_m
    dx = side / n
    axis = (np.arange(n) + 0.5) * dx - side / 2.0
    xx, yy = np.meshgrid(axis, axis)
    mask = xx**2 + yy**2 <= (side / 2.0) ** 2
    cells = np.argwhere(mask)
    count = len(cells)
    index = -np.ones((n, n), dtype=int)
    for cell_number, (row, col) in enumerate(cells):
        index[row, col] = cell_number
    area = dx**2

    h_pattern = _patterns(mask, h_scenario)
    h_values = inputs.coolant_h_w_m2_k * h_pattern
    # Uniform power over the CAD-configured heater footprint, normalized so
    # the exact requested heater power enters the matrix even on a coarse grid.
    heater = mask & (xx**2 + yy**2 <= (geometry.heater_diameter_m / 2.0) ** 2)
    source_per_cell = inputs.heater_power_w / int(heater.sum())

    matrix = lil_matrix((2 * count, 2 * count), dtype=float)
    rhs = np.zeros(2 * count)
    payload_inplane = inputs.aluminum_conductivity_w_m_k * geometry.payload_thickness_m
    cover_inplane = inputs.aluminum_conductivity_w_m_k * geometry.cover_thickness_m
    contact = area / inputs.contact_resistance_m2_k_w

    for row, col in cells:
        p = index[row, col]
        c = p + count
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            neighbor = index[row + dr, col + dc] if 0 <= row + dr < n and 0 <= col + dc < n else -1
            if neighbor >= 0:
                matrix[p, p] += payload_inplane
                matrix[p, neighbor] -= payload_inplane
                matrix[c, c] += cover_inplane
                matrix[c, neighbor + count] -= cover_inplane

        matrix[p, p] += contact + inputs.environmental_h_w_m2_k * area
        matrix[p, c] -= contact
        matrix[c, c] += contact + h_values[row, col] * area
        matrix[c, p] -= contact
        rhs[p] += inputs.environmental_h_w_m2_k * area * inputs.ambient_temperature_c
        rhs[c] += h_values[row, col] * area * inputs.coolant_temperature_c
        if heater[row, col]:
            rhs[p] += source_per_cell * inputs.payload_power_fraction
            rhs[c] += source_per_cell * (1.0 - inputs.payload_power_fraction)

    solution = spsolve(matrix.tocsr(), rhs)
    payload = np.full((n, n), np.nan)
    cover = np.full((n, n), np.nan)
    for row, col in cells:
        p = index[row, col]
        payload[row, col] = solution[p]
        cover[row, col] = solution[p + count]
    heat_coolant = float(np.nansum(h_values * area * (cover - inputs.coolant_temperature_c)))
    heat_environment = float(np.nansum(inputs.environmental_h_w_m2_k * area * (payload - inputs.ambient_temperature_c)))
    residual = inputs.heater_power_w - heat_coolant - heat_environment
    return ThermalResult(
        payload,
        cover,
        mask,
        heat_coolant,
        heat_environment,
        residual,
        asdict(inputs) | {"h_scenario": h_scenario},
        [
            "Unvalidated reduced model; h, contact resistance, bypass and environmental loss are uncertain inputs.",
            "Modeled region is the 160 mm payload disk; the outer square-cover region is omitted and its cut edge is adiabatic.",
            "Coolant temperature is prescribed uniformly; downstream coolant warming and local conjugate flow are not resolved.",
            "Imposed h patterns are sensitivity scenarios, not recovered per-pixel measurements.",
        ],
    )


def uniform_lumped_solution(geometry: GeometrySI, inputs: ThermalInputs) -> tuple[float, float]:
    """Two-node analytical limit for a uniform field, used for verification."""

    n = inputs.grid_size
    side = geometry.payload_diameter_m
    dx = side / n
    axis = (np.arange(n) + 0.5) * dx - side / 2.0
    xx, yy = np.meshgrid(axis, axis)
    area = float(np.sum(xx**2 + yy**2 <= (side / 2.0) ** 2) * dx**2)
    gc = area / inputs.contact_resistance_m2_k_w
    ge = inputs.environmental_h_w_m2_k * area
    gw = inputs.coolant_h_w_m2_k * area
    matrix = np.array([[gc + ge, -gc], [-gc, gc + gw]])
    rhs = np.array(
        [
            ge * inputs.ambient_temperature_c + inputs.heater_power_w * inputs.payload_power_fraction,
            gw * inputs.coolant_temperature_c + inputs.heater_power_w * (1.0 - inputs.payload_power_fraction),
        ]
    )
    result = np.linalg.solve(matrix, rhs)
    return float(result[0]), float(result[1])


def sensitivity_sweep(geometry: GeometrySI, baseline: ThermalInputs | None = None) -> list[dict[str, float | str]]:
    """Small, readable Rev A sensitivity set that completes on a laptop CPU."""

    baseline = baseline or ThermalInputs()
    rows: list[dict[str, float | str]] = []
    for contact in (baseline.contact_resistance_m2_k_w * factor for factor in (.5, 1, 2.5)):
        for h in (baseline.coolant_h_w_m2_k * factor for factor in (.5, 1, 5/3)):
            uniform_result = solve_two_layer(
                geometry,
                replace(baseline, contact_resistance_m2_k_w=contact, coolant_h_w_m2_k=h),
                "uniform",
            )
            for scenario in ("uniform", "broad", "fine"):
                inputs = replace(baseline, contact_resistance_m2_k_w=contact, coolant_h_w_m2_k=h)
                result = solve_two_layer(geometry, inputs, scenario)
                payload = result.payload_temperature_c[result.active_mask]
                response = (result.payload_temperature_c - uniform_result.payload_temperature_c)[result.active_mask]
                imposed_pattern = _patterns(result.active_mask, scenario)[result.active_mask]
                h_relative_std = float(np.std(imposed_pattern))
                rows.append(
                    {
                        "contact_resistance_m2_k_w": contact,
                        "coolant_h_w_m2_k": h,
                        "h_scenario": scenario,
                        "payload_mean_c": float(payload.mean()),
                        "payload_peak_to_peak_k": float(payload.max() - payload.min()),
                        "payload_standard_deviation_k": float(payload.std()),
                        "imposed_h_relative_standard_deviation": h_relative_std,
                        "surface_response_to_uniform_standard_deviation_k": float(np.std(response)),
                        "spatial_transfer_k_per_h_fraction": float(np.std(response) / h_relative_std) if h_relative_std > 0 else 0.0,
                        "energy_residual_w": result.energy_residual_w,
                    }
                )
    # Thickness and environmental-loss cases are separate so parameters are not
    # confused with fitted quantities.
    for thickness_scale, loss_scale in ((0.8, 1), (1.2, 1), (1, .375), (1, 1.875)):
        loss_h = baseline.environmental_h_w_m2_k * loss_scale
        modified = replace(
            geometry,
            payload_thickness_m=geometry.payload_thickness_m * thickness_scale,
            cover_thickness_m=geometry.cover_thickness_m * thickness_scale,
        )
        result = solve_two_layer(modified, replace(baseline, environmental_h_w_m2_k=loss_h), "broad")
        payload = result.payload_temperature_c[result.active_mask]
        rows.append({
            "contact_resistance_m2_k_w": baseline.contact_resistance_m2_k_w,
            "coolant_h_w_m2_k": baseline.coolant_h_w_m2_k,
            "h_scenario": f"broad_thickness_{thickness_scale:g}_loss_{loss_h:g}",
            "payload_mean_c": float(payload.mean()),
            "payload_peak_to_peak_k": float(payload.max() - payload.min()),
            "payload_standard_deviation_k": float(payload.std()),
            "imposed_h_relative_standard_deviation": None,
            "surface_response_to_uniform_standard_deviation_k": None,
            "spatial_transfer_k_per_h_fraction": None,
            "energy_residual_w": result.energy_residual_w,
        })
    return rows
