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
    ALSA = "alsa"
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
        elif shutil.which("amixer"):
            self._backend = AudioBackend.ALSA
            logger.info("Detected ALSA audio backend (no PipeWire/PulseAudio)")
        else:
            logger.warning("No supported audio backend found")
            self._backend = AudioBackend.UNKNOWN
            
    @property
    def backend(self) -> AudioBackend:
        """Get the detected audio backend."""
        return self._backend
        
    async def _run_command(self, *args: str, env: Optional[dict] = None) -> tuple[str, str, int]:
        """Run a shell command and return stdout, stderr, returncode."""
        import os
        
        # Build environment with PipeWire/PulseAudio runtime dir
        cmd_env = os.environ.copy()
        
        # Try to find the correct runtime directory for audio
        # This is needed when running as a systemd service
        runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
        if not runtime_dir:
            # Try common locations
            uid = os.getuid()
            for possible_dir in [f"/run/user/{uid}", f"/tmp/pulse-{uid}"]:
                if os.path.exists(possible_dir):
                    runtime_dir = possible_dir
                    break
                    
        if runtime_dir:
            cmd_env["XDG_RUNTIME_DIR"] = runtime_dir
            
        # Set PULSE_RUNTIME_PATH if not set
        if "PULSE_RUNTIME_PATH" not in cmd_env and runtime_dir:
            pulse_path = os.path.join(runtime_dir, "pulse")
            if os.path.exists(pulse_path):
                cmd_env["PULSE_RUNTIME_PATH"] = pulse_path
                
        # For PipeWire
        if "PIPEWIRE_RUNTIME_DIR" not in cmd_env and runtime_dir:
            cmd_env["PIPEWIRE_RUNTIME_DIR"] = runtime_dir
            
        if env:
            cmd_env.update(env)
            
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=cmd_env,
            )
            stdout, stderr = await proc.communicate()
            return stdout.decode(), stderr.decode(), proc.returncode or 0
        except Exception as e:
            logger.error(f"Command failed: {args}: {e}")
            return "", str(e), 1
            
    async def get_sinks(self) -> list[AudioSink]:
        """Get all available audio sinks."""
        if self._backend == AudioBackend.PIPEWIRE:
            sinks = await self._get_sinks_pipewire()
            # If PipeWire returns empty, try ALSA fallback
            if not sinks:
                logger.warning("PipeWire returned no sinks, trying ALSA fallback")
                return await self._get_sinks_alsa()
            return sinks
        elif self._backend == AudioBackend.PULSEAUDIO:
            sinks = await self._get_sinks_pulseaudio()
            # If PulseAudio returns empty, try ALSA fallback
            if not sinks:
                logger.warning("PulseAudio returned no sinks, trying ALSA fallback")
                return await self._get_sinks_alsa()
            return sinks
        elif self._backend == AudioBackend.ALSA:
            return await self._get_sinks_alsa()
        return []
        
    async def _get_sinks_pipewire(self) -> list[AudioSink]:
        """Get sinks using native PipeWire tools (pw-dump, wpctl)."""
        sinks = []
        
        # First try pw-dump for JSON output
        stdout, stderr, returncode = await self._run_command("pw-dump")
        
        if returncode != 0:
            logger.warning(f"pw-dump failed: {stderr}")
            # Fall back to pactl if available
            if shutil.which("pactl"):
                return await self._get_sinks_pulseaudio()
            return []
            
        try:
            data = json.loads(stdout)
            
            # Get default sink ID using wpctl
            default_sink_id = await self._get_default_sink_id_pipewire()
            
            for obj in data:
                info = obj.get("info", {})
                props = info.get("props", obj.get("props", {}))
                
                # Filter for Audio/Sink nodes
                if props.get("media.class") != "Audio/Sink":
                    continue
                    
                node_id = obj.get("id", 0)
                node_name = props.get("node.name", "")
                
                # Get volume for this sink
                volume = await self._get_sink_volume_pipewire(node_id)
                muted = await self._get_sink_mute_pipewire(node_id)
                
                sinks.append(AudioSink(
                    id=node_id,
                    name=node_name,
                    description=props.get("node.description", props.get("node.nick", node_name)),
                    is_default=(node_id == default_sink_id),
                    volume=volume,
                    muted=muted,
                    state="running",  # PipeWire doesn't expose state the same way
                ))
                
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse pw-dump output: {e}")
            # Fall back to pactl if available
            if shutil.which("pactl"):
                return await self._get_sinks_pulseaudio()
                
        return sinks
        
    async def _get_default_sink_id_pipewire(self) -> Optional[int]:
        """Get the default sink ID using wpctl."""
        # wpctl status shows default sink with asterisk, but we need to parse it
        # Alternative: use pw-dump to find the default.audio.sink metadata
        stdout, _, returncode = await self._run_command("pw-dump")
        
        if returncode != 0:
            return None
            
        try:
            data = json.loads(stdout)
            
            # Find the default metadata
            for obj in data:
                info = obj.get("info", {})
                props = info.get("props", obj.get("props", {}))
                
                # Look for settings metadata
                if obj.get("type") == "PipeWire:Interface:Metadata":
                    metadata = info.get("metadata", [])
                    for entry in metadata:
                        if entry.get("key") == "default.audio.sink":
                            # Value contains the node name
                            value = entry.get("value", {})
                            if isinstance(value, dict):
                                sink_name = value.get("name", "")
                            else:
                                sink_name = str(value)
                            
                            # Find the node ID for this name
                            for obj2 in data:
                                info2 = obj2.get("info", {})
                                props2 = info2.get("props", obj2.get("props", {}))
                                if props2.get("node.name") == sink_name:
                                    return obj2.get("id")
        except (json.JSONDecodeError, KeyError, TypeError):
            pass
            
        # Fallback: parse wpctl status output
        stdout, _, returncode = await self._run_command("wpctl", "status")
        if returncode == 0:
            in_audio_section = False
            in_sinks = False
            for line in stdout.split("\n"):
                # Track when we're in the Audio section
                if line.startswith("Audio"):
                    in_audio_section = True
                    continue
                elif line.startswith("Video") or line.startswith("Settings"):
                    in_audio_section = False
                    in_sinks = False
                    continue
                    
                if not in_audio_section:
                    continue
                    
                if "Sinks:" in line:
                    in_sinks = True
                    continue
                elif "Sources:" in line or "Filters:" in line or "Streams:" in line:
                    in_sinks = False
                    continue
                    
                if in_sinks and "*" in line:
                    # Default sink marked with asterisk
                    # Format: " │  *   68. Built-in Audio Stereo"
                    match = re.search(r"\*\s+(\d+)\.", line)
                    if match:
                        return int(match.group(1))
                            
        return None
        
    async def _get_sink_volume_pipewire(self, node_id: int) -> float:
        """Get volume for a PipeWire sink using wpctl."""
        stdout, _, returncode = await self._run_command("wpctl", "get-volume", str(node_id))
        
        if returncode == 0:
            # Output: "Volume: 0.40" or "Volume: 0.40 [MUTED]"
            match = re.search(r"Volume:\s*([\d.]+)", stdout)
            if match:
                return float(match.group(1)) * 100  # Convert to percentage
                
        return 100.0
        
    async def _get_sink_mute_pipewire(self, node_id: int) -> bool:
        """Check if a PipeWire sink is muted using wpctl."""
        stdout, _, returncode = await self._run_command("wpctl", "get-volume", str(node_id))
        
        if returncode == 0:
            return "[MUTED]" in stdout
            
        return False
        
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
        
    async def _get_sinks_alsa(self) -> list[AudioSink]:
        """Get sinks using ALSA (amixer) as fallback."""
        sinks = []
        
        # Use aplay to list playback devices
        stdout, _, returncode = await self._run_command("aplay", "-l")
        
        if returncode != 0:
            return []
            
        # Parse aplay output
        # Format: "card 0: Headphones [bcm2835 Headphones], device 0: bcm2835 Headphones [bcm2835 Headphones]"
        card_id = 0
        for line in stdout.split("\n"):
            if line.startswith("card "):
                match = re.search(r"card (\d+): (\w+) \[([^\]]+)\]", line)
                if match:
                    card_num = int(match.group(1))
                    card_name = match.group(2)
                    card_desc = match.group(3)
                    
                    # Get volume using amixer
                    volume = 100.0
                    muted = False
                    vol_stdout, _, vol_rc = await self._run_command(
                        "amixer", "-c", str(card_num), "get", "PCM"
                    )
                    if vol_rc == 0:
                        vol_match = re.search(r"\[(\d+)%\]", vol_stdout)
                        if vol_match:
                            volume = float(vol_match.group(1))
                        muted = "[off]" in vol_stdout.lower()
                    
                    sinks.append(AudioSink(
                        id=card_num,
                        name=f"hw:{card_num}",
                        description=card_desc,
                        is_default=(card_num == 0),  # First card is usually default
                        volume=volume,
                        muted=muted,
                        state="running",
                    ))
                    card_id += 1
                    
        return sinks
        
    async def set_default_sink(self, sink_name: str) -> bool:
        """Set the default audio sink."""
        if self._backend == AudioBackend.PIPEWIRE and not shutil.which("pactl"):
            # Use wpctl for native PipeWire
            # First, find the node ID for this sink name
            sinks = await self.get_sinks()
            sink_id = None
            for sink in sinks:
                if sink.name == sink_name:
                    sink_id = sink.id
                    break
                    
            if sink_id is None:
                logger.error(f"Sink not found: {sink_name}")
                return False
                
            _, _, returncode = await self._run_command("wpctl", "set-default", str(sink_id))
        else:
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
        
        if self._backend == AudioBackend.PIPEWIRE and not shutil.which("pactl"):
            # Use wpctl for native PipeWire
            # Find sink ID
            sinks = await self.get_sinks()
            sink_id = None
            for sink in sinks:
                if sink.name == sink_name:
                    sink_id = sink.id
                    break
                    
            if sink_id is None:
                # Try using @DEFAULT_AUDIO_SINK@ as fallback
                sink_id = "@DEFAULT_AUDIO_SINK@"
            else:
                sink_id = str(sink_id)
                
            # wpctl uses decimal (0.0-1.0+) not percentage
            volume_decimal = volume / 100.0
            _, _, returncode = await self._run_command(
                "wpctl", "set-volume", sink_id, str(volume_decimal)
            )
        else:
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
        if self._backend == AudioBackend.PIPEWIRE and not shutil.which("pactl"):
            # Use wpctl for native PipeWire
            sinks = await self.get_sinks()
            sink_id = None
            for sink in sinks:
                if sink.name == sink_name:
                    sink_id = sink.id
                    break
                    
            if sink_id is None:
                sink_id = "@DEFAULT_AUDIO_SINK@"
            else:
                sink_id = str(sink_id)
                
            mute_str = "1" if mute else "0"
            _, _, returncode = await self._run_command(
                "wpctl", "set-mute", sink_id, mute_str
            )
        else:
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
        if self._backend == AudioBackend.PIPEWIRE and not shutil.which("pactl"):
            # Use wpctl for native PipeWire
            sinks = await self.get_sinks()
            sink_id = None
            for sink in sinks:
                if sink.name == sink_name:
                    sink_id = sink.id
                    break
                    
            if sink_id is None:
                sink_id = "@DEFAULT_AUDIO_SINK@"
            else:
                sink_id = str(sink_id)
                
            _, _, returncode = await self._run_command(
                "wpctl", "set-mute", sink_id, "toggle"
            )
        else:
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
