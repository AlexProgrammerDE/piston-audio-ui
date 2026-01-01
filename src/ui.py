"""
NiceGUI Web Interface for Piston Audio.

Provides:
- Pairing confirmation dialogs with passkey display
- Connected device display with status
- Audio output selection
- Volume control
- Audio settings
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable, Optional

from nicegui import app, ui

if TYPE_CHECKING:
    from .bluetooth_agent import BluetoothDevice, BluetoothManager, PairingRequest, DeviceState
    from .audio_manager import AudioManager, AudioSink

logger = logging.getLogger(__name__)


class PairingCodeDisplay:
    """Persistent display for pairing codes during active pairing."""
    
    def __init__(self):
        self.container: ui.card | None = None
        self.code_label: ui.label | None = None
        self.device_label: ui.label | None = None
        self.status_label: ui.label | None = None
        self._visible = False
        
    def show(self, device_name: str, passkey: str) -> None:
        """Show the pairing code display."""
        if self.container:
            self.container.set_visibility(True)
            if self.device_label:
                self.device_label.text = f"Pairing with: {device_name}"
            if self.code_label:
                self.code_label.text = passkey
            if self.status_label:
                self.status_label.text = "Confirm this code matches your device"
            self._visible = True
            
    def hide(self) -> None:
        """Hide the pairing code display."""
        if self.container:
            self.container.set_visibility(False)
        self._visible = False
        
    def update_status(self, status: str) -> None:
        """Update the status text."""
        if self.status_label:
            self.status_label.text = status
            
    def render(self) -> ui.card:
        """Render the pairing code display component."""
        with ui.card().classes("w-full") as self.container:
            with ui.row().classes("w-full items-center"):
                ui.icon("bluetooth_searching", color="primary", size="lg")
                with ui.column().classes("flex-grow"):
                    self.device_label = ui.label("Pairing with: Device")
                    self.status_label = ui.label("Waiting for confirmation...").props("caption")
                    
            ui.separator()
            
            with ui.row().classes("w-full justify-center"):
                self.code_label = ui.label("000000").style(
                    "font-size: 3rem; font-family: monospace; font-weight: bold; "
                    "letter-spacing: 0.5em; color: var(--q-primary)"
                )
                
        self.container.set_visibility(False)
        return self.container


class PairingDialog:
    """Dialog for Bluetooth pairing confirmation."""
    
    def __init__(
        self,
        request: "PairingRequest",
        on_accept: Callable[[str], Any],
        on_reject: Callable[[str], Any],
    ):
        self.request = request
        self.on_accept = on_accept
        self.on_reject = on_reject
        self.dialog: ui.dialog | None = None
        
    def show(self) -> None:
        """Display the pairing dialog."""
        with ui.dialog() as self.dialog, ui.card():
            with ui.row().classes("items-center"):
                ui.icon("bluetooth", color="primary", size="md")
                ui.label("Bluetooth Pairing Request").style("font-size: 1.25rem; font-weight: bold")
            
            ui.separator()
            
            ui.label(f"Device: {self.request.device_name}")
            ui.label(f"Address: {self.request.device_address}").props("caption")
            
            if self.request.passkey:
                ui.separator()
                ui.label("Confirm this passkey matches your device:")
                with ui.row().classes("w-full justify-center"):
                    ui.label(self.request.passkey).style(
                        "font-size: 2.5rem; font-family: monospace; font-weight: bold; "
                        "letter-spacing: 0.4em; color: var(--q-primary)"
                    )
            else:
                ui.label("Allow this device to connect?").props("caption")
                    
            ui.separator()
            
            with ui.row().classes("w-full justify-end"):
                ui.button("Reject", on_click=self._reject, color="negative").props("flat")
                ui.button("Accept", on_click=self._accept, color="positive")
                
        self.dialog.open()
        
    async def _accept(self) -> None:
        """Handle accept button."""
        if self.dialog:
            self.dialog.close()
        await self.on_accept(self.request.device_path)
        
    async def _reject(self) -> None:
        """Handle reject button."""
        if self.dialog:
            self.dialog.close()
        await self.on_reject(self.request.device_path)


class DeviceCard:
    """Card displaying a connected or paired device."""
    
    def __init__(
        self,
        device: "BluetoothDevice",
        on_connect: Callable[[str], Any],
        on_disconnect: Callable[[str], Any],
        on_remove: Callable[[str], Any],
    ):
        self.device = device
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect
        self.on_remove = on_remove
        
    def _get_icon(self) -> str:
        """Get appropriate icon for device type."""
        icon_lower = self.device.icon.lower()
        if "phone" in icon_lower:
            return "smartphone"
        elif "computer" in icon_lower:
            return "computer"
        elif "audio" in icon_lower or "headset" in icon_lower or "headphone" in icon_lower:
            return "headphones"
        elif "input" in icon_lower or "keyboard" in icon_lower:
            return "keyboard"
        elif "mouse" in icon_lower:
            return "mouse"
        else:
            return "bluetooth"
            
    def _get_state_badge(self) -> tuple[str, str, str]:
        """Get badge text, color and icon based on device state."""
        from .bluetooth_agent import DeviceState
        
        state = self.device.state
        if state == DeviceState.CONNECTED:
            return "Connected", "positive", "check_circle"
        elif state == DeviceState.CONNECTING:
            return "Connecting...", "warning", "sync"
        elif state == DeviceState.DISCONNECTING:
            return "Disconnecting...", "warning", "sync"
        elif state == DeviceState.PAIRING:
            return "Pairing...", "info", "bluetooth_searching"
        elif state == DeviceState.ERROR:
            return "Error", "negative", "error"
        else:
            return "", "", ""
        
    def render(self) -> ui.card:
        """Render the device card."""
        with ui.card() as card:
            with ui.row().classes("w-full items-center justify-between"):
                with ui.row().classes("items-center"):
                    icon = self._get_icon()
                    if self.device.connected:
                        ui.icon(icon, color="positive", size="md")
                    else:
                        ui.icon(icon, color="grey", size="md")
                        
                    with ui.column():
                        ui.label(self.device.name)
                        with ui.row().classes("items-center"):
                            ui.label(self.device.address).props("caption")
                            if self.device.battery_percentage is not None:
                                ui.label(f" | {self.device.battery_percentage}%").props("caption")
                                if self.device.battery_percentage <= 20:
                                    ui.icon("battery_alert", color="negative", size="xs")
                                elif self.device.battery_percentage <= 50:
                                    ui.icon("battery_3_bar", color="warning", size="xs")
                                else:
                                    ui.icon("battery_full", color="positive", size="xs")
                        
                        # Show error message if present
                        if self.device.error_message:
                            ui.label(self.device.error_message).props("caption").style("color: var(--q-negative)")
                        
                with ui.row().classes("items-center"):
                    # State badge
                    badge_text, badge_color, badge_icon = self._get_state_badge()
                    if badge_text:
                        with ui.row().classes("items-center"):
                            if badge_icon:
                                ui.icon(badge_icon, color=badge_color, size="xs")
                            ui.badge(badge_text, color=badge_color)
                    
                    # Action buttons
                    if self.device.connected:
                        ui.button(
                            icon="link_off",
                            on_click=lambda: self.on_disconnect(self.device.path)
                        ).props("flat round").tooltip("Disconnect")
                    else:
                        ui.button(
                            icon="link",
                            on_click=lambda: self.on_connect(self.device.path)
                        ).props("flat round").tooltip("Connect")
                        
                    ui.button(
                        icon="delete",
                        on_click=lambda: self.on_remove(self.device.path),
                        color="negative"
                    ).props("flat round").tooltip("Remove device")
                    
        return card


class AudioOutputSelector:
    """Component for selecting audio output."""
    
    def __init__(self, audio_manager: "AudioManager"):
        self.audio_manager = audio_manager
        self.sinks: list["AudioSink"] = []
        self.select: ui.select | None = None
        
    async def refresh(self) -> None:
        """Refresh the list of audio sinks."""
        self.sinks = await self.audio_manager.get_sinks()
        if self.select:
            options = {s.name: s.display_name for s in self.sinks}
            self.select.options = options
            self.select.update()
            
            for sink in self.sinks:
                if sink.is_default:
                    self.select.value = sink.name
                    break
                    
    async def _on_change(self, e) -> None:
        """Handle output selection change."""
        if e.value:
            success = await self.audio_manager.set_default_sink(e.value)
            if success:
                ui.notify("Audio output changed", type="positive")
            else:
                ui.notify("Failed to change audio output", type="negative")
                
    def render(self) -> None:
        """Render the audio output selector."""
        ui.label("Audio Output")
        
        options = {s.name: s.display_name for s in self.sinks}
        default = next((s.name for s in self.sinks if s.is_default), None)
        
        self.select = ui.select(
            options=options,
            value=default,
            on_change=self._on_change,
        ).classes("w-full")
        
        ui.button("Refresh", icon="refresh", on_click=self.refresh).props("flat")


class VolumeControl:
    """Component for volume control."""
    
    def __init__(self, audio_manager: "AudioManager"):
        self.audio_manager = audio_manager
        self.slider: ui.slider | None = None
        self.mute_btn: ui.button | None = None
        self.current_sink: "AudioSink | None" = None
        
    async def refresh(self) -> None:
        """Refresh volume state."""
        self.current_sink = await self.audio_manager.get_default_sink()
        if self.current_sink and self.slider:
            self.slider.value = int(self.current_sink.volume)
            
    async def _on_volume_change(self, e) -> None:
        """Handle volume slider change."""
        if self.current_sink:
            await self.audio_manager.set_volume(self.current_sink.name, int(e.value))
            
    async def _on_mute_toggle(self) -> None:
        """Handle mute button click."""
        if self.current_sink:
            await self.audio_manager.toggle_mute(self.current_sink.name)
            await self.refresh()
            
    def render(self) -> None:
        """Render the volume control."""
        initial_volume = int(self.current_sink.volume) if self.current_sink else 50
        
        ui.label("Volume")
        
        with ui.row().classes("w-full items-center"):
            self.mute_btn = ui.button(
                icon="volume_up",
                on_click=self._on_mute_toggle,
            ).props("flat round")
            
            self.slider = ui.slider(
                min=0,
                max=150,
                value=initial_volume,
                on_change=self._on_volume_change,
            ).classes("flex-grow")
            
            ui.label().bind_text_from(self.slider, "value", lambda v: f"{int(v)}%")


class PistonAudioUI:
    """Main UI class for Piston Audio."""
    
    def __init__(
        self,
        bluetooth_manager: "BluetoothManager",
        audio_manager: "AudioManager",
    ):
        self.bt_manager = bluetooth_manager
        self.audio_manager = audio_manager
        self.devices_container: ui.column | None = None
        self.output_selector: AudioOutputSelector | None = None
        self.volume_control: VolumeControl | None = None
        self.pairing_display: PairingCodeDisplay | None = None
        self._pairing_dialogs: dict[str, PairingDialog] = {}
        self._device_states: dict[str, "DeviceState"] = {}
        
    def on_pairing_request(self, request: "PairingRequest") -> None:
        """Handle incoming pairing request."""
        logger.info(f"Pairing request from {request.device_name} ({request.device_address})")
        
        # Show pairing code in the persistent display
        if request.passkey and self.pairing_display:
            self.pairing_display.show(request.device_name, request.passkey)
        
        dialog = PairingDialog(
            request=request,
            on_accept=self._accept_pairing,
            on_reject=self._reject_pairing,
        )
        self._pairing_dialogs[request.device_path] = dialog
        
        # Show dialog in all connected clients
        try:
            clients = getattr(app, 'clients', {})
            for client in clients.values():
                with client:
                    dialog.show()
        except Exception:
            dialog.show()
                
    async def _accept_pairing(self, device_path: str) -> None:
        """Accept a pairing request."""
        if self.pairing_display:
            self.pairing_display.update_status("Pairing accepted, connecting...")
            
        try:
            if self.bt_manager.agent:
                self.bt_manager.agent.accept_pairing(device_path)
                await self.bt_manager.trust_device(device_path)
                ui.notify("Device paired and trusted", type="positive")
        except Exception as e:
            ui.notify(f"Pairing failed: {e}", type="negative")
        finally:
            if self.pairing_display:
                self.pairing_display.hide()
            await self._refresh_devices()
            
    async def _reject_pairing(self, device_path: str) -> None:
        """Reject a pairing request."""
        if self.pairing_display:
            self.pairing_display.hide()
            
        if self.bt_manager.agent:
            self.bt_manager.agent.reject_pairing(device_path)
            ui.notify("Pairing rejected", type="warning")
            
    async def _connect_device(self, device_path: str) -> None:
        """Connect to a device."""
        from .bluetooth_agent import DeviceState, ConnectionError as BTConnectionError
        
        # Update state to connecting
        self._device_states[device_path] = DeviceState.CONNECTING
        await self._refresh_devices()
        
        try:
            await self.bt_manager.connect_device(device_path)
            self._device_states[device_path] = DeviceState.CONNECTED
            ui.notify("Device connected", type="positive")
        except BTConnectionError as e:
            self._device_states[device_path] = DeviceState.ERROR
            ui.notify(str(e), type="negative")
            logger.error(f"Connection error: {e}")
        except Exception as e:
            self._device_states[device_path] = DeviceState.ERROR
            error_msg = self._parse_dbus_error(str(e))
            ui.notify(f"Connection failed: {error_msg}", type="negative")
            logger.error(f"Connection error: {e}")
        finally:
            await self._refresh_devices()
            # Clear error state after a delay
            if self._device_states.get(device_path) == DeviceState.ERROR:
                await self._clear_error_state(device_path)
            
    async def _disconnect_device(self, device_path: str) -> None:
        """Disconnect a device."""
        from .bluetooth_agent import DeviceState, ConnectionError as BTConnectionError
        
        # Update state to disconnecting
        self._device_states[device_path] = DeviceState.DISCONNECTING
        await self._refresh_devices()
        
        try:
            await self.bt_manager.disconnect_device(device_path)
            self._device_states[device_path] = DeviceState.DISCONNECTED
            ui.notify("Device disconnected", type="info")
        except BTConnectionError as e:
            ui.notify(str(e), type="negative")
        except Exception as e:
            error_msg = self._parse_dbus_error(str(e))
            ui.notify(f"Disconnect failed: {error_msg}", type="negative")
        finally:
            await self._refresh_devices()
            
    async def _remove_device(self, device_path: str) -> None:
        """Remove/unpair a device."""
        from .bluetooth_agent import AdapterError
        
        try:
            await self.bt_manager.remove_device(device_path)
            # Remove from state tracking
            self._device_states.pop(device_path, None)
            ui.notify("Device removed", type="info")
        except AdapterError as e:
            ui.notify(str(e), type="negative")
        except Exception as e:
            error_msg = self._parse_dbus_error(str(e))
            ui.notify(f"Remove failed: {error_msg}", type="negative")
        finally:
            await self._refresh_devices()
            
    async def _clear_error_state(self, device_path: str, delay: float = 5.0) -> None:
        """Clear error state after a delay."""
        import asyncio
        await asyncio.sleep(delay)
        if self._device_states.get(device_path) == "error":
            self._device_states.pop(device_path, None)
            await self._refresh_devices()
    
    def _parse_dbus_error(self, error: str) -> str:
        """Parse D-Bus error messages into user-friendly text."""
        if "Host is down" in error:
            return "Device is not in range or powered off"
        elif "Connection refused" in error:
            return "Device refused the connection"
        elif "le-connection-abort" in error:
            return "Connection was aborted"
        elif "InProgress" in error:
            return "Operation already in progress"
        elif "NotReady" in error:
            return "Bluetooth adapter is not ready"
        elif "AuthenticationFailed" in error:
            return "Authentication failed - try removing and re-pairing"
        elif "AuthenticationCanceled" in error:
            return "Authentication was cancelled"
        elif "AuthenticationRejected" in error:
            return "Authentication was rejected by the device"
        elif "AuthenticationTimeout" in error:
            return "Authentication timed out"
        elif "ConnectionAttemptFailed" in error:
            return "Connection attempt failed"
        else:
            # Extract the actual error message if possible
            if ":" in error:
                parts = error.split(":")
                return parts[-1].strip()
            return error
            
    async def _refresh_devices(self) -> None:
        """Refresh the devices list."""
        from .bluetooth_agent import DeviceState, AdapterError
        
        if not self.devices_container:
            return
            
        self.devices_container.clear()
        
        try:
            devices = await self.bt_manager.get_devices()
            
            # Apply UI state overrides
            for device in devices:
                if device.path in self._device_states:
                    device.state = self._device_states[device.path]
            
            with self.devices_container:
                if not devices:
                    with ui.row().classes("w-full items-center justify-center"):
                        ui.icon("bluetooth_disabled", color="grey", size="md")
                        ui.label("No paired devices").props("caption")
                else:
                    for device in devices:
                        DeviceCard(
                            device=device,
                            on_connect=self._connect_device,
                            on_disconnect=self._disconnect_device,
                            on_remove=self._remove_device,
                        ).render()
        except AdapterError as e:
            with self.devices_container:
                with ui.row().classes("w-full items-center"):
                    ui.icon("error", color="negative", size="md")
                    ui.label(f"Error: {e}").style("color: var(--q-negative)")
        except Exception as e:
            logger.error(f"Failed to refresh devices: {e}")
            with self.devices_container:
                with ui.row().classes("w-full items-center"):
                    ui.icon("error", color="negative", size="md")
                    ui.label("Failed to load devices").style("color: var(--q-negative)")
                    
    async def _toggle_discoverable(self, e) -> None:
        """Toggle discoverable mode."""
        try:
            await self.bt_manager.set_discoverable(e.value)
            await self.bt_manager.set_pairable(e.value)
            state = "enabled" if e.value else "disabled"
            ui.notify(f"Discoverable mode {state}", type="info")
        except Exception as ex:
            ui.notify(f"Failed to change discoverable mode: {ex}", type="negative")
            e.sender.value = not e.value  # Revert the switch
        
    async def _refresh_audio(self) -> None:
        """Refresh audio controls."""
        if self.output_selector:
            await self.output_selector.refresh()
        if self.volume_control:
            await self.volume_control.refresh()
            
    def setup_routes(self) -> None:
        """Setup UI routes."""
        
        @ui.page("/")
        async def index():
            await self._render_main_page()
            
        @ui.page("/settings")
        async def settings():
            await self._render_settings_page()
            
    async def _render_main_page(self) -> None:
        """Render the main page."""
        ui.dark_mode().auto()
        
        with ui.header():
            ui.label("Piston Audio").style("font-size: 1.25rem; font-weight: bold")
            ui.space()
            ui.button(icon="settings", on_click=lambda: ui.navigate.to("/settings")).props("flat round")
                
        with ui.column().classes("w-full max-w-2xl mx-auto p-4"):
            # Pairing code display (hidden by default)
            self.pairing_display = PairingCodeDisplay()
            self.pairing_display.render()
            
            # Discoverable toggle
            with ui.card().classes("w-full"):
                with ui.row().classes("w-full items-center justify-between"):
                    with ui.column():
                        ui.label("Discoverable")
                        ui.label("Allow devices to find and pair").props("caption")
                    ui.switch(on_change=self._toggle_discoverable)
                    
            # Devices section
            with ui.card().classes("w-full"):
                with ui.row().classes("w-full items-center justify-between"):
                    ui.label("Devices").style("font-size: 1.125rem")
                    ui.button(icon="refresh", on_click=self._refresh_devices).props("flat round")
                    
                self.devices_container = ui.column().classes("w-full")
                await self._refresh_devices()
                
            # Audio section
            with ui.card().classes("w-full"):
                ui.label("Audio").style("font-size: 1.125rem")
                
                self.output_selector = AudioOutputSelector(self.audio_manager)
                await self.output_selector.refresh()
                self.output_selector.render()
                
                ui.separator()
                
                self.volume_control = VolumeControl(self.audio_manager)
                await self.volume_control.refresh()
                self.volume_control.render()
                
        ui.timer(5.0, self._refresh_devices)
        ui.timer(2.0, self._refresh_audio)
        
    async def _render_settings_page(self) -> None:
        """Render the settings page."""
        ui.dark_mode().auto()
        
        with ui.header():
            ui.button(icon="arrow_back", on_click=lambda: ui.navigate.to("/")).props("flat round")
            ui.label("Settings").style("font-size: 1.25rem; font-weight: bold")
            
        with ui.column().classes("w-full max-w-2xl mx-auto p-4"):
            # Adapter settings
            with ui.card().classes("w-full"):
                ui.label("Bluetooth Adapter").style("font-size: 1.125rem")
                
                try:
                    adapter_info = await self.bt_manager.get_adapter_info()
                    
                    name_input = ui.input(
                        "Device Name",
                        value=adapter_info.get("alias", "Piston Audio"),
                    ).classes("w-full")
                    
                    async def save_name():
                        try:
                            await self.bt_manager.set_adapter_alias(name_input.value)
                            ui.notify("Name saved", type="positive")
                        except Exception as e:
                            ui.notify(f"Failed to save name: {e}", type="negative")
                        
                    ui.button("Save Name", on_click=save_name).props("flat")
                    
                    ui.separator()
                    
                    ui.label(f"Address: {adapter_info.get('address', 'Unknown')}").props("caption")
                    ui.label(f"Powered: {'Yes' if adapter_info.get('powered') else 'No'}").props("caption")
                    ui.label(f"Discoverable: {'Yes' if adapter_info.get('discoverable') else 'No'}").props("caption")
                    ui.label(f"Pairable: {'Yes' if adapter_info.get('pairable') else 'No'}").props("caption")
                except Exception as e:
                    with ui.row().classes("items-center"):
                        ui.icon("error", color="negative", size="sm")
                        ui.label(f"Failed to load adapter info: {e}").props("caption")
                        
            # Audio settings
            with ui.card().classes("w-full"):
                ui.label("Audio Settings").style("font-size: 1.125rem")
                backend = self.audio_manager.backend.value
                ui.label(f"Audio Backend: {backend.title()}").props("caption")
                    
            # About section
            with ui.card().classes("w-full"):
                ui.label("About").style("font-size: 1.125rem")
                ui.label("Piston Audio v1.0.0")
                ui.label("Bluetooth audio receiver for Raspberry Pi").props("caption")
                ui.link(
                    "GitHub",
                    "https://github.com/AlexProgrammerDE/piston-audio-ui",
                    new_tab=True,
                )
