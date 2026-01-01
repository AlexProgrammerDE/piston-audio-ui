"""Pytest configuration and fixtures."""

import pytest


@pytest.fixture
def mock_sink():
    """Create a mock AudioSink for testing."""
    from src.audio_manager import AudioSink

    return AudioSink(
        id=1,
        name="alsa_output.pci-0000_00_1f.3.analog-stereo",
        description="Built-in Audio Analog Stereo",
        is_default=True,
        volume=75.0,
        muted=False,
        state="running",
    )


@pytest.fixture
def mock_bluetooth_device():
    """Create a mock BluetoothDevice for testing."""
    from src.bluetooth_agent import BluetoothDevice

    return BluetoothDevice(
        path="/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF",
        address="AA:BB:CC:DD:EE:FF",
        name="Test Phone",
        paired=True,
        trusted=True,
        connected=False,
        icon="phone",
    )
