"""corrected rev a arithmetic screening, versioned apart from the cad release."""

from __future__ import annotations

from .geometry import _find_config, _load_parameter_object


REPORT_VERSION = "corrected-screening-1.0"


# --- corrected screening report ---

def corrected_screening(config_path=None) -> dict:
    """redo the known rev a arithmetic slips without changing the cad release."""

    p = _load_parameter_object(_find_config(config_path))

    # cover plate deflection at the thinnest allowed cover, in mm and mpa
    cover_min = p.cover_thickness - p.cover_thickness_tol
    flexural_rigidity = p.elastic_modulus_aluminum_mpa * cover_min**3 / (12.0 * (1.0 - p.poisson_aluminum**2))
    radius = 83.0  # fixed plate radius of the rev a screening, mm
    clamped = p.pressure_mpa * radius**4 / (64.0 * flexural_rigidity)
    simply_supported_factor = (5.0 + p.poisson_aluminum) / (1.0 + p.poisson_aluminum)
    simply_supported = simply_supported_factor * clamped

    # rib gasket compression over the free-thickness tolerance and service gap
    gasket_free_min = p.rib_gasket_free_thickness - p.rib_gasket_thickness_tol
    gasket_free_max = p.rib_gasket_free_thickness + p.rib_gasket_thickness_tol
    rib_min = 100.0 * (gasket_free_min - p.service_gap_max) / gasket_free_min
    rib_max = 100.0 * (gasket_free_max - p.service_gap_min) / gasket_free_max

    # main o-ring squeeze, only known for the nominal cross-section
    deepest_gland = p.main_groove_depth + p.main_groove_depth_tol + p.max_local_seal_opening
    nominal_squeeze_min = 100.0 * (p.main_or_cs - deepest_gland) / p.main_or_cs

    return {
        "report_version": REPORT_VERSION,
        "does_not_modify_cad_release": True,
        "external_o_ring_squeeze": {
            "numeric_worst_case_interval": None,
            "reason": "AS568-166 cross-section tolerance is absent from the Rev A brief; supplier minimum/maximum cross-section is required.",
            "conditional_nominal_cross_section_minimum_percent": nominal_squeeze_min,
        },
        "rib_gasket_service_compression_percent": {
            "minimum": rib_min,
            "maximum": rib_max,
            "uses_free_thickness_tolerance": True,
        },
        "cover_pressure_screening": {
            "cover_thickness_mm": cover_min,
            "clamped_uniform_load_mm": clamped,
            "simply_supported_uniform_load_mm": simply_supported,
            "simply_supported_to_clamped_factor": simply_supported_factor,
            "formula_note": "Classical small-deflection circular plate idealizations; gasket, preload, contact, square boundary and nonlinear response remain unresolved.",
        },
        "discrepancies": [
            {
                "item": "main O-ring minimum squeeze",
                "original": "nominal cross-section used",
                "corrected": "numeric worst case withheld until supplier cross-section tolerance is available",
            },
            {
                "item": "rib gasket service compression",
                "original": "12.5-32.5% using nominal 2.00 mm",
                "corrected": f"{rib_min:.2f}-{rib_max:.2f}% using 1.95-2.05 mm free-thickness tolerance",
            },
            {
                "item": "simply supported cover",
                "original": "four times nominal-thickness clamped result",
                "corrected": f"factor {simply_supported_factor:.4f} from (5+nu)/(1+nu), using minimum 5.45 mm thickness",
            },
        ],
    }
