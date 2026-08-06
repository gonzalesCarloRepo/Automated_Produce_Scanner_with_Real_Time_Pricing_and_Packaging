THESIS DEVICE BUNDLE

Files:
- init_databases.py
- printer_actuator.py
- transaction_gui_crud.py
- vegetable_gui_crud.py
- barcode_lookup_gui.py
- thesis_device_main.py

Suggested run order on Raspberry Pi:
1. python3 init_databases.py
2. python3 vegetable_gui_crud.py
3. python3 transaction_gui_crud.py
4. python3 barcode_lookup_gui.py
5. python3 thesis_device_main.py

Notes:
- thesis_device_main.py was updated to support one-vegetable-only logic for garlic, onion, and marble_potato.
- If more than one different vegetable type is detected at the same time, the LCD and preview show a warning and printing/sealing is blocked.
- Existing confirmed mappings are preserved:
  GPIO17 button, GPIO23/24 BTS7960, GPIO6/5 HX711, I2C LCD 0x27, printer /dev/usb/lp0.
- Model path remains:
  /home/jekaca/virtual_environment/jekaca_sama-project-1-linux-aarch64-v2.eim
