"""Streamlit entry point showing the actual scaffold status."""


def main() -> None:
    """Render project status without inventing model or simulation results."""
    import streamlit as st

    st.set_page_config(page_title="GulfOilGuard-AI", layout="wide")
    st.title("GulfOilGuard-AI")
    st.write("Oil spill detection, drift prediction, and cleanup planning.")
    st.info("Project scaffold: detection, drift simulation, and routing await implementation.")
    for title, description in (
        ("Detection", "Satellite imagery and predicted masks will appear here."),
        ("Drift prediction", "Georeferenced trajectories for 6, 12, and 24 hours will appear here."),
        ("Cleanup optimization", "Vessel assignments and routes will appear here."),
    ):
        st.subheader(title)
        st.write(description)


if __name__ == "__main__":
    main()
