import asyncio
from bleak import BleakScanner, BleakClient

# The standard Nordic UART Service UUID that Pybricks uses for usys.stdin
NUS_RX_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"

# Note: If you renamed your hub in the Pybricks IDE, change this string!
HUB_NAME = "test"

async def main():
    print(f"Searching for '{HUB_NAME}' via Bluetooth...")
    
    # 1. Scan the room for the hub
    device = await BleakScanner.find_device_by_name(HUB_NAME)
    
    if not device:
        print("Could not find the hub!")
        print("Make sure it is powered on and completely disconnected from the Pybricks web IDE.")
        return

    print(f"Found it! Connecting to {device.address}...")
    
    # 2. Connect and stream data
    async with BleakClient(device) as client:
        print("Connected! Sending flap commands. Watch the robot!")
        
        for i in range(5):
            print("Sending 100 (open)...")
            # response=False makes it act like a fast, raw serial write
            await client.write_gatt_char(NUS_RX_UUID, b"100\n", response=False)
            await asyncio.sleep(0.5)

            print("Sending 0 (close)...")
            await client.write_gatt_char(NUS_RX_UUID, b"0\n", response=False)
            await asyncio.sleep(0.5)
            
        print("\nDone. Did the motor move?")

if __name__ == "__main__":
    asyncio.run(main())