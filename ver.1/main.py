"""
PuppetBot main.py
ESP32 + MicroPython
サーボ左腕:GPIO14 / 右腕:GPIO15 / ボタンA:GPIO12 / ボタンB:GPIO13 / LED:GPIO2
"""

import asyncio
import network
import time
import json
import gc
from machine import Pin, PWM

# ---- ピン設定 ----
servo_left  = PWM(Pin(14), freq=50)
servo_right = PWM(Pin(15), freq=50)
button_a    = Pin(12, Pin.IN, Pin.PULL_UP)
button_b    = Pin(13, Pin.IN, Pin.PULL_UP)
led         = Pin(2, Pin.OUT)

# ---- サーボ定数 (duty_u16 / 50Hz / 20ms周期) ----
# SG90: 1.0ms=-45°, 1.5ms=中立, 2.0ms=+45°
SERVO_DOWN   = 1638   # 0.5ms  (-90° 左端)
SERVO_CENTER = 4751   # 1.45ms ( 0°  中立)
SERVO_UP     = 7864   # 2.4ms  (+90° 右端)

# ---- グローバル状態 ----
auto_mode = False
speed     = 3       # 1〜5
is_waving = False

# ---- Eventフラグ（create_task不要・メモリ確保なし） ----
ev_left  = asyncio.Event()
ev_right = asyncio.Event()
ev_both  = asyncio.Event()

# ---- サーボ制御 ----
def servo_set(servo, duty):
    servo.duty_u16(duty)

async def _do_wave(servo):
    servo_set(servo, SERVO_CENTER)
    await asyncio.sleep_ms(400)
    servo_set(servo, SERVO_UP)
    await asyncio.sleep_ms(500)
    servo_set(servo, SERVO_CENTER)
    await asyncio.sleep_ms(400)
    servo.duty_u16(0)

async def _do_both():
    servo_set(servo_left,  SERVO_CENTER)
    servo_set(servo_right, SERVO_CENTER)
    await asyncio.sleep_ms(400)
    servo_set(servo_left,  SERVO_UP)
    servo_set(servo_right, SERVO_UP)
    await asyncio.sleep_ms(500)
    servo_set(servo_left,  SERVO_CENTER)
    servo_set(servo_right, SERVO_CENTER)
    await asyncio.sleep_ms(400)
    servo_left.duty_u16(0)
    servo_right.duty_u16(0)

# ---- 常駐waveタスク（起動時に1回だけ生成） ----
async def wave_runner():
    global is_waving
    while True:
        await asyncio.sleep_ms(10)
        if is_waving:
            continue
        if ev_both.is_set():
            ev_both.clear()
            is_waving = True
            await _do_both()
            is_waving = False
            gc.collect()
        elif ev_left.is_set():
            ev_left.clear()
            is_waving = True
            await _do_wave(servo_left)
            is_waving = False
            gc.collect()
        elif ev_right.is_set():
            ev_right.clear()
            is_waving = True
            await _do_wave(servo_right)
            is_waving = False
            gc.collect()

def request_wave(ev):
    """動作中でなければEventをセット"""
    if not is_waving:
        ev.set()

# ---- WiFi APモード起動 ----
def start_ap():
    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    ap.config(essid='PuppetBot', authmode=network.AUTH_OPEN)
    timeout = 10
    while not ap.active() and timeout > 0:
        time.sleep(0.5)
        timeout -= 0.5
    print('AP IP:', ap.ifconfig()[0])

# ---- HTML ----
HTML = b"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>PuppetBot</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,sans-serif;background:#1a1a2e;color:#eee;
     min-height:100vh;display:flex;flex-direction:column;align-items:center;padding:20px 16px}
h1{font-size:1.6rem;margin:16px 0 28px;color:#e94560;letter-spacing:.05em}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;width:100%;max-width:380px}
.btn{padding:30px 8px;font-size:1.15rem;font-weight:700;border:none;border-radius:18px;
     cursor:pointer;transition:transform .1s,opacity .1s;line-height:1.4}
.btn:active{transform:scale(.95);opacity:.8}
.btn-l{background:#16213e;color:#7ec8e3}
.btn-r{background:#16213e;color:#f5a623}
.btn-b{background:#533483;color:#fff;grid-column:span 2}
.btn-a{grid-column:span 2;padding:22px 8px;font-size:1rem;border-radius:14px}
.off{background:#2a2a3a;color:#888}
.on{background:#e94560;color:#fff}
.sp{width:100%;max-width:380px;margin-top:22px}
.sp label{display:block;margin-bottom:10px;font-size:.9rem;color:#aaa}
input[type=range]{width:100%;height:6px;accent-color:#e94560;cursor:pointer}
#msg{margin-top:14px;font-size:.8rem;color:#555;height:1.2em;text-align:center}
</style>
</head>
<body>
<h1>&#x1F9F8; PuppetBot</h1>
<div class="grid">
  <button class="btn btn-l" onclick="cmd('/wave/left')">&#x1F91A;<br>左腕</button>
  <button class="btn btn-r" onclick="cmd('/wave/right')">&#x1F91A;<br>右腕</button>
  <button class="btn btn-b" onclick="cmd('/wave/both')">&#x1F64C; 両腕同時</button>
  <button id="aBtn" class="btn btn-a off" onclick="toggleAuto()">自動モード OFF</button>
</div>
<div class="sp">
  <label>スピード: <strong id="spv">3</strong></label>
  <input type="range" min="1" max="5" value="3" oninput="setSpd(this.value)">
</div>
<p id="msg">&#x2014;</p>
<script>
async function cmd(p){
  document.getElementById('msg').textContent='送信中…';
  try{await fetch(p,{method:'POST'});document.getElementById('msg').textContent='OK';}
  catch(e){document.getElementById('msg').textContent='Error: '+e;}
}
async function toggleAuto(){
  await fetch('/auto',{method:'POST'});
  poll();
}
async function setSpd(v){
  document.getElementById('spv').textContent=v;
  await fetch('/speed',{method:'POST',
    headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'speed='+v});
}
async function poll(){
  try{
    const r=await fetch('/status');
    const d=await r.json();
    const b=document.getElementById('aBtn');
    b.textContent='自動モード '+(d.auto?'ON':'OFF');
    b.className='btn btn-a '+(d.auto?'on':'off');
  }catch(e){}
}
setInterval(poll,1500);
poll();
</script>
</body>
</html>"""

# ---- HTTPハンドラ ----
async def handle_client(reader, writer):
    global auto_mode, speed
    try:
        raw = await asyncio.wait_for(reader.read(2048), timeout=5.0)
        text = raw.decode('utf-8', 'ignore')
        first = text.split('\r\n')[0].split()
        if len(first) < 2:
            return
        method, path = first[0], first[1]

        # Content-Type のボディを取得
        body = text[text.find('\r\n\r\n')+4:] if '\r\n\r\n' in text else ''

        if method == 'GET' and path in ('/', '/index.html'):
            hdr = b'HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nConnection: close\r\n\r\n'
            writer.write(hdr + HTML)

        elif method == 'GET' and path == '/status':
            data = json.dumps({'auto': auto_mode, 'speed': speed})
            writer.write(('HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n'
                          'Connection: close\r\n\r\n' + data).encode())

        elif method == 'POST' and path == '/wave/left':
            request_wave(ev_left)
            writer.write(b'HTTP/1.1 200 OK\r\nConnection: close\r\n\r\nOK')

        elif method == 'POST' and path == '/wave/right':
            request_wave(ev_right)
            writer.write(b'HTTP/1.1 200 OK\r\nConnection: close\r\n\r\nOK')

        elif method == 'POST' and path == '/wave/both':
            request_wave(ev_both)
            writer.write(b'HTTP/1.1 200 OK\r\nConnection: close\r\n\r\nOK')

        elif method == 'POST' and path == '/auto':
            auto_mode = not auto_mode
            led.value(1 if auto_mode else 0)
            writer.write(b'HTTP/1.1 200 OK\r\nConnection: close\r\n\r\nOK')

        elif method == 'POST' and path == '/speed':
            for p in body.split('&'):
                if p.startswith('speed='):
                    try:
                        speed = max(1, min(5, int(p[6:])))
                    except Exception:
                        pass
            writer.write(b'HTTP/1.1 200 OK\r\nConnection: close\r\n\r\nOK')

        else:
            writer.write(b'HTTP/1.1 404 Not Found\r\nConnection: close\r\n\r\nNot Found')

        await writer.drain()
    except Exception as e:
        print('HTTP error:', e)
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass

# ---- ボタンタスク ----
# ステートマシン方式デバウンス
# idle → debouncing（50ms安定待ち）→ pressed → 離したら発火 → idle
DEBOUNCE_MS = 50   # この時間ずっと押されていたら「確定」

async def button_task():
    global auto_mode

    a_state          = 'idle'   # idle / debouncing / pressed
    b_state          = 'idle'
    a_change_ms      = 0
    b_change_ms      = 0
    a_press_ms       = 0
    a_long_triggered = False

    while True:
        now = time.ticks_ms()
        a = button_a.value()  # 押してる=0, 離してる=1
        b = button_b.value()

        # ---- ボタンA ----
        if a_state == 'idle':
            if a == 0:                         # 押し始め検知
                a_state     = 'debouncing'
                a_change_ms = now
                a_long_triggered = False

        elif a_state == 'debouncing':
            if a == 1:                         # 50ms以内に離れた＝チャタリング
                a_state = 'idle'
            elif time.ticks_diff(now, a_change_ms) >= DEBOUNCE_MS:
                a_state    = 'pressed'         # 確定
                a_press_ms = now

        elif a_state == 'pressed':
            if a == 0:                         # 押し続け中
                if (not a_long_triggered and
                        time.ticks_diff(now, a_press_ms) >= 1000):
                    auto_mode = not auto_mode
                    led.value(1 if auto_mode else 0)
                    a_long_triggered = True
            else:                              # 離した → 発火
                if not a_long_triggered:
                    request_wave(ev_left)
                a_state = 'idle'

        # ---- ボタンB ----
        if b_state == 'idle':
            if b == 0:
                b_state     = 'debouncing'
                b_change_ms = now

        elif b_state == 'debouncing':
            if b == 1:                         # チャタリング
                b_state = 'idle'
            elif time.ticks_diff(now, b_change_ms) >= DEBOUNCE_MS:
                b_state = 'pressed'            # 確定

        elif b_state == 'pressed':
            if b == 1:                         # 離した → 発火
                request_wave(ev_right)
                b_state = 'idle'

        await asyncio.sleep_ms(5)  # 5msポーリング（チャタリング検出精度向上）

# ---- 自動モードタスク ----
async def auto_task():
    toggle = False
    while True:
        if auto_mode and not is_waving:
            request_wave(ev_left if toggle else ev_right)
            toggle = not toggle
            interval = 6 - speed          # speed=1→5秒 … speed=5→1秒
            await asyncio.sleep(interval)
        else:
            await asyncio.sleep_ms(200)

# ---- メイン ----
async def main():
    # 起動時にサーボを中立位置へ
    servo_set(servo_left,  SERVO_CENTER)
    servo_set(servo_right, SERVO_CENTER)
    led.value(0)

    start_ap()

    server = await asyncio.start_server(handle_client, '0.0.0.0', 80)
    print('Server ready: http://192.168.4.1/')

    await asyncio.gather(
        wave_runner(),
        button_task(),
        auto_task(),
    )

asyncio.run(main())
