"""Single source of truth shared by CAD generation and engineering calculations.

All linear dimensions are millimetres, angles are degrees, pressure is MPa,
and temperatures are degrees Celsius unless a field explicitly says otherwise.
"""

from dataclasses import dataclass
from math import pi


@dataclass(frozen=True)
class RevA:
    revision: str = "Rev A preliminary engineering"
    datum_note: str = "CP-001 upper sealing deck z=0; cavity center x=y=0; ports on x-axis"
    ordinary_tolerance: float = 0.10

    base_xy: float = 200.00
    base_thickness: float = 25.00
    base_envelope_tol: float = 0.10
    stock_xy: float = 203.2
    stock_thickness: float = 25.4
    cavity_diameter: float = 165.00
    cavity_diameter_plus: float = 0.05
    cavity_depth: float = 5.00
    cavity_depth_tol: float = 0.02
    deck_flatness: float = 0.02
    pocket_floor_flatness: float = 0.03

    main_or_id: float = 171.12
    main_or_cs: float = 2.62
    main_groove_od: float = 176.35
    main_groove_width: float = 3.70
    main_groove_depth: float = 2.12
    main_groove_depth_tol: float = 0.02
    main_groove_bottom_r: float = 0.30
    main_groove_position: float = 0.05

    cover_xy: float = 200.00
    cover_thickness: float = 5.50
    cover_thickness_tol: float = 0.05
    cover_flatness: float = 0.03
    cover_parallelism: float = 0.03

    structural_clamp_xy: float = 200.00
    structural_clamp_aperture: float = 166.00
    structural_clamp_aperture_plus: float = 0.10
    structural_clamp_thickness: float = 8.00
    structural_clamp_thickness_tol: float = 0.10

    bolt_count: int = 16
    bolt_pcd: float = 188.00
    bolt_offset_deg: float = 11.25
    clearance_hole_diameter: float = 5.50
    clearance_hole_plus: float = 0.10
    screw_nominal_length: float = 25.0
    screw_head_diameter: float = 8.5
    screw_head_height: float = 5.0
    washer_od: float = 10.0
    washer_id: float = 5.3
    washer_thickness: float = 1.0
    tapped_hole_diameter_model: float = 4.2
    tapped_hole_depth: float = 12.0
    drill_point_allowance: float = 1.0

    insert_od: float = 163.60
    insert_od_tol: float = 0.05
    floor_thickness: float = 1.00
    floor_thickness_tol: float = 0.03
    channel_height: float = 4.00
    channel_height_tol: float = 0.05
    rib_width: float = 4.00
    rib_width_tol: float = 0.05
    gasket_support_from_underside: float = 3.50
    gasket_support_tol: float = 0.03
    rib_gasket_free_thickness: float = 2.00
    rib_gasket_thickness_tol: float = 0.05
    rib_gasket_width: float = 2.00
    rib_gasket_width_tol: float = 0.05
    rib_gasket_installed_height: float = 1.50
    service_gap_min: float = 1.35
    service_gap_max: float = 1.75

    locator_pin_diameter: float = 4.0
    locator_clearance: float = 0.10
    locator_radius: float = 55.0
    radial_slot_length: float = 7.0
    polymer_cte_per_k: float = 130e-6
    aluminum_cte_per_k: float = 23.6e-6
    temperature_min: float = 20.0
    temperature_max: float = 60.0
    reserved_growth_diametral: float = 0.20

    side_port_axis_z: float = -14.0
    transfer_x: float = 70.0
    drilled_passage_diameter: float = 6.0
    insert_transfer_diameter: float = 7.20
    insert_transfer_tol: float = 0.05
    npt_thread_envelope_diameter: float = 13.70
    npt_thread_length_candidate: float = 13.5
    tap_bore_diameter: float = 1.5
    tap_thread_model_diameter: float = 5.0
    tap_axis_y: float = -100.0

    transfer_or_id: float = 10.82
    transfer_or_cs: float = 1.78
    transfer_groove_od: float = 14.38
    transfer_groove_width: float = 2.50
    transfer_groove_depth: float = 1.35
    transfer_groove_depth_tol: float = 0.02

    fi100_channel_width: float = 8.00
    fi100_pass_count: int = 9
    fi100_pitch: float = 12.0
    fi100_straight_length: float = 96.0
    fi100_return_radius: float = 6.0

    fi200_channel_width: float = 8.0
    fi200_centers_y: tuple[float, ...] = (-42, -30, -18, -6, 6, 18, 30, 42)
    fi200_straight_length: float = 96.0
    fi200_header_width: float = 12.0
    fi300_header_end_width: float = 6.0

    payload_diameter: float = 160.0
    payload_thickness: float = 2.0
    payload_thickness_tol: float = 0.05
    roi_diameter: float = 150.0
    heater_envelope_diameter: float = 150.0
    heater_placeholder_thickness: float = 1.0
    payload_clamp_od: float = 164.0
    payload_clamp_id: float = 150.5
    payload_clamp_thickness: float = 4.0

    pressure_mpa: float = 0.030
    max_additional_cover_opening: float = 0.10
    max_local_seal_opening: float = 0.03
    elastic_modulus_aluminum_mpa: float = 69000.0
    poisson_aluminum: float = 0.33

    bracket_plate_thickness: float = 6.0
    bracket_width: float = 30.0
    bracket_leg_length: float = 45.0
    bracket_mount_x: float = 75.0
    bracket_mount_y: float = 75.0
    bracket_base_hole_diameter: float = 5.0
    bracket_bench_hole_diameter: float = 8.0

    @property
    def bolt_radius(self) -> float:
        return self.bolt_pcd / 2.0

    @property
    def main_groove_id(self) -> float:
        return self.main_groove_od - 2.0 * self.main_groove_width

    @property
    def transfer_groove_id(self) -> float:
        return self.transfer_groove_od - 2.0 * self.transfer_groove_width

    @property
    def insert_bottom_z(self) -> float:
        return -self.cavity_depth

    @property
    def insert_floor_top_z(self) -> float:
        return -self.cavity_depth + self.floor_thickness

    @property
    def rib_support_z(self) -> float:
        return -self.cavity_depth + self.gasket_support_from_underside

    @property
    def pressure_force_n(self) -> float:
        return self.pressure_mpa * pi * (self.cavity_diameter / 2.0) ** 2


P = RevA()


MATERIALS = {
    "CP-001": "6061-T6 aluminum, stress-relieved stock where available",
    "CP-002": "6061-T6 aluminum, preliminary",
    "FI-000": "POM-C/acetal final candidate; PETG prototype only",
    "FI-100": "POM-C/acetal final candidate; PETG prototype only",
    "FI-200": "POM-C/acetal final candidate; PETG prototype only",
    "FI-300": "POM-C/acetal final candidate; PETG prototype only",
    "TH-001": "Aluminum, preliminary; coating TBD",
    "CL-001": "Aluminum, preliminary",
    "CL-002": "Steel or aluminum subject to clamp analysis",
    "BR-001": "Aluminum angle/plate, preliminary",
    "GS-001": "AS568-166 nominal 70A EPDM candidate; supplier data required",
    "GS-013": "AS568-013 nominal EPDM candidate; supplier data required",
    "GS-RIB": "2 mm compliant sheet/strip; compound and force data unresolved",
}
