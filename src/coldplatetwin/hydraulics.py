"""Hydraulic screening models for the four Rev A inserts.

The rectangular-channel correlation uses the Darcy friction factor.  The
parallel inserts are solved as a pressure-node network, not by forcing equal
branch flow.  Results are screening pressure drops, not structural ratings or
local gauge pressures.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
from scipy.optimize import least_squares

from .geometry import GeometrySI
from .properties import water_properties


@dataclass(frozen=True)
class HydraulicInputs:
    """Editable dimensionless loss coefficients, not measured constants."""

    entrance_exit_k: float = 1.5
    bend_k: float = 0.35
    parallel_channel_k: float = 1.5
    header_segment_k: float = 0.08
    plenum_k: float = 3.0

    def validate(self):
        for name, value in asdict(self).items():
            if not np.isfinite(value) or value < 0:
                raise ValueError(f"hydraulic.{name} must be finite and nonnegative")


@dataclass(frozen=True)
class HydraulicResult:
    insert_id: str
    flow_lpm: float
    screening_pressure_drop_pa: float | None
    reynolds_number: float | None
    branch_flow_lpm: list[float] | None
    mass_balance_error_lpm: float
    warnings: list[str]
    assumptions: dict[str, float | str]
    applicability: str = "laminar_screening"
    maximum_nodal_residual_fraction: float = 0.0

    def as_dict(self) -> dict:
        return asdict(self)


def hydraulic_diameter(width_m: float, height_m: float) -> float:
    if not np.isfinite([width_m, height_m]).all() or width_m <= 0 or height_m <= 0:
        raise ValueError("Channel width and height must be positive")
    return 2.0 * width_m * height_m / (width_m + height_m)


def rectangular_darcy_friction_reynolds(width_m: float, height_m: float) -> float:
    """Return f_D*Re for fully developed laminar rectangular flow.

    Shah and London give the aspect-ratio polynomial for the Fanning product;
    multiplication by four yields this Darcy-convention form.
    """

    alpha = min(width_m, height_m) / max(width_m, height_m)
    return 96.0 * (1 - 1.3553 * alpha + 1.9467 * alpha**2 - 1.7012 * alpha**3 + 0.9564 * alpha**4 - 0.2537 * alpha**5)


def channel_pressure_drop(
    volume_flow_m3_s: float,
    width_m: float,
    height_m: float,
    length_m: float,
    temperature_c: float,
    minor_loss_k: float = 0.0,
) -> tuple[float, float, float]:
    """Calculate fully developed laminar pressure drop plus named minor losses."""

    if not np.isfinite([volume_flow_m3_s, length_m, minor_loss_k]).all():
        raise ValueError("Flow, length and loss coefficient must be finite")
    if min(volume_flow_m3_s, length_m, minor_loss_k) < 0:
        raise ValueError("Flow, length and loss coefficient must be nonnegative")
    area = width_m * height_m
    diameter = hydraulic_diameter(width_m, height_m)
    props = water_properties(temperature_c)
    velocity = volume_flow_m3_s / area
    reynolds = props.density_kg_m3 * velocity * diameter / props.viscosity_pa_s
    fd_re = rectangular_darcy_friction_reynolds(width_m, height_m)
    friction = fd_re / reynolds if reynolds > 0 else 0.0
    pressure = friction * length_m / diameter * props.density_kg_m3 * velocity**2 / 2.0
    pressure += minor_loss_k * props.density_kg_m3 * velocity**2 / 2.0
    return float(pressure), float(reynolds), float(friction)


def _loss_coefficients(width: float, height: float, length: float, temperature_c: float, k: float) -> tuple[float, float]:
    """Return coefficients for dp = R*q + B*q*abs(q)."""

    props = water_properties(temperature_c)
    area = width * height
    diameter = hydraulic_diameter(width, height)
    fd_re = rectangular_darcy_friction_reynolds(width, height)
    linear = fd_re * props.viscosity_pa_s * length / (2.0 * diameter**2 * area)
    quadratic = k * props.density_kg_m3 / (2.0 * area**2)
    return linear, quadratic


def _flow_from_pressure(delta_p: float, linear: float, quadratic: float) -> float:
    sign = 1.0 if delta_p >= 0 else -1.0
    magnitude = abs(delta_p)
    if quadratic <= 0:
        return sign * magnitude / linear
    return sign * 2 * magnitude / (linear + np.sqrt(linear**2 + 4 * quadratic * magnitude))


def parallel_network(
    geometry: GeometrySI,
    insert_id: str,
    flow_lpm: float,
    temperature_c: float,
    channel_minor_k: float = 1.5,
    header_minor_k_per_segment: float = 0.08,
) -> HydraulicResult:
    """Solve the FI-200/FI-300 inlet-header/channel/outlet-header network."""

    if insert_id not in {"FI-200", "FI-300"}:
        raise ValueError("parallel_network supports only FI-200 and FI-300")
    if not np.isfinite(flow_lpm) or flow_lpm <= 0:
        raise ValueError("Flow must be positive")
    if not np.isfinite([channel_minor_k, header_minor_k_per_segment]).all() or min(channel_minor_k, header_minor_k_per_segment) < 0:
        raise ValueError("Minor loss coefficients must be finite and nonnegative")
    n = geometry.parallel_channel_count
    total_q = flow_lpm / 60_000.0
    y = np.asarray(geometry.parallel_centers_y_m)
    if n < 2 or len(y) != n or np.any(np.diff(y) <= 0) or not np.allclose(y, -y[::-1]):
        raise ValueError("The two central-feed approximation requires symmetric ordered channel centers")
    if n % 2:
        raise ValueError("The central-feed approximation requires an even channel count")
    feed_nodes = [n // 2 - 1, n // 2]
    source = np.zeros(n)
    source[feed_nodes] = total_q / 2.0

    if insert_id == "FI-200":
        node_widths = np.full(n, geometry.fi200_header_width_m)
    else:
        radial_fraction = np.abs(y) / np.max(np.abs(y))
        node_widths = geometry.fi200_header_width_m - radial_fraction * (
            geometry.fi200_header_width_m - geometry.fi300_header_end_width_m
        )

    header_coefficients = [
        _loss_coefficients(float((node_widths[i] + node_widths[i + 1]) / 2.0), geometry.channel_height_m, float(y[i + 1] - y[i]), temperature_c, header_minor_k_per_segment)
        for i in range(n - 1)
    ]
    channel_linear, channel_quadratic = _loss_coefficients(
        geometry.parallel_channel_width_m,
        geometry.channel_height_m,
        geometry.parallel_channel_length_m,
        temperature_c,
        channel_minor_k,
    )

    def residual(pressures: np.ndarray) -> np.ndarray:
        pin = pressures[:n]
        pout = pressures[n:]
        inlet_balance = source.copy()
        outlet_balance = -source.copy()
        for i, (linear, quadratic) in enumerate(header_coefficients):
            q_in = _flow_from_pressure(pin[i] - pin[i + 1], linear, quadratic)
            inlet_balance[i] -= q_in
            inlet_balance[i + 1] += q_in
            q_out = _flow_from_pressure(pout[i] - pout[i + 1], linear, quadratic)
            outlet_balance[i] -= q_out
            outlet_balance[i + 1] += q_out
        for i in range(n):
            q_channel = _flow_from_pressure(pin[i] - pout[i], channel_linear, channel_quadratic)
            inlet_balance[i] -= q_channel
            outlet_balance[i] += q_channel
        # Pressure has an arbitrary datum.  An extra residual anchors one outlet
        # node while the least-squares solver satisfies every mass balance.
        return np.r_[inlet_balance / total_q, outlet_balance / total_q, pout[feed_nodes[0]] / 10_000.0]

    single_drop, _, _ = channel_pressure_drop(total_q / n, geometry.parallel_channel_width_m, geometry.channel_height_m, geometry.parallel_channel_length_m, temperature_c, channel_minor_k)
    guess = np.r_[np.full(n, single_drop), np.zeros(n)]
    solution = least_squares(residual, guess, xtol=1e-12, ftol=1e-12, gtol=1e-12, max_nfev=3000)
    nodal_error = float(np.max(np.abs(residual(solution.x)[:-1])))
    if not solution.success or not np.isfinite(solution.x).all() or nodal_error > 1e-7:
        raise RuntimeError(f"Hydraulic network did not converge: nodal residual {nodal_error:.3g}")
    pin = solution.x[:n]
    pout = solution.x[n:]
    branches = np.array([_flow_from_pressure(pin[i] - pout[i], channel_linear, channel_quadratic) for i in range(n)])
    supply_pressure = float(np.mean(pin[feed_nodes]) - np.mean(pout[feed_nodes]))
    if np.any(branches <= 0) or supply_pressure <= 0:
        raise RuntimeError("Hydraulic network returned nonphysical flow or pressure")
    mean_branch = total_q / n
    maldistribution = float(np.std(branches) / mean_branch)
    _, reynolds, _ = channel_pressure_drop(float(branches.max()), geometry.parallel_channel_width_m, geometry.channel_height_m, geometry.parallel_channel_length_m, temperature_c)
    warnings = [
        "Parallel-header result is a reduced resistance network; header junction details and 3D separation are unresolved.",
        "FI-300 is a candidate scenario, not demonstrated improvement.",
    ]
    if reynolds > 2300:
        warnings.append("Maximum branch Reynolds number is outside the laminar correlation range.")
    entrance_length = 0.05 * reynolds * hydraulic_diameter(geometry.parallel_channel_width_m, geometry.channel_height_m)
    if entrance_length > geometry.parallel_channel_length_m:
        warnings.append("Estimated laminar entrance length exceeds channel length; developing flow is unresolved.")
    return HydraulicResult(
        insert_id,
        flow_lpm,
        supply_pressure,
        reynolds,
        (branches * 60_000.0).tolist(),
        float((branches.sum() - total_q) * 60_000.0),
        warnings,
        {
            "friction_convention": "Darcy",
            "channel_minor_loss_k": channel_minor_k,
            "header_minor_loss_k_per_segment": header_minor_k_per_segment,
            "branch_flow_cv": maldistribution,
            "equal_split_reference_lpm": flow_lpm / n,
            "reynolds_definition": "maximum branch Reynolds number",
            "feed_approximation": "half total flow applied at each of the two central header nodes",
            "estimated_entrance_length_m": entrance_length,
        },
        applicability="outside_laminar_range" if reynolds > 2300 else "laminar_screening",
        maximum_nodal_residual_fraction=nodal_error,
    )


def predict_hydraulics(geometry: GeometrySI, insert_id: str, flow_lpm: float,
                      temperature_c: float = 25.0, inputs: HydraulicInputs | None = None) -> HydraulicResult:
    """Route each insert to its appropriate screening model."""

    inputs = inputs or HydraulicInputs()
    inputs.validate()
    if not np.isfinite(flow_lpm) or flow_lpm <= 0:
        raise ValueError("Flow must be positive")
    q = flow_lpm / 60_000.0
    if insert_id == "FI-100":
        bend_count = geometry.fi100_bend_count
        k_entrance_exit = inputs.entrance_exit_k
        k_bends = inputs.bend_k * bend_count
        drop, reynolds, _ = channel_pressure_drop(q, geometry.channel_width_m, geometry.channel_height_m, geometry.fi100_path_length_m, temperature_c, k_entrance_exit + k_bends)
        warnings = ["FI-100 return and entrance loss coefficients are assumptions requiring measurement."]
        if reynolds > 2300:
            warnings.append("Reynolds number is outside the laminar correlation range; no turbulent extension is applied.")
        return HydraulicResult(insert_id, flow_lpm, drop, reynolds, None, 0.0, warnings,
                               {"friction_convention": "Darcy", "path_length_m": geometry.fi100_path_length_m,
                                "minor_loss_k": k_entrance_exit + k_bends},
                               applicability="outside_laminar_range" if reynolds > 2300 else "laminar_screening")
    if insert_id in {"FI-200", "FI-300"}:
        return parallel_network(geometry, insert_id, flow_lpm, temperature_c,
                                inputs.parallel_channel_k, inputs.header_segment_k)
    if insert_id == "FI-000":
        props = water_properties(temperature_c)
        port_area = np.pi * geometry.drilled_passage_diameter_m**2 / 4.0
        velocity = q / port_area
        coarse_k = inputs.plenum_k
        drop = coarse_k * props.density_kg_m3 * velocity**2 / 2.0
        return HydraulicResult(insert_id, flow_lpm, float(drop), None, None, 0.0, ["FI-000 uses a coarse port/plenum minor-loss model; no channel correlation is claimed."], {"model": "coarse plenum", "minor_loss_k": coarse_k, "port_diameter_m": geometry.drilled_passage_diameter_m}, applicability="coarse_plenum_assumption")
    raise ValueError(f"Unknown insert_id {insert_id!r}")
