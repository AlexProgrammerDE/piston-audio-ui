"""
Bluetooth Agent for handling pairing requests via D-Bus.

This module implements a BlueZ agent that can:
- Accept/reject pairing requests through a web UI
- Auto-trust devices for A2DP audio streaming
- Manage device connections
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

from dbus_fast import BusType, Variant
from dbus_fast.aio import MessageBus
from dbus_fast.service import ServiceInterface, method, PropertyAccess, dbus_property

logger = logging.getLogger(__name__)

# BlueZ D-Bus constants
BLUEZ_SERVICE = "org.bluez"
AGENT_INTERFACE = "org.bluez.Agent1"
AGENT_MANAGER_INTERFACE = "org.bluez.AgentManager1"
ADAPTER_INTERFACE = "org.bluez.Adapter1"
DEVICE_INTERFACE = "org.bluez.Device1"
PROPERTIES_INTERFACE = "org.freedesktop.DBus.Properties"
OBJECT_MANAGER_INTERFACE = "org.freedesktop.DBus.ObjectManager"


class PairingStatus(Enum):
    """Status of a pairing request."""
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    TIMEOUT = "timeout"


@dataclass
class PairingRequest:
    """Represents a pending pairing request."""
    device_path: str
    device_name: str
    device_address: str
    passkey: str | None = None
    status: PairingStatus = PairingStatus.PENDING
    future: asyncio.Future | None = None


@dataclass
class BluetoothDevice:
    """Represents a Bluetooth device."""
    path: str
    address: str
    name: str
    paired: bool = False
    trusted: bool = False
    connected: bool = False
    icon: str = "audio-card"


class BluetoothAgent(ServiceInterface):
    """
    D-Bus Bluetooth Agent for handling pairing requests.
    
    This agent receives pairing requests from BlueZ and forwards them
    to a callback for UI confirmation.
    """
    
    def __init__(
        self,
        on_pairing_request: Callable[[PairingRequest], None] | None = None,
        pairing_timeout: int = 60,
    ):
        super().__init__(AGENT_INTERFACE)
        self._on_pairing_request = on_pairing_request
        self._pairing_timeout = pairing_timeout
        self._pending_requests: dict[str, PairingRequest] = {}
        self._bus: MessageBus | None = None
        
    @property
    def pending_requests(self) -> dict[str, PairingRequest]:
        """Get pending pairing requests."""
        return self._pending_requests
    
    def set_bus(self, bus: MessageBus) -> None:
        """Set the D-Bus connection."""
        self._bus = bus
        
    async def _get_device_info(self, device_path: str) -> tuple[str, str]:
        """Get device name and address from D-Bus path."""
        if not self._bus:
            return "Unknown", "00:00:00:00:00:00"
            
        try:
            introspection = await self._bus.introspect(BLUEZ_SERVICE, device_path)
            proxy = self._bus.get_proxy_object(BLUEZ_SERVICE, device_path, introspection)
            props = proxy.get_interface(PROPERTIES_INTERFACE)
            
            name_var = await props.call_get(DEVICE_INTERFACE, "Name")
            address_var = await props.call_get(DEVICE_INTERFACE, "Address")
            
            name = name_var.value if name_var else "Unknown"
            address = address_var.value if address_var else "00:00:00:00:00:00"
            
            return name, address
        except Exception as e:
            logger.warning(f"Failed to get device info: {e}")
            # Extract address from path as fallback
            address = device_path.split("/")[-1].replace("dev_", "").replace("_", ":")
            return "Unknown Device", address
    
    async def _wait_for_response(self, request: PairingRequest) -> bool:
        """Wait for user response to pairing request."""
        request.future = asyncio.get_event_loop().create_future()
        
        try:
            await asyncio.wait_for(request.future, timeout=self._pairing_timeout)
            return request.status == PairingStatus.ACCEPTED
        except asyncio.TimeoutError:
            request.status = PairingStatus.TIMEOUT
            return False
        finally:
            if request.device_path in self._pending_requests:
                del self._pending_requests[request.device_path]

    @method()
    def Release(self) -> None:
        """Called when the agent is unregistered."""
        logger.info("Bluetooth agent released")
        
    @method()
    async def RequestPinCode(self, device: "o") -> "s":
        """Request PIN code for pairing."""
        name, address = await self._get_device_info(device)
        logger.info(f"PIN code requested for {name} ({address})")
        return "0000"
        
    @method()
    async def DisplayPinCode(self, device: "o", pincode: "s") -> None:
        """Display PIN code for user."""
        name, address = await self._get_device_info(device)
        logger.info(f"Display PIN {pincode} for {name} ({address})")
        
        request = PairingRequest(
            device_path=device,
            device_name=name,
            device_address=address,
            passkey=pincode,
        )
        self._pending_requests[device] = request
        
        if self._on_pairing_request:
            self._on_pairing_request(request)
            
    @method()
    async def RequestPasskey(self, device: "o") -> "u":
        """Request passkey for pairing."""
        name, address = await self._get_device_info(device)
        logger.info(f"Passkey requested for {name} ({address})")
        return 0
        
    @method()
    async def DisplayPasskey(self, device: "o", passkey: "u", entered: "q") -> None:
        """Display passkey for user."""
        name, address = await self._get_device_info(device)
        passkey_str = f"{passkey:06d}"
        logger.info(f"Display passkey {passkey_str} for {name} ({address})")
        
        request = PairingRequest(
            device_path=device,
            device_name=name,
            device_address=address,
            passkey=passkey_str,
        )
        self._pending_requests[device] = request
        
        if self._on_pairing_request:
            self._on_pairing_request(request)
            
    @method()
    async def RequestConfirmation(self, device: "o", passkey: "u") -> None:
        """Request confirmation for pairing."""
        name, address = await self._get_device_info(device)
        passkey_str = f"{passkey:06d}"
        logger.info(f"Confirmation requested for {name} ({address}) with passkey {passkey_str}")
        
        request = PairingRequest(
            device_path=device,
            device_name=name,
            device_address=address,
            passkey=passkey_str,
        )
        self._pending_requests[device] = request
        
        if self._on_pairing_request:
            self._on_pairing_request(request)
            
        # Wait for user confirmation
        accepted = await self._wait_for_response(request)
        
        if not accepted:
            from dbus_fast import DBusError
            raise DBusError("org.bluez.Error.Rejected", "Pairing rejected by user")
            
    @method()
    async def RequestAuthorization(self, device: "o") -> None:
        """Request authorization for incoming connection."""
        name, address = await self._get_device_info(device)
        logger.info(f"Authorization requested for {name} ({address})")
        
        request = PairingRequest(
            device_path=device,
            device_name=name,
            device_address=address,
        )
        self._pending_requests[device] = request
        
        if self._on_pairing_request:
            self._on_pairing_request(request)
            
        accepted = await self._wait_for_response(request)
        
        if not accepted:
            from dbus_fast import DBusError
            raise DBusError("org.bluez.Error.Rejected", "Authorization rejected by user")
            
    @method()
    async def AuthorizeService(self, device: "o", uuid: "s") -> None:
        """Authorize a Bluetooth service."""
        name, address = await self._get_device_info(device)
        logger.info(f"Service {uuid} authorization for {name} ({address})")
        # Auto-authorize A2DP and AVRCP services
        a2dp_uuids = [
            "0000110a-0000-1000-8000-00805f9b34fb",  # A2DP Source
            "0000110b-0000-1000-8000-00805f9b34fb",  # A2DP Sink
            "0000110e-0000-1000-8000-00805f9b34fb",  # AVRCP Target
            "0000110c-0000-1000-8000-00805f9b34fb",  # AVRCP Controller
        ]
        if uuid.lower() in a2dp_uuids:
            logger.info(f"Auto-authorizing A2DP/AVRCP service for {name}")
            return
            
        # For other services, request user confirmation
        request = PairingRequest(
            device_path=device,
            device_name=name,
            device_address=address,
        )
        self._pending_requests[device] = request
        
        if self._on_pairing_request:
            self._on_pairing_request(request)
            
        accepted = await self._wait_for_response(request)
        
        if not accepted:
            from dbus_fast import DBusError
            raise DBusError("org.bluez.Error.Rejected", "Service authorization rejected")
            
    @method()
    def Cancel(self) -> None:
        """Cancel ongoing pairing."""
        logger.info("Pairing cancelled")
        # Cancel all pending requests
        for request in self._pending_requests.values():
            request.status = PairingStatus.REJECTED
            if request.future and not request.future.done():
                request.future.set_result(None)
        self._pending_requests.clear()
        
    def accept_pairing(self, device_path: str) -> bool:
        """Accept a pending pairing request."""
        if device_path in self._pending_requests:
            request = self._pending_requests[device_path]
            request.status = PairingStatus.ACCEPTED
            if request.future and not request.future.done():
                request.future.set_result(None)
            return True
        return False
        
    def reject_pairing(self, device_path: str) -> bool:
        """Reject a pending pairing request."""
        if device_path in self._pending_requests:
            request = self._pending_requests[device_path]
            request.status = PairingStatus.REJECTED
            if request.future and not request.future.done():
                request.future.set_result(None)
            return True
        return False


class BluetoothManager:
    """
    Manager for Bluetooth adapter and device operations.
    
    Handles:
    - Adapter configuration (discoverable, pairable)
    - Device management (trust, connect, disconnect, remove)
    - Agent registration
    """
    
    def __init__(self):
        self._bus: MessageBus | None = None
        self._agent: BluetoothAgent | None = None
        self._adapter_path: str | None = None
        self._on_device_change: Callable[[], None] | None = None
        
    @property
    def agent(self) -> BluetoothAgent | None:
        """Get the Bluetooth agent."""
        return self._agent
        
    def set_device_change_callback(self, callback: Callable[[], None]) -> None:
        """Set callback for device changes."""
        self._on_device_change = callback
        
    async def connect(self) -> None:
        """Connect to D-Bus and find the Bluetooth adapter."""
        self._bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        
        # Find the adapter
        introspection = await self._bus.introspect(BLUEZ_SERVICE, "/")
        proxy = self._bus.get_proxy_object(BLUEZ_SERVICE, "/", introspection)
        obj_manager = proxy.get_interface(OBJECT_MANAGER_INTERFACE)
        
        objects = await obj_manager.call_get_managed_objects()
        
        for path, interfaces in objects.items():
            if ADAPTER_INTERFACE in interfaces:
                self._adapter_path = path
                logger.info(f"Found Bluetooth adapter: {path}")
                break
                
        if not self._adapter_path:
            raise RuntimeError("No Bluetooth adapter found")
            
    async def register_agent(
        self,
        on_pairing_request: Callable[[PairingRequest], None] | None = None,
        pairing_timeout: int = 60,
    ) -> BluetoothAgent:
        """Register the Bluetooth agent."""
        if not self._bus:
            raise RuntimeError("Not connected to D-Bus")
            
        self._agent = BluetoothAgent(on_pairing_request, pairing_timeout)
        self._agent.set_bus(self._bus)
        
        agent_path = "/org/piston/bluetooth/agent"
        self._bus.export(agent_path, self._agent)
        
        # Register with BlueZ
        introspection = await self._bus.introspect(BLUEZ_SERVICE, "/org/bluez")
        proxy = self._bus.get_proxy_object(BLUEZ_SERVICE, "/org/bluez", introspection)
        agent_manager = proxy.get_interface(AGENT_MANAGER_INTERFACE)
        
        await agent_manager.call_register_agent(agent_path, "DisplayYesNo")
        await agent_manager.call_request_default_agent(agent_path)
        
        logger.info("Bluetooth agent registered")
        return self._agent
        
    async def set_discoverable(self, discoverable: bool, timeout: int = 0) -> None:
        """Set adapter discoverable state."""
        if not self._bus or not self._adapter_path:
            return
            
        introspection = await self._bus.introspect(BLUEZ_SERVICE, self._adapter_path)
        proxy = self._bus.get_proxy_object(BLUEZ_SERVICE, self._adapter_path, introspection)
        props = proxy.get_interface(PROPERTIES_INTERFACE)
        
        await props.call_set(ADAPTER_INTERFACE, "Discoverable", Variant("b", discoverable))
        if timeout >= 0:
            await props.call_set(ADAPTER_INTERFACE, "DiscoverableTimeout", Variant("u", timeout))
            
        logger.info(f"Adapter discoverable: {discoverable}")
        
    async def set_pairable(self, pairable: bool, timeout: int = 0) -> None:
        """Set adapter pairable state."""
        if not self._bus or not self._adapter_path:
            return
            
        introspection = await self._bus.introspect(BLUEZ_SERVICE, self._adapter_path)
        proxy = self._bus.get_proxy_object(BLUEZ_SERVICE, self._adapter_path, introspection)
        props = proxy.get_interface(PROPERTIES_INTERFACE)
        
        await props.call_set(ADAPTER_INTERFACE, "Pairable", Variant("b", pairable))
        if timeout >= 0:
            await props.call_set(ADAPTER_INTERFACE, "PairableTimeout", Variant("u", timeout))
            
        logger.info(f"Adapter pairable: {pairable}")
        
    async def get_adapter_info(self) -> dict:
        """Get adapter information."""
        if not self._bus or not self._adapter_path:
            return {}
            
        introspection = await self._bus.introspect(BLUEZ_SERVICE, self._adapter_path)
        proxy = self._bus.get_proxy_object(BLUEZ_SERVICE, self._adapter_path, introspection)
        props = proxy.get_interface(PROPERTIES_INTERFACE)
        
        all_props = await props.call_get_all(ADAPTER_INTERFACE)
        
        return {
            "name": all_props.get("Name", Variant("s", "")).value,
            "alias": all_props.get("Alias", Variant("s", "")).value,
            "address": all_props.get("Address", Variant("s", "")).value,
            "powered": all_props.get("Powered", Variant("b", False)).value,
            "discoverable": all_props.get("Discoverable", Variant("b", False)).value,
            "pairable": all_props.get("Pairable", Variant("b", False)).value,
        }
        
    async def set_adapter_alias(self, alias: str) -> None:
        """Set the adapter's friendly name."""
        if not self._bus or not self._adapter_path:
            return
            
        introspection = await self._bus.introspect(BLUEZ_SERVICE, self._adapter_path)
        proxy = self._bus.get_proxy_object(BLUEZ_SERVICE, self._adapter_path, introspection)
        props = proxy.get_interface(PROPERTIES_INTERFACE)
        
        await props.call_set(ADAPTER_INTERFACE, "Alias", Variant("s", alias))
        logger.info(f"Adapter alias set to: {alias}")
        
    async def get_devices(self) -> list[BluetoothDevice]:
        """Get all paired/known devices."""
        if not self._bus:
            return []
            
        devices = []
        
        introspection = await self._bus.introspect(BLUEZ_SERVICE, "/")
        proxy = self._bus.get_proxy_object(BLUEZ_SERVICE, "/", introspection)
        obj_manager = proxy.get_interface(OBJECT_MANAGER_INTERFACE)
        
        objects = await obj_manager.call_get_managed_objects()
        
        for path, interfaces in objects.items():
            if DEVICE_INTERFACE in interfaces:
                device_props = interfaces[DEVICE_INTERFACE]
                device = BluetoothDevice(
                    path=path,
                    address=device_props.get("Address", Variant("s", "")).value,
                    name=device_props.get("Name", Variant("s", "Unknown")).value,
                    paired=device_props.get("Paired", Variant("b", False)).value,
                    trusted=device_props.get("Trusted", Variant("b", False)).value,
                    connected=device_props.get("Connected", Variant("b", False)).value,
                    icon=device_props.get("Icon", Variant("s", "audio-card")).value,
                )
                devices.append(device)
                
        return devices
        
    async def get_connected_device(self) -> BluetoothDevice | None:
        """Get the currently connected device, if any."""
        devices = await self.get_devices()
        for device in devices:
            if device.connected:
                return device
        return None
        
    async def trust_device(self, device_path: str) -> None:
        """Trust a device for auto-connection."""
        if not self._bus:
            return
            
        introspection = await self._bus.introspect(BLUEZ_SERVICE, device_path)
        proxy = self._bus.get_proxy_object(BLUEZ_SERVICE, device_path, introspection)
        props = proxy.get_interface(PROPERTIES_INTERFACE)
        
        await props.call_set(DEVICE_INTERFACE, "Trusted", Variant("b", True))
        logger.info(f"Device trusted: {device_path}")
        
    async def connect_device(self, device_path: str) -> None:
        """Connect to a device."""
        if not self._bus:
            return
            
        introspection = await self._bus.introspect(BLUEZ_SERVICE, device_path)
        proxy = self._bus.get_proxy_object(BLUEZ_SERVICE, device_path, introspection)
        device = proxy.get_interface(DEVICE_INTERFACE)
        
        await device.call_connect()
        logger.info(f"Device connected: {device_path}")
        
    async def disconnect_device(self, device_path: str) -> None:
        """Disconnect a device."""
        if not self._bus:
            return
            
        introspection = await self._bus.introspect(BLUEZ_SERVICE, device_path)
        proxy = self._bus.get_proxy_object(BLUEZ_SERVICE, device_path, introspection)
        device = proxy.get_interface(DEVICE_INTERFACE)
        
        await device.call_disconnect()
        logger.info(f"Device disconnected: {device_path}")
        
    async def remove_device(self, device_path: str) -> None:
        """Remove/unpair a device."""
        if not self._bus or not self._adapter_path:
            return
            
        introspection = await self._bus.introspect(BLUEZ_SERVICE, self._adapter_path)
        proxy = self._bus.get_proxy_object(BLUEZ_SERVICE, self._adapter_path, introspection)
        adapter = proxy.get_interface(ADAPTER_INTERFACE)
        
        await adapter.call_remove_device(device_path)
        logger.info(f"Device removed: {device_path}")
        
    async def disconnect(self) -> None:
        """Disconnect from D-Bus."""
        if self._bus:
            self._bus.disconnect()
            self._bus = None
