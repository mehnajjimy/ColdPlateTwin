"""local viewer for the same run bundles produced by demo and CSV import."""

import argparse
from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st
from coldplatetwin.bundle import load_bundles, matched_comparisons
from coldplatetwin.configuration import AnalysisConfig


def main(data_path=None):
    """draw the dashboard for the bundles in data_path, or in --data when it is not given."""

    # streamlit passes our own arguments after "--". ignore anything else.
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--data", type=Path, default=Path("outputs/demo"))
    args, _ = parser.parse_known_args()
    path = Path(data_path) if data_path else args.data

    # page header and bundle loading
    st.set_page_config(page_title="ColdPlateTwin", layout="wide")
    st.title("ColdPlateTwin experiment analysis")
    try:
        bundles = load_bundles(path)
    except (OSError, ValueError, KeyError) as error:
        st.error(f"Cannot open analysis: {error}")
        return

    # run picker and data-source banner
    names = [item["run_id"] for item, _ in bundles]
    selected_id = st.selectbox("Run", names)
    selected, root = bundles[names.index(selected_id)]
    st.warning("SYNTHETIC DATA" if selected["source"] == "synthetic" else "EXPERIMENTAL DATA")
    metadata = selected["provenance"]["metadata"]
    st.caption(f"Insert: {selected['insert_id']} | Geometry: {metadata['geometry_hash'][:12]}")

    # calibrated time traces
    st.subheader("Calibrated time traces")
    frame = pd.read_csv(root / selected["artifacts"]["calibrated_csv"], parse_dates=["timestamp"])
    st.line_chart(frame.set_index("timestamp")[["tin_c", "tout_c"]])
    st.line_chart(frame.set_index("timestamp")[["flow_lpm"]])

    # energy balance and uncertainty, or the reasons a run was rejected
    st.subheader("Energy and uncertainty")
    if selected["steady_state"]["passed"]:
        metrics = selected["metrics"]
        for label, key in (("Electrical power", "electrical_power_synchronized_vi_w"),
                           ("Heat to water", "heat_to_water_enthalpy_w"),
                           ("Unaccounted residual", "unaccounted_energy_residual_w")):
            st.metric(label, f"{metrics[key]:.2f} W")
        table = pd.DataFrame(selected["uncertainties"]).T
        if not table.empty:
            st.dataframe(table[["value", "analytical_standard", "monte_carlo_standard", "status"]])
        else:
            st.info("Uncertainties unavailable; inspect the missing sensor specifications below.")
    else:
        st.error("Run rejected: " + "; ".join(selected["steady_state"]["reasons"]))

    # one radiometric frame of this run, marked as inside or outside the averaging interval
    st.subheader("This run's radiometric frames")
    ir = selected["artifacts"].get("radiometric")
    if ir:
        with np.load(root / ir["file"], allow_pickle=False) as archive:
            frames = archive["temperatures_c"]
        index = st.selectbox("Frame", list(range(len(frames))))
        if ir["timestamps"] is not None:
            stamp = ir["timestamps"][index]
        else:
            stamp = "Time unavailable"
        if index in ir["accepted_frame_indices"]:
            interval_note = "inside accepted averaging interval"
        else:
            interval_note = "excluded from steady thermal metrics"
        st.caption(f"{stamp} | " + interval_note)
        fig, ax = plt.subplots(figsize=(5, 4))
        image = ax.imshow(frames[index], origin="lower", cmap="inferno")
        fig.colorbar(image, ax=ax, label="Temperature (°C)")
        ax.set_title(f"{selected['source'].upper()} - {selected_id}")
        st.pyplot(fig)
        plt.close(fig)
        if selected.get("roi"):
            st.write("ROI statistics of the sampled mean map", selected["roi"])
    else:
        st.info("No IR frames were supplied for this run.")

    # matched comparisons across all bundles, using the selected run's tolerances
    st.subheader("Matched-condition comparisons")
    effective = selected["provenance"]["analysis_configuration"]
    config = AnalysisConfig()
    config.comparison_flow_tolerance_lpm = effective["comparison_flow_tolerance_lpm"]
    config.comparison_power_tolerance_w = effective["comparison_power_tolerance_w"]
    config.comparison_inlet_tolerance_k = effective["comparison_inlet_tolerance_k"]
    comparisons = matched_comparisons([item for item, _ in bundles], config)
    if comparisons:
        st.dataframe(pd.DataFrame(comparisons))
        st.caption("Differences retain covariance from shared calibration records.")
    else:
        st.info("No pair meets the source, geometry, flow, power and inlet-temperature matching criteria.")

    # raw criteria, warnings and provenance for inspection
    with st.expander("Criteria, provenance and limitations"):
        st.json(selected["steady_state"]["criteria"])
        for warning in selected["warnings"]:
            st.write(warning)
        st.json(selected["provenance"])


if __name__ == "__main__":
    main()
