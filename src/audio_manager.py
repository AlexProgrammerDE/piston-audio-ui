"""
Audio Management module for PipeWire/PulseAudio.

This module provides:
- Audio output device listing and selection
- Volume control
- Audio sink management for Bluetooth A2DP
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
from dataclasses import dataclass
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class AudioBackend(Enum):
    """Supported audio backends."""
    PIPEWIRE = "pipewire"
    PULSEAUDIO = "pulseaudio"
    UNKNOWN = "unknown"


@dataclass
class AudioSink:
    """Represents an audio output sink."""
    id: int
    name: str
    description: str
    is_default: bool = False
    volume: float = 100.0
    muted: bool = False
    state: str = "unknown"
    
    @property
    def display_name(self) -> str:
        """Get a user-friendly display name."""
        return self.description or self.name


@dataclass
class AudioSource:
    """Represents an audio input source."""
    id: int
    name: str
    description: str
    is_default: bool = False
    volume: float = 100.0
    muted: bool = False


class AudioManager:
    """
    Manager for audio output control.
    
    Supports both PipeWire and PulseAudio backends.
    Provides methods for:
    - Listing audio sinks (outputs)
    - Setting default sink
    - Volume control
    - Mute/unmute
    """
    
    def __init__(self):
        self._backend = AudioBackend.UNKNOWN
        self._detect_backend()
        
    def _detect_backend(self) -> None:
        """Detect the available audio backend."""
        # Check for PipeWire first (it's the newer standard)
        if shutil.which("pw-cli"):
            self._backend = AudioBackend.PIPEWIRE
            logger.info("Detected PipeWire audio backend")
        elif shutil.which("pactl"):
            self._backend = AudioBackend.PULSEAUDIO
            logger.info("Detected PulseAudio backend")
        else:
            logger.warning("No supported audio backend found")
            self._backend = AudioBackend.UNKNOWN
            
    @property
    def backend(self) -> AudioBackend:
        """Get the detected audio backend."""
        return self._backend
        
    async def _run_command(self, *args: str) -> tuple[str, str, int]:
        """Run a shell command and return stdout, stderr, returncode."""
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            return stdout.decode(), stderr.decode(), proc.returncode or 0
        except Exception as e:
            logger.error(f"Command failed: {args}: {e}")
            return "", str(e), 1
            
    async def get_sinks(self) -> list[AudioSink]:
        """Get all available audio sinks."""
        if self._backend == AudioBackend.PIPEWIRE:
            return await self._get_sinks_pipewire()
        elif self._backend == AudioBackend.PULSEAUDIO:
            return await self._get_sinks_pulseaudio()
        return []
        
    async def _get_sinks_pipewire(self) -> list[AudioSink]:
        """Get sinks using PipeWire/pactl."""
        # PipeWire provides pactl compatibility
        return await self._get_sinks_pulseaudio()
        
    async def _get_sinks_pulseaudio(self) -> list[AudioSink]:
        """Get sinks using pactl."""
        sinks = []
        
        # Get default sink name
        stdout, _, _ = await self._run_command("pactl", "get-default-sink")
        default_sink = stdout.strip()
        
        # List all sinks
        stdout, _, returncode = await self._run_command("pactl", "-f", "json", "list", "sinks")
        
        if returncode != 0:
            # Fallback to non-JSON format
            return await self._get_sinks_pulseaudio_legacy()
            
        try:
            data = json.loads(stdout)
            for sink in data:
                volume = 100.0
                if "volume" in sink:
                    # Get average volume across channels
                    volumes = []
                    for channel, vol_info in sink["volume"].items():
                        if isinstance(vol_info, dict) and "value_percent" in vol_info:
                            vol_str = vol_info["value_percent"].rstrip("%")
                            try:
                                volumes.append(float(vol_str))
                            except ValueError:
                                pass
                    if volumes:
                        volume = sum(volumes) / len(volumes)
                        
                sinks.append(AudioSink(
                    id=sink.get("index", 0),
                    name=sink.get("name", ""),
                    description=sink.get("description", ""),
                    is_default=sink.get("name") == default_sink,
                    volume=volume,
                    muted=sink.get("mute", False),
                    state=sink.get("state", "unknown"),
                ))
        except json.JSONDecodeError:
            return await self._get_sinks_pulseaudio_legacy()
            
        return sinks
        
    async def _get_sinks_pulseaudio_legacy(self) -> list[AudioSink]:
        """Parse sinks from non-JSON pactl output."""
        sinks = []
        
        # Get default sink
        stdout, _, _ = await self._run_command("pactl", "get-default-sink")
        default_sink = stdout.strip()
        
        # List sinks
        stdout, _, _ = await self._run_command("pactl", "list", "sinks")
        
        current_sink: dict = {}
        
        for line in stdout.split("\n"):
            line = line.strip()
            
            if line.startswith("Sink #"):
                if current_sink:
                    sinks.append(AudioSink(
                        id=current_sink.get("id", 0),
                        name=current_sink.get("name", ""),
                        description=current_sink.get("description", ""),
                        is_default=current_sink.get("name") == default_sink,
                        volume=current_sink.get("volume", 100.0),
                        muted=current_sink.get("muted", False),
                        state=current_sink.get("state", "unknown"),
                    ))
                current_sink = {"id": int(line.split("#")[1])}
            elif line.startswith("Name:"):
                current_sink["name"] = line.split(":", 1)[1].strip()
            elif line.startswith("Description:"):
                current_sink["description"] = line.split(":", 1)[1].strip()
            elif line.startswith("State:"):
                current_sink["state"] = line.split(":", 1)[1].strip().lower()
            elif line.startswith("Mute:"):
                current_sink["muted"] = "yes" in line.lower()
            elif line.startswith("Volume:"):
                # Parse volume percentage
                match = re.search(r"(\d+)%", line)
                if match:
                    current_sink["volume"] = float(match.group(1))
                    
        # Don't forget the last sink
        if current_sink:
            sinks.append(AudioSink(
                id=current_sink.get("id", 0),
                name=current_sink.get("name", ""),
                description=current_sink.get("description", ""),
                is_default=current_sink.get("name") == default_sink,
                volume=current_sink.get("volume", 100.0),
                muted=current_sink.get("muted", False),
                state=current_sink.get("state", "unknown"),
            ))
            
        return sinks
        
    async def set_default_sink(self, sink_name: str) -> bool:
        """Set the default audio sink."""
        _, _, returncode = await self._run_command("pactl", "set-default-sink", sink_name)
        
        if returncode == 0:
            logger.info(f"Default sink set to: {sink_name}")
            return True
        else:
            logger.error(f"Failed to set default sink: {sink_name}")
            return False
            
    async def set_volume(self, sink_name: str, volume: int) -> bool:
        """Set volume for a sink (0-100)."""
        volume = max(0, min(150, volume))  # Allow up to 150% for boost
        _, _, returncode = await self._run_command(
            "pactl", "set-sink-volume", sink_name, f"{volume}%"
        )
        
        if returncode == 0:
            logger.info(f"Volume set to {volume}% for {sink_name}")
            return True
        else:
            logger.error(f"Failed to set volume for {sink_name}")
            return False
            
    async def set_mute(self, sink_name: str, mute: bool) -> bool:
        """Mute or unmute a sink."""
        mute_str = "1" if mute else "0"
        _, _, returncode = await self._run_command(
            "pactl", "set-sink-mute", sink_name, mute_str
        )
        
        if returncode == 0:
            logger.info(f"Sink {sink_name} mute: {mute}")
            return True
        else:
            logger.error(f"Failed to set mute for {sink_name}")
            return False
            
    async def toggle_mute(self, sink_name: str) -> bool:
        """Toggle mute state for a sink."""
        _, _, returncode = await self._run_command(
            "pactl", "set-sink-mute", sink_name, "toggle"
        )
        return returncode == 0
        
    async def get_default_sink(self) -> Optional[AudioSink]:
        """Get the default sink."""
        sinks = await self.get_sinks()
        for sink in sinks:
            if sink.is_default:
                return sink
        return None
        
    async def get_bluetooth_sinks(self) -> list[AudioSink]:
        """Get only Bluetooth audio sinks."""
        sinks = await self.get_sinks()
        return [s for s in sinks if "bluetooth" in s.name.lower() or "bluez" in s.name.lower()]
        

class EqualizerManager:
    """
    Manager for audio equalizer settings.
    
    Supports PulseAudio equalizer (pulseaudio-equalizer) if available.
    """
    
    def __init__(self):
        self._available = self._check_available()
        
    def _check_available(self) -> bool:
        """Check if equalizer is available."""
        return shutil.which("pulseaudio-equalizer") is not None
        
    @property
    def available(self) -> bool:
        """Check if equalizer is available."""
        return self._available
        
    async def _run_command(self, *args: str) -> tuple[str, str, int]:
        """Run a shell command."""
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            return stdout.decode(), stderr.decode(), proc.returncode or 0
        except Exception as e:
            return "", str(e), 1
            
    async def enable(self) -> bool:
        """Enable the equalizer."""
        if not self._available:
            return False
        _, _, code = await self._run_command("pulseaudio-equalizer", "enable")
        return code == 0
        
    async def disable(self) -> bool:
        """Disable the equalizer."""
        if not self._available:
            return False
        _, _, code = await self._run_command("pulseaudio-equalizer", "disable")
        return code == 0


class BluetoothAudioConfig:
    """
    Configuration for Bluetooth audio.
    
    Handles BlueZ and audio backend configuration for A2DP sink mode.
    """
    
    @staticmethod
    async def get_bluetooth_audio_status() -> dict:
        """Get current Bluetooth audio status."""
        status = {
            "a2dp_sink_available": False,
            "bluetooth_audio_enabled": False,
            "current_codec": None,
        }
        
        # Check if bluetooth audio module is loaded
        try:
            proc = await asyncio.create_subprocess_exec(
                "pactl", "list", "modules",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            output = stdout.decode()
            
            status["bluetooth_audio_enabled"] = (
                "module-bluetooth-discover" in output or
                "module-bluez5-discover" in output
            )
        except Exception as e:
            logger.warning(f"Failed to check Bluetooth audio status: {e}")
            
        # Check for A2DP sink
        try:
            proc = await asyncio.create_subprocess_exec(
                "pactl", "-f", "json", "list", "cards",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            
            try:
                cards = json.loads(stdout.decode())
                for card in cards:
                    profiles = card.get("profiles", {})
                    for profile_name in profiles:
                        if "a2dp" in profile_name.lower():
                            status["a2dp_sink_available"] = True
                            break
            except json.JSONDecodeError:
                pass
        except Exception as e:
            logger.warning(f"Failed to check A2DP status: {e}")
            
        return status
        
    @staticmethod
    async def set_bluetooth_card_profile(card_name: str, profile: str) -> bool:
        """Set the profile for a Bluetooth audio card."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "pactl", "set-card-profile", card_name, profile,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, _ = await proc.communicate()
            return proc.returncode == 0
        except Exception as e:
            logger.error(f"Failed to set card profile: {e}")
            return False
