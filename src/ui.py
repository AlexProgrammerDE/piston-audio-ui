"""
NiceGUI Web Interface for Piston Audio.

Provides:
- Pairing confirmation dialogs
- Connected device display
- Audio output selection
- Volume control
- Audio settings
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Callable

from nicegui import app, ui

if TYPE_CHECKING:
    from .bluetooth_agent import BluetoothDevice, BluetoothManager, PairingRequest
    from .audio_manager import AudioManager, AudioSink

logger = logging.getLogger(__name__)


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
        with ui.dialog() as self.dialog, ui.card().classes("p-6"):
            ui.label("Bluetooth Pairing Request").classes("text-xl font-bold mb-4")
            
            with ui.column().classes("gap-2 mb-4"):
                ui.label(f"Device: {self.request.device_name}").classes("text-lg")
                ui.label(f"Address: {self.request.device_address}").classes("text-gray-500")
                
                if self.request.passkey:
                    ui.separator()
                    ui.label("Confirm this passkey matches your device:").classes("mt-2")
                    ui.label(self.request.passkey).classes(
                        "text-3xl font-mono font-bold text-primary tracking-widest my-4"
                    )
                    
            with ui.row().classes("gap-4 justify-end w-full"):
                ui.button("Reject", on_click=self._reject).props("flat color=negative")
                ui.button("Accept", on_click=self._accept).props("color=positive")
                
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
        
    def render(self) -> ui.card:
        """Render the device card."""
        with ui.card().classes("w-full p-4") as card:
            with ui.row().classes("items-center justify-between w-full"):
                with ui.row().classes("items-center gap-3"):
                    # Device icon based on type
                    icon = "smartphone" if "phone" in self.device.icon.lower() else "bluetooth"
                    if self.device.connected:
                        ui.icon(icon, color="positive").classes("text-2xl")
                    else:
                        ui.icon(icon, color="grey").classes("text-2xl")
                        
                    with ui.column().classes("gap-0"):
                        ui.label(self.device.name).classes("font-medium")
                        ui.label(self.device.address).classes("text-xs text-gray-500")
                        
                with ui.row().classes("gap-2"):
                    if self.device.connected:
                        ui.chip("Connected", color="positive").props("dense")
                        ui.button(
                            icon="link_off",
                            on_click=lambda: self.on_disconnect(self.device.path)
                        ).props("flat dense").tooltip("Disconnect")
                    else:
                        ui.button(
                            icon="link",
                            on_click=lambda: self.on_connect(self.device.path)
                        ).props("flat dense").tooltip("Connect")
                        
                    ui.button(
                        icon="delete",
                        on_click=lambda: self.on_remove(self.device.path)
                    ).props("flat dense color=negative").tooltip("Remove device")
                    
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
            
            # Set current default
            for sink in self.sinks:
                if sink.is_default:
                    self.select.value = sink.name
                    break
                    
    async def _on_change(self, e) -> None:
        """Handle output selection change."""
        if e.value:
            success = await self.audio_manager.set_default_sink(e.value)
            if success:
                ui.notify(f"Audio output changed", type="positive")
            else:
                ui.notify("Failed to change audio output", type="negative")
                
    def render(self) -> ui.column:
        """Render the audio output selector."""
        with ui.column().classes("w-full gap-2") as col:
            ui.label("Audio Output").classes("font-medium")
            
            options = {s.name: s.display_name for s in self.sinks}
            default = next((s.name for s in self.sinks if s.is_default), None)
            
            self.select = ui.select(
                options=options,
                value=default,
                on_change=self._on_change,
            ).classes("w-full")
            
            ui.button(
                "Refresh",
                icon="refresh",
                on_click=self.refresh,
            ).props("flat dense")
            
        return col


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
            
    def render(self) -> ui.column:
        """Render the volume control."""
        initial_volume = int(self.current_sink.volume) if self.current_sink else 50
        
        with ui.column().classes("w-full gap-2") as col:
            ui.label("Volume").classes("font-medium")
            
            with ui.row().classes("w-full items-center gap-4"):
                self.mute_btn = ui.button(
                    icon="volume_up",
                    on_click=self._on_mute_toggle,
                ).props("flat dense")
                
                self.slider = ui.slider(
                    min=0,
                    max=150,
                    value=initial_volume,
                    on_change=self._on_volume_change,
                ).classes("flex-grow")
                
                ui.label().bind_text_from(self.slider, "value", lambda v: f"{int(v)}%")
                
        return col


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
        self._pairing_dialogs: dict[str, PairingDialog] = {}
        
    def on_pairing_request(self, request: "PairingRequest") -> None:
        """Handle incoming pairing request."""
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
            # Fallback: just show dialog in current context
            dialog.show()
                
    async def _accept_pairing(self, device_path: str) -> None:
        """Accept a pairing request."""
        if self.bt_manager.agent:
            self.bt_manager.agent.accept_pairing(device_path)
            # Trust the device for auto-reconnect
            await self.bt_manager.trust_device(device_path)
            ui.notify("Device paired and trusted", type="positive")
            await self._refresh_devices()
            
    async def _reject_pairing(self, device_path: str) -> None:
        """Reject a pairing request."""
        if self.bt_manager.agent:
            self.bt_manager.agent.reject_pairing(device_path)
            ui.notify("Pairing rejected", type="warning")
            
    async def _connect_device(self, device_path: str) -> None:
        """Connect to a device."""
        try:
            await self.bt_manager.connect_device(device_path)
            ui.notify("Device connected", type="positive")
            await self._refresh_devices()
        except Exception as e:
            ui.notify(f"Connection failed: {e}", type="negative")
            
    async def _disconnect_device(self, device_path: str) -> None:
        """Disconnect a device."""
        try:
            await self.bt_manager.disconnect_device(device_path)
            ui.notify("Device disconnected", type="info")
            await self._refresh_devices()
        except Exception as e:
            ui.notify(f"Disconnect failed: {e}", type="negative")
            
    async def _remove_device(self, device_path: str) -> None:
        """Remove/unpair a device."""
        try:
            await self.bt_manager.remove_device(device_path)
            ui.notify("Device removed", type="info")
            await self._refresh_devices()
        except Exception as e:
            ui.notify(f"Remove failed: {e}", type="negative")
            
    async def _refresh_devices(self) -> None:
        """Refresh the devices list."""
        if not self.devices_container:
            return
            
        self.devices_container.clear()
        
        devices = await self.bt_manager.get_devices()
        
        with self.devices_container:
            if not devices:
                ui.label("No paired devices").classes("text-gray-500 italic")
            else:
                for device in devices:
                    DeviceCard(
                        device=device,
                        on_connect=self._connect_device,
                        on_disconnect=self._disconnect_device,
                        on_remove=self._remove_device,
                    ).render()
                    
    async def _toggle_discoverable(self, e) -> None:
        """Toggle discoverable mode."""
        await self.bt_manager.set_discoverable(e.value)
        await self.bt_manager.set_pairable(e.value)
        state = "enabled" if e.value else "disabled"
        ui.notify(f"Discoverable mode {state}", type="info")
        
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
        
        with ui.header().classes("items-center justify-between px-4"):
            ui.label("Piston Audio").classes("text-xl font-bold")
            with ui.row().classes("gap-2"):
                ui.button(icon="settings", on_click=lambda: ui.navigate.to("/settings")).props("flat")
                
        with ui.column().classes("w-full max-w-2xl mx-auto p-4 gap-6"):
            # Discoverable toggle
            with ui.card().classes("w-full p-4"):
                with ui.row().classes("items-center justify-between w-full"):
                    with ui.column().classes("gap-0"):
                        ui.label("Discoverable").classes("font-medium")
                        ui.label("Allow devices to find and pair").classes("text-xs text-gray-500")
                    ui.switch(on_change=self._toggle_discoverable)
                    
            # Connected device section
            with ui.card().classes("w-full p-4"):
                with ui.row().classes("items-center justify-between w-full mb-4"):
                    ui.label("Devices").classes("text-lg font-medium")
                    ui.button(
                        icon="refresh",
                        on_click=self._refresh_devices,
                    ).props("flat dense")
                    
                self.devices_container = ui.column().classes("w-full gap-2")
                await self._refresh_devices()
                
            # Audio output section
            with ui.card().classes("w-full p-4"):
                ui.label("Audio").classes("text-lg font-medium mb-4")
                
                self.output_selector = AudioOutputSelector(self.audio_manager)
                await self.output_selector.refresh()
                self.output_selector.render()
                
                ui.separator().classes("my-4")
                
                self.volume_control = VolumeControl(self.audio_manager)
                await self.volume_control.refresh()
                self.volume_control.render()
                
        # Auto-refresh timer
        ui.timer(5.0, self._refresh_devices)
        ui.timer(2.0, self._refresh_audio)
        
    async def _render_settings_page(self) -> None:
        """Render the settings page."""
        ui.dark_mode().auto()
        
        with ui.header().classes("items-center px-4"):
            ui.button(icon="arrow_back", on_click=lambda: ui.navigate.to("/")).props("flat")
            ui.label("Settings").classes("text-xl font-bold ml-2")
            
        with ui.column().classes("w-full max-w-2xl mx-auto p-4 gap-6"):
            # Adapter settings
            with ui.card().classes("w-full p-4"):
                ui.label("Bluetooth Adapter").classes("text-lg font-medium mb-4")
                
                adapter_info = await self.bt_manager.get_adapter_info()
                
                with ui.column().classes("gap-4 w-full"):
                    # Adapter name
                    name_input = ui.input(
                        "Device Name",
                        value=adapter_info.get("alias", "Piston Audio"),
                    ).classes("w-full")
                    
                    async def save_name():
                        await self.bt_manager.set_adapter_alias(name_input.value)
                        ui.notify("Name saved", type="positive")
                        
                    ui.button("Save Name", on_click=save_name).props("flat")
                    
                    ui.separator()
                    
                    # Adapter info
                    with ui.column().classes("gap-1"):
                        ui.label(f"Address: {adapter_info.get('address', 'Unknown')}").classes("text-sm")
                        ui.label(f"Powered: {'Yes' if adapter_info.get('powered') else 'No'}").classes("text-sm")
                        
            # Audio settings
            with ui.card().classes("w-full p-4"):
                ui.label("Audio Settings").classes("text-lg font-medium mb-4")
                
                with ui.column().classes("gap-4 w-full"):
                    # Backend info
                    backend = self.audio_manager.backend.value
                    ui.label(f"Audio Backend: {backend.title()}").classes("text-sm")
                    
            # About section
            with ui.card().classes("w-full p-4"):
                ui.label("About").classes("text-lg font-medium mb-4")
                
                with ui.column().classes("gap-2"):
                    ui.label("Piston Audio v1.0.0").classes("font-medium")
                    ui.label("Bluetooth audio receiver for Raspberry Pi").classes("text-sm text-gray-500")
                    ui.link(
                        "GitHub",
                        "https://github.com/AlexProgrammerDE/piston-audio-ui",
                        new_tab=True,
                    ).classes("text-sm")
