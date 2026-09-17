"""Deterministic Rev A screening calculations; imports the CAD configuration."""

from __future__ import annotations

import json
from math import pi, sqrt
from pathlib import Path

from .config import P


def calculate() -> dict:
    dt = P.temperature_max - P.temperature_min
    hot_insert_max = (P.insert_od + P.insert_od_tol) * (1 + P.polymer_cte_per_k * dt)
    cold_cavity_min = P.cavity_diameter
    thermal_clearance = cold_cavity_min - hot_insert_max

    nominal_squeeze = (P.main_or_cs - P.main_groove_depth) / P.main_or_cs
    min_squeeze_with_opening = (
        P.main_or_cs - (P.main_groove_depth + P.main_groove_depth_tol + P.max_local_seal_opening)
    ) / P.main_or_cs
    max_squeeze = (
        P.main_or_cs - (P.main_groove_depth - P.main_groove_depth_tol)
    ) / P.main_or_cs
    main_ring_area = pi * (P.main_or_cs / 2) ** 2
    main_gland_area = P.main_groove_width * P.main_groove_depth
    gland_fill = main_ring_area / main_gland_area
    groove_center_d = P.main_groove_od - P.main_groove_width
    ring_center_d = P.main_or_id + P.main_or_cs

    d = P.elastic_modulus_aluminum_mpa * P.cover_thickness**3 / (
        12 * (1 - P.poisson_aluminum**2)
    )
    radius = 83.0
    q = P.pressure_mpa
    clamped_deflection = q * radius**4 / (64 * d)
    simply_supported_screen = 4.0 * clamped_deflection

    screw_engagement_nominal = P.screw_nominal_length - (
        P.washer_thickness + P.structural_clamp_thickness + P.cover_thickness
    )
    screw_engagement_min = P.screw_nominal_length - (
        (P.washer_thickness + 0.10)
        + (P.structural_clamp_thickness + P.structural_clamp_thickness_tol)
        + (P.cover_thickness + P.cover_thickness_tol)
    )
    screw_engagement_max = P.screw_nominal_length - (
        (P.washer_thickness - 0.10)
        + (P.structural_clamp_thickness - P.structural_clamp_thickness_tol)
        + (P.cover_thickness - P.cover_thickness_tol)
    )

    channel_height_min = (P.cavity_depth - P.cavity_depth_tol) - (
        P.floor_thickness + P.floor_thickness_tol
    )
    channel_height_max = (P.cavity_depth + P.cavity_depth_tol) - (
        P.floor_thickness - P.floor_thickness_tol
    )
    fi100_transition = sqrt(22.0**2 + 48.0**2)
    fi100_path = (
        P.fi100_pass_count * P.fi100_straight_length
        + (P.fi100_pass_count - 1) * pi * P.fi100_return_radius
        + 2 * fi100_transition
    )
    thread_bottom_wall = P.base_thickness + P.side_port_axis_z - P.npt_thread_envelope_diameter / 2
    drilled_bottom_wall = P.base_thickness + P.side_port_axis_z - P.drilled_passage_diameter / 2

    return {
        "revision": P.revision,
        "units": "mm, N, MPa, degrees C unless noted",
        "coordinate_system": P.datum_note,
        "external_seal": {
            "nominal_squeeze_percent": 100 * nominal_squeeze,
            "minimum_squeeze_with_0p03_opening_percent": 100 * min_squeeze_with_opening,
            "maximum_squeeze_nominal_cs_percent": 100 * max_squeeze,
            "nominal_2d_gland_fill_percent": 100 * gland_fill,
            "groove_centerline_diameter": groove_center_d,
            "oring_centerline_diameter": ring_center_d,
            "centerline_fit_percent": 100 * (groove_center_d - ring_center_d) / ring_center_d,
            "status": "PRELIMINARY: verify actual ring tolerance, compound, swelling, thermal exposure, and Parker axial-face-seal rules",
        },
        "thermal_insert_fit": {
            "cold_minimum_diametral_clearance": P.cavity_diameter - (P.insert_od + P.insert_od_tol),
            "hot_insert_cold_base_clearance": thermal_clearance,
            "clearance_after_reserved_growth": thermal_clearance - P.reserved_growth_diametral,
            "hot_insert_max_diameter": hot_insert_max,
            "status": "passes dimensional screening; conditioned-polymer measurement remains required",
        },
        "assembled_height_budget": {
            "nominal_channel_height": P.cavity_depth - P.floor_thickness,
            "worst_case_min": channel_height_min,
            "worst_case_max": channel_height_max,
            "specified_range": [P.channel_height - P.channel_height_tol, P.channel_height + P.channel_height_tol],
            "status": "exactly consumes tolerance band before flatness; match-finish insert floor to measured base",
        },
        "pressure_screening": {
            "pressure_mpa": P.pressure_mpa,
            "resultant_force_n": P.pressure_force_n,
            "load_per_fastener_from_pressure_only_n": P.pressure_force_n / P.bolt_count,
            "ideal_clamped_deflection_mm": clamped_deflection,
            "simply_supported_screen_mm": simply_supported_screen,
            "allowable_additional_opening_mm": P.max_additional_cover_opening,
            "status": "screen only; gasket reaction, preload, flange compliance, contact, and thermal distortion unresolved",
        },
        "hardware_stack": {
            "nominal_engagement_mm": screw_engagement_nominal,
            "worst_case_min_engagement_mm": screw_engagement_min,
            "worst_case_max_engagement_mm": screw_engagement_max,
            "modeled_full_thread_depth_mm": P.tapped_hole_depth,
            "drill_point_clearance_to_port_envelope_mm": 1.0,
            "status": "select actual M5x25 screw/washer and verify thread runout; torque not specified",
        },
        "port_screening": {
            "thread_envelope_bottom_wall_mm": thread_bottom_wall,
            "drilled_passage_bottom_wall_mm": drilled_bottom_wall,
            "candidate_thread_length_mm": P.npt_thread_length_candidate,
            "status": "actual 1/4-18 NPT fitting geometry and engagement required before release",
        },
        "internal_gasket": {
            "nominal_compression_percent": 100 * (P.rib_gasket_free_thickness - P.rib_gasket_installed_height) / P.rib_gasket_free_thickness,
            "service_compression_range_percent": [
                100 * (P.rib_gasket_free_thickness - P.service_gap_max) / P.rib_gasket_free_thickness,
                100 * (P.rib_gasket_free_thickness - P.service_gap_min) / P.rib_gasket_free_thickness,
            ],
            "status": "geometry only; compound, force/deflection, compression set, bulging, and retention test unresolved",
        },
        "flow": {
            "fi100_cad_centerline_path_length_mm": fi100_path,
            "fi100_note": "9 x 96 straight passes, 8 semicircular R6 returns, and two modeled diagonal feed transitions",
            "fi200_parallel_channel_length_mm": P.fi200_straight_length,
            "fi200_channel_count": len(P.fi200_centers_y),
            "fi300_status": "tapered-manifold candidate; hydraulic improvement not demonstrated",
        },
    }


def write_results(path: Path) -> dict:
    results = calculate()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(results, indent=2) + "\n")
    return results


if __name__ == "__main__":
    print(json.dumps(calculate(), indent=2))
