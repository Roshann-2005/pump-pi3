"""
Solar-pump low-voltage disconnect (LVD) for Raspberry Pi.

Reads the battery voltage from an MCP3008 ADC (channel CH0) through a
resistor divider, prints the voltage and pump state to the terminal once
per second, and drives the HW-517 MOSFET on GPIO17 so the battery is not
over-discharged.

Wiring (matches the diagram):
  - Divider midpoint -> MCP3008 CH0
  - MCP3008 VDD + VREF -> Pi 3V3, AGND + DGND -> GND
  - MCP3008 CLK/DOUT/DIN/CS -> Pi SCLK/MISO/MOSI/CE0  (SPI)
  - GPIO17 -> HW-517 TRIG   (HIGH = pump ON, LOW = pump OFF)

Setup on the Pi:
  sudo raspi-config   ->  Interface Options  ->  SPI  ->  enable
  pip install gpiozero        (usually already present on Raspberry Pi OS)

Run:
  python3 pump_lvd.py
"""

import time
from gpiozero import MCP3008, DigitalOutputDevice

# ----------------------------- HARDWARE -------------------------------
ADC_CHANNEL = 0          # MCP3008 CH0
VREF        = 3.3        # volts on MCP3008 VDD/VREF (the Pi's 3V3 rail)
R1          = 100_000    # divider TOP resistor   (battery+ -> node), ohms
R2          = 33_000     # divider BOTTOM resistor (node -> GND), ohms
CAL         = 1.000      # calibration: (multimeter volts) / (printed volts)

PUMP_PIN    = 17         # GPIO17 -> HW-517 TRIG

DIVIDER = R2 / (R1 + R2)        # node voltage = battery * DIVIDER

# ----------------------------- LVD LOGIC ------------------------------
V_OFF        = 1.3      # disconnect (pump OFF) when voltage drops below this
V_ON         = 1.5      # reconnect (pump ON) when voltage rises above this
DEBOUNCE_S   = 5.0       # a threshold crossing must persist this long to act
SAMPLE_PERIOD_S = 0.1    # seconds between reads / prints
N_AVG        = 16        # ADC samples averaged per reading (noise smoothing)

# ----------------------------- SETUP ----------------------------------
adc  = MCP3008(channel=ADC_CHANNEL)
# Start OFF so the pump is never energised before the logic is in control.
pump = DigitalOutputDevice(PUMP_PIN, initial_value=False)


def read_voltage():
    """Return the battery voltage in volts (averaged)."""
    raw = sum(adc.value for _ in range(N_AVG)) / N_AVG   # 0.0 .. 1.0
    node_v = raw * VREF
    return node_v                                  # volts at CH0
    return node_v / DIVIDER * CAL                        # volts at battery


def main():
    pump_on = False          # current pump state
    candidate = None         # pending new state awaiting debounce
    candidate_since = 0.0

    print("Battery LVD running.  Thresholds: "
          f"OFF < {V_OFF:.1f} V,  ON > {V_ON:.1f} V.  Ctrl+C to stop.\n")
    try:
        while True:
            v = read_voltage()
            now = time.monotonic()

            # What state does the present voltage call for? (hysteresis band -> hold)
            if pump_on and v < V_OFF:
                want = False
            elif (not pump_on) and v > V_ON:
                want = True
            else:
                want = pump_on

            note = ""
            if want != pump_on:
                # A change is wanted: require it to persist for DEBOUNCE_S.
                if candidate != want:
                    candidate = want
                    candidate_since = now
                elapsed = now - candidate_since
                if elapsed >= DEBOUNCE_S:
                    pump_on = want
                    pump.value = pump_on
                    candidate = None
                else:
                    note = (f"   (-> {'ON' if want else 'OFF'} "
                            f"in {DEBOUNCE_S - elapsed:0.0f}s)")
            else:
                candidate = None  # voltage settled back inside the band

            ts = time.strftime("%H:%M:%S")
            print(f"[{ts}]  {v:5.2f} V   pump {'ON ' if pump.value else 'OFF'}{note}")
            time.sleep(SAMPLE_PERIOD_S)

    except KeyboardInterrupt:
        pass
    finally:
        pump.off()            # fail-safe: leave the pump OFF on exit
        print("\nStopped - pump OFF.")


if __name__ == "__main__":
    main()
