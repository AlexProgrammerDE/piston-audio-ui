"""Tests for the audio manager module."""

import pytest

from src.audio_manager import AudioBackend, AudioManager, AudioSink


class TestAudioSink:
    """Tests for AudioSink dataclass."""

    def test_display_name_with_description(self):
        """Test that display_name returns description when available."""
        sink = AudioSink(
            id=1,
            name="alsa_output.usb",
            description="USB Audio Device",
        )
        assert sink.display_name == "USB Audio Device"

    def test_display_name_fallback(self):
        """Test that display_name falls back to name."""
        sink = AudioSink(
            id=1,
            name="alsa_output.usb",
            description="",
        )
        assert sink.display_name == "alsa_output.usb"

    def test_default_values(self):
        """Test default values for AudioSink."""
        sink = AudioSink(id=1, name="test", description="Test")
        assert sink.is_default is False
        assert sink.volume == 100.0
        assert sink.muted is False
        assert sink.state == "unknown"


class TestAudioManager:
    """Tests for AudioManager class."""

    def test_backend_detection(self):
        """Test that backend is detected."""
        manager = AudioManager()
        # Should be one of the known backends
        assert manager.backend in [
            AudioBackend.PIPEWIRE,
            AudioBackend.PULSEAUDIO,
            AudioBackend.UNKNOWN,
        ]

    @pytest.mark.asyncio
    async def test_get_sinks_returns_list(self):
        """Test that get_sinks returns a list."""
        manager = AudioManager()
        sinks = await manager.get_sinks()
        assert isinstance(sinks, list)

    @pytest.mark.asyncio
    async def test_get_bluetooth_sinks(self):
        """Test filtering for Bluetooth sinks."""
        manager = AudioManager()
        bt_sinks = await manager.get_bluetooth_sinks()
        assert isinstance(bt_sinks, list)
        # All returned sinks should have bluetooth in name
        for sink in bt_sinks:
            assert "bluetooth" in sink.name.lower() or "bluez" in sink.name.lower()
