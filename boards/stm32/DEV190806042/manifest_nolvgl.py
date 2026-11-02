# Board without LVGL (bring-up builds): pass FROZEN_MANIFEST=<this file>.
include("$(PORT_DIR)/boards/manifest.py")
c_module("$(BOARD_DIR)/../../../modules/st_ltdc")
module("panels.py", base_path="$(BOARD_DIR)/../../../python")
