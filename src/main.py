#!/usr/bin/env python3
"""
Piston Audio - Raspberry Pi Bluetooth Audio Receiver

Main entry point for the application.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from nicegui import app, ui

from src.audio_manager import AudioManager
from src.bluetooth_agent import BluetoothManager
from src.ui import PistonAudioUI

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


class PistonAudio:
    """Main application class."""
    
    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8080,
        device_name: str = "Piston Audio",
    ):
        self.host = host
        self.port = port
        self.device_name = device_name
        
        self.bt_manager = BluetoothManager()
        self.audio_manager = AudioManager()
        self.ui: PistonAudioUI | None = None
        
    async def setup(self) -> None:
        """Initialize the application."""
        logger.info("Starting Piston Audio...")
        
        # Connect to D-Bus and setup Bluetooth
        try:
            await self.bt_manager.connect()
            logger.info("Connected to Bluetooth adapter")
            
            # Set adapter name and make discoverable
            await self.bt_manager.set_adapter_alias(self.device_name)
            await self.bt_manager.set_discoverable(True, timeout=0)
            await self.bt_manager.set_pairable(True, timeout=0)
            
            # Register the pairing agent
            self.ui = PistonAudioUI(self.bt_manager, self.audio_manager)
            await self.bt_manager.register_agent(
                on_pairing_request=self.ui.on_pairing_request,
                pairing_timeout=60,
            )
            logger.info("Bluetooth agent registered")
            
        except Exception as e:
            logger.error(f"Failed to setup Bluetooth: {e}")
            logger.warning("Running in audio-only mode (no Bluetooth)")
            
            # Create UI anyway for audio control
            self.ui = PistonAudioUI(self.bt_manager, self.audio_manager)
            
        # Setup UI routes
        self.ui.setup_routes()
        
    async def shutdown(self) -> None:
        """Cleanup on shutdown."""
        logger.info("Shutting down Piston Audio...")
        
        try:
            # Disable discoverable mode
            await self.bt_manager.set_discoverable(False)
            await self.bt_manager.set_pairable(False)
        except Exception:
            pass
            
        try:
            await self.bt_manager.disconnect()
        except Exception:
            pass
        
    def run(self) -> None:
        """Run the application."""
        # Use NiceGUI's startup hook to run async setup
        # This ensures we use the same event loop as NiceGUI
        app.on_startup(self.setup)
        app.on_shutdown(self.shutdown)
        
        # Start NiceGUI - it manages its own event loop
        ui.run(
            host=self.host,
            port=self.port,
            title="Piston Audio",
            favicon="speaker",
            dark=None,  # Auto dark mode
            reload=False,
            show=False,  # Don't open browser on headless
        )


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Piston Audio - Raspberry Pi Bluetooth Audio Receiver",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host to bind to (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=7654,
        help="Port to listen on (default: 7654)",
    )
    parser.add_argument(
        "--name",
        default="Piston Audio",
        help="Bluetooth device name (default: Piston Audio)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    
    args = parser.parse_args()
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        
    app_instance = PistonAudio(
        host=args.host,
        port=args.port,
        device_name=args.name,
    )
    app_instance.run()


if __name__ == "__main__":
    main()
