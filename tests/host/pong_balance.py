# Balance check of examples/pong.py on CPython, LVGL and hardware stubbed out:
# simulated players of different speed against the MCU paddle.
#   python3 -I tests/host/pong_balance.py examples/pong.py
import sys, types, random
class D:
    def __init__(self,*a,**k): pass
    def __getattr__(self,n): return D()
    def __call__(self,*a,**k): return D()
    def __int__(self): return 0
    def __index__(self): return 0
    def __neg__(self): return 0
    def __floordiv__(self,o): return 0
    def __rfloordiv__(self,o): return 0
    def __mod__(self,o): return 0
lv = types.ModuleType('lvgl'); lv.__getattr__ = lambda n: D()
dd = types.ModuleType('display_driver'); dd.WIDTH = dd.HEIGHT = 240
m = types.ModuleType('machine'); m.Pin = D; m.PWM = D
sys.modules.update(lvgl=lv, display_driver=dd, machine=m)
src = open(sys.argv[1]).read()
def play(human_speed, react, seed, games=20):
    random.seed(seed)
    wins = [0, 0]; rallies = []
    for g in range(games):
        ns = {}; exec(src, ns)
        ns['SOUND'] = False
        ns['new_game']()
        hits = 0; ticks = 0
        while ns['state'] != 'over' and ticks < 200000:
            # simulated human: follows the ball when it comes, limited speed
            st = ns
            if st['vx'] < 0 and st['bx'] < 240 * react:
                target = st['by'] + 3 - st['PH'] / 2
            else:
                target = (240 - st['PH']) / 2
            d = max(-human_speed, min(human_speed, target - st['uy']))
            st['uy'] = max(0, min(240 - st['PH'], st['uy'] + d))
            st['on_tick'](None); ticks += 1
        wins[0 if st['points'][0] >= st['WIN'] else 1] += 1
    return wins
for hs, react in ((1.5, .6), (2.0, .6), (2.4, .65), (3.0, .7), (4.0, .8), (99, 1.0)):
    print('human speed %4.1f px/tick, reacts at %.0f%% of the field: user-MCU games %s' % (hs, react * 100, play(hs, react, 1)))
