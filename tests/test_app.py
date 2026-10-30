"""Tests for Streamlit application startup and rendering (app.py).

Tests do not require an active MongoDB server.
"""

from streamlit.testing.v1 import AppTest


def test_streamlit_app_starts_without_crash():
    at = AppTest.from_file("app.py").run()
    assert not at.exception


def test_streamlit_dashboard_renders_title():
    at = AppTest.from_file("app.py").run()
    assert not at.exception

    titles = [t.value for t in at.title]
    assert any("GRANIT EU Data Manager" in t for t in titles), titles


def test_streamlit_sidebar_navigation_present():
    at = AppTest.from_file("app.py").run()
    assert not at.exception

    labels = [w.label for w in at.sidebar.radio]
    assert any("Go to" in label for label in labels), labels
