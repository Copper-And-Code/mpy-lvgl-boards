# Animation: a bar sweeping left and right and an arc filling up.
#
#   mpremote run examples/animation.py
#
# LVGL animations run from display_driver's timer. Rendering is double
# buffered, so moving objects do not tear.
import lvgl as lv
import display_driver
import ui

W, H = display_driver.WIDTH, display_driver.HEIGHT

scr = lv.obj()
scr.set_style_bg_color(lv.color_hex(0x000000), 0)

bar = lv.obj(scr)
BAR = ui.px(16)
bar.set_size(BAR, H)
bar.set_style_bg_color(lv.color_hex(0x00C0FF), 0)
bar.set_style_border_width(0, 0)
bar.set_style_radius(0, 0)

a = lv.anim_t()
a.init()
a.set_var(bar)
a.set_values(0, W - BAR)
a.set_duration(1500)
a.set_reverse_duration(1500)
a.set_repeat_count(lv.ANIM_REPEAT_INFINITE)
a.set_path_cb(lv.anim_t.path_ease_in_out)
a.set_custom_exec_cb(lambda anim, v: bar.set_x(v))
a.start()

arc = lv.arc(scr)
arc.set_size(ui.px(120), ui.px(120))
arc.set_style_arc_width(ui.px(12), 0)
arc.set_style_arc_width(ui.px(12), lv.PART.INDICATOR)
arc.set_style_pad_all(ui.px(4), lv.PART.KNOB)
arc.center()
arc.remove_flag(lv.obj.FLAG.CLICKABLE)

b = lv.anim_t()
b.init()
b.set_var(arc)
b.set_values(0, 100)
b.set_duration(2000)
b.set_repeat_count(lv.ANIM_REPEAT_INFINITE)
b.set_custom_exec_cb(lambda anim, v: arc.set_value(v))
b.start()

lv.screen_load(scr)
