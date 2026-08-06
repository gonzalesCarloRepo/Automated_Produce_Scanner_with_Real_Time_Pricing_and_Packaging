Updated file: thesis_device_main.py

What was changed:
1. Added adjustable actuator default position:
   - DEFAULT_POSITION_BEFORE_PRESS = "extended"
   - POSITION_AFTER_PRESS = "retracted"
   - DEFAULT_POSITION_MOVE_TIME_S
   - POSITION_AFTER_PRESS_MOVE_TIME_S
   - PRESS_HOLD_TIME_S
   - RETURN_TO_DEFAULT_DELAY_S
   - DIR_CHANGE_PAUSE_S
   - MOVE_TO_DEFAULT_ON_STARTUP
   - ENSURE_DEFAULT_BEFORE_EACH_CYCLE

2. New actuator behavior:
   - On startup, the actuator can move to the default position.
   - When button GPIO17 is pressed, actuator moves to POSITION_AFTER_PRESS.
   - It pauses/holds.
   - It returns to DEFAULT_POSITION_BEFORE_PRESS.

3. Added three-vegetable handling:
   - Supports onion, garlic, marble_potato from vegetable_price.db.
   - Ignores detections below 60 percent confidence.
   - If two or more vegetable types are detected at the same time, LCD shows:
       MULTIPLE VEG
       ONE TYPE ONLY
   - Printing/sealing is blocked when multiple vegetable types are detected.

How to use on Raspberry Pi:
1. Backup your current thesis_device_main.py.
2. Copy this updated thesis_device_main.py into your final_device folder.
3. Keep hx711_calibration.json, vegetable_price.db, and customer_transactions.db in the same folder.
4. Run using Thonny or terminal.
5. Calibrate actuator timing values slowly on real hardware.

Important safety note:
The actuator has no position feedback sensor, so the positions are time-based. Start with short timing values and increase gradually to avoid forcing the sealer mechanism.
