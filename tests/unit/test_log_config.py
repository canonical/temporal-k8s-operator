# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for log configuration."""

import yaml

from charm import render
from literals import LOG_FORMAT, LOG_OUTPUT_FILE


def test_log_config_renders_with_file_output():
    """Test that log configuration includes file output settings."""
    context = {
        "LOG_LEVEL": "info",
        "LOG_OUTPUT_FILE": LOG_OUTPUT_FILE,
        "LOG_FORMAT": LOG_FORMAT,
    }
    
    config = render("config.jinja", context)
    parsed = yaml.safe_load(config)
    
    # Verify log section exists
    assert "log" in parsed
    
    # Verify stdout is disabled (file-only logging)
    assert parsed["log"]["stdout"] is False
    
    # Verify file output is configured
    assert parsed["log"]["outputFile"] == LOG_OUTPUT_FILE
    assert parsed["log"]["outputFile"] == "/var/log/temporal/server.log"
    
    # Verify JSON format
    assert parsed["log"]["format"] == LOG_FORMAT
    assert parsed["log"]["format"] == "json"
    
    # Verify log level
    assert parsed["log"]["level"] == "info"


def test_log_config_respects_log_level():
    """Test that log level can be changed."""
    for level in ["debug", "info", "warning", "error"]:
        context = {
            "LOG_LEVEL": level,
            "LOG_OUTPUT_FILE": LOG_OUTPUT_FILE,
            "LOG_FORMAT": LOG_FORMAT,
        }
        
        config = render("config.jinja", context)
        parsed = yaml.safe_load(config)
        
        assert parsed["log"]["level"] == level
