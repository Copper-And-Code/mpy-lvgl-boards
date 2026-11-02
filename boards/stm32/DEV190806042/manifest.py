include("$(PORT_DIR)/boards/manifest.py")
include("$(LVMP_DIR)/manifest.py")
c_module("$(BOARD_DIR)/../../../modules/st_ltdc")
module("panels.py", base_path="$(BOARD_DIR)/../../../python")
