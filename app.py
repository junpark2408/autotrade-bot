from flask import Flask, request, jsonify, render_template_string
import requests
import time
import hmac
import hashlib
import json

app = Flask(__name__)

# 텔레그램 설정
TELEGRAM_BOT_TOKEN = '7695863748:AAG-BXuSNB85vRdYvNq_LCemH1zCRm23sjQ'
TELEGRAM_CHAT_ID = '1956090853'

# 거래소 API 설정 (Bitget 실전용)
EXCHANGE_API_KEY = 'bg_20ae8d8409bf0bf122ad61d090088323'
EXCHANGE_API_SECRET = '1895222457d096486282b9813789ccf318c231f94f301ab20debbb8e5d6eef8c'
EXCHANGE_API_PASSPHRASE = 'qkrwnsgud2408'
BASE_URL = "https://api.bitget.com"

# 사용자 설정값 (UI 변경 가능)
LEVERAGE = 5
ENTRY_PERCENT = 20

# 상태 변수
position = None
tp1_done = False
tp2_done = False
bot_active = True

# 텔레그램 전송 함수
def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    try:
        requests.post(url, json=data)
    except Exception as e:
        print("텔레그램 에러", e)

# 거래소 주문 함수
def exchange_order(order_type, side, size):
    timestamp = str(int(time.time() * 1000))
    method = "POST"
    request_path = "/api/v1/mix/order/place"

    body = {
        "symbol": "BTCUSDT",
        "marginCoin": "USDT",
        "size": size,
        "side": "open_long" if side == "롱" else "open_short" if order_type == "시장가" else "close_long" if side == "롱" else "close_short",
        "orderType": "market",
        "leverage": LEVERAGE
    }

    body_str = json.dumps(body)
    prehash = timestamp + method + request_path + body_str
    sign = hmac.new(EXCHANGE_API_SECRET.encode('utf-8'), prehash.encode('utf-8'), hashlib.sha256).hexdigest()

    headers = {
        "ACCESS-KEY": EXCHANGE_API_KEY,
        "ACCESS-SIGN": sign,
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": EXCHANGE_API_PASSPHRASE,
        "Content-Type": "application/json"
    }

    url = BASE_URL + request_path

    try:
        response = requests.post(url, headers=headers, data=body_str)
        result = response.json()
        send_telegram(f"[거래소 주문 결과] {result}")
        return result.get("code") == "00000"
    except Exception as e:
        send_telegram(f"[거래소 주문 에러] {e}")
        return False

# 자동매매 실행

def execute_order(signal, price):
    global position

    side = "롱" if signal.startswith("롱") else "숏"
    qty = ENTRY_PERCENT  # 설정된 퍼센트 수량 사용

    if signal in ["롱 진입", "숏 진입"]:
        exchange_order("시장가", side, qty)
    elif "익절" in signal or "손절" in signal:
        exchange_order("시장가", side, qty)

    send_telegram(f"🚨 [자동매매 실행]\n신호: {signal}\n가격: {price}")

# 포지션 종료

def close_position(reason):
    global position, tp1_done, tp2_done
    if position:
        send_telegram(f"❗ 포지션 종료 ({position}) - 이유: {reason}")
        exchange_order("시장가", position, ENTRY_PERCENT)
        position = None
        tp1_done = False
        tp2_done = False

@app.route("/webhook", methods=["POST"])
def webhook():
    global position, tp1_done, tp2_done, bot_active

    if not bot_active:
        return jsonify({"status": "bot paused"}), 200

    data = request.json
    if not data:
        return jsonify({"status": "error", "message": "No data received"}), 400

    signal = data.get("signal")
    price = data.get("price")

    if not signal or not price:
        return jsonify({"status": "error", "message": "Invalid payload"}), 400

    try:
        if signal == "ping":
    send_telegram("✅ [PING] 서버 정상 작동 중입니다.")
    return jsonify({"status": "ping received"}), 200

        if signal == "go_long":
            if position == "short":
                close_position("반대 신호 (숏 → 롱)")
            position = "long"
            execute_order("롱 진입", price)

        elif signal == "go_short":
            if position == "long":
                close_position("반대 신호 (롱 → 숏)")
            position = "short"
            execute_order("숏 진입", price)

        elif signal == "tp1_hit_long" and position == "long" and not tp1_done:
            execute_order("롱 TP1 익절 (50%)", price)
            tp1_done = True

        elif signal == "tp2_hit_long" and position == "long" and tp1_done and not tp2_done:
            execute_order("롱 TP2 익절 (25%)", price)
            tp2_done = True

        elif signal == "tp3_hit_long" and position == "long":
            execute_order("롱 TP3 익절 (전량)", price)
            close_position("롱 TP3 완료")

        elif signal == "tp1_hit_short" and position == "short" and not tp1_done:
            execute_order("숏 TP1 익절 (50%)", price)
            tp1_done = True

        elif signal == "tp2_hit_short" and position == "short" and tp1_done and not tp2_done:
            execute_order("숏 TP2 익절 (25%)", price)
            tp2_done = True

        elif signal == "tp3_hit_short" and position == "short":
            execute_order("숏 TP3 익절 (전량)", price)
            close_position("숏 TP3 완료")

        elif signal == "sl_hit_long" and position == "long":
            execute_order("롱 SL 손절 (전량)", price)
            close_position("롱 SL 터치")

        elif signal == "sl_hit_short" and position == "short":
            execute_order("숏 SL 손절 (전량)", price)
            close_position("숏 SL 터치")

    except Exception as e:
        send_telegram(f"[시스템 에러] {e}")

    return jsonify({"status": "success"}), 200

# UI 페이지
@app.route("/")
def index():
    return render_template_string("""
        <h1>자동매매 봇 제어판</h1>
        <p>봇 상태: <b>{{'ON' if bot_active else 'OFF'}}</b></p>
        <form action="/toggle" method="post">
            <button type="submit">{{'정지하기' if bot_active else '시작하기'}}</button>
        </form>
        <h3>레버리지 / 진입 퍼센트 설정</h3>
        <form action="/settings" method="post">
            레버리지: <input type="number" name="leverage" value="{{leverage}}"><br>
            진입 퍼센트: <input type="number" name="entry_percent" value="{{entry_percent}}"><br>
            <button type="submit">적용</button>
        </form>
    """, bot_active=bot_active, leverage=LEVERAGE, entry_percent=ENTRY_PERCENT)

@app.route("/toggle", methods=["POST"])
def toggle():
    global bot_active
    bot_active = not bot_active
    return "<script>location.href='/'</script>"

@app.route("/settings", methods=["POST"])
def settings():
    global LEVERAGE, ENTRY_PERCENT
    LEVERAGE = int(request.form.get("leverage", 5))
    ENTRY_PERCENT = int(request.form.get("entry_percent", 10))
    return "<script>location.href='/'</script>"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
