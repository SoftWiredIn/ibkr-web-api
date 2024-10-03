import requests
import time
import os
import json
from flask import Flask, render_template, request, redirect, url_for
from pprint import pprint
import traceback
from pyngrok import ngrok

# disable warnings until you install a certificate
from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

BASE_API_URL = "http://localhost:5055/v1/api"
ACCOUNT_ID = "DUA732142"
ALERT_TEMPLATE = '''{{
    "secret": "{secret}",
    "ticker": "{{{{ticker}}}}",
    "price": {{{{strategy.order.price}}}},
    "quantity": {{{{strategy.order.contracts}}}},
    "alert_message": "{{{{strategy.order.alert_message}}}}"
}}'''

WEBHOOK_URL_SET = False
WEBHOOK_URL = ''
try:
    if not WEBHOOK_URL_SET:
        public_url = ngrok.connect(5056)
        WEBHOOK_URL = f'{public_url.public_url}/tvwebhook'
        WEBHOOK_URL_SET = True

except:
    pass

os.environ['PYTHONHTTPSVERIFY'] = '0'

app = Flask(__name__)

SYMBOL_TO_CONTRACTID_MAP = {
    'GOOG': 208813720,
    'NIFTY': 51497778,
    'ADANIENT': 56986798,
    'AAPL': 265598,
    'NQ1!': 11004958,
    'NVDA': 4815747,
    'TSLA': 76792991,
    'BTCUSD': 509872400,
    'USDJPY': 15016059,
    'BTCUSD': 479624278,
}

session = requests.Session()
session.verify = False
session.get(f"{BASE_API_URL}")


@app.template_filter('ctime')
def timectime(s):
    return time.ctime(s/1000)


@app.route("/")
def dashboard():
    global ACCOUNT_ID
    try:
        r = session.get(f"{BASE_API_URL}/portfolio/accounts")
        accounts = r.json()
    except Exception as e:
        return 'Make sure you authenticate first then visit this page. <a href="http://localhost:5055">Log in</a>'

    account = accounts[0]

    ACCOUNT_ID = account_id = accounts[0]["id"]
    try:
        r = session.get(f"{BASE_API_URL}/portfolio/{account_id}/summary")
        summary = r.json()
    except Exception as e:
        summary = {'totalcashvalue': {'amount': 0}}

    message_template = ALERT_TEMPLATE.format(secret='784gfdgs2')

    return render_template("dashboard.html", account=account, summary=summary, account_id=account_id, webhook_url=WEBHOOK_URL, message_template=message_template)


@app.route("/lookup")
def lookup():
    symbol = request.args.get('symbol', None)
    stocks = []

    if symbol is not None:
        r = requests.get(
            f"{BASE_API_URL}/iserver/secdef/search?symbol={symbol}&name=true", verify=False)

        response = r.json()
        stocks = response

    return render_template("lookup.html", stocks=stocks)


@app.route("/contract/<contract_id>/<period>")
def contract(contract_id, period='5d', bar='1d'):
    data = {
        "conids": [
            contract_id
        ]
    }

    r = requests.post(f"{BASE_API_URL}/trsrv/secdef", data=data, verify=False)
    contract = r.json()['secdef'][0]

    r = requests.get(
        f"{BASE_API_URL}/iserver/marketdata/history?conid={contract_id}&period={period}&bar={bar}", verify=False)
    price_history = r.json()

    return render_template("contract.html", price_history=price_history, contract=contract)


@app.route("/orders")
def orders():
    r = requests.get(f"{BASE_API_URL}/iserver/account/orders", verify=False)
    # print(r.content)
    orders = r.json()["orders"]

    for order in orders:
        order['execTime'] = timectime(order['lastExecutionTime_r'])

    orders = sorted(orders, key=lambda order: order['execTime'], reverse=True)

    # place order code
    return render_template("orders.html", orders=orders)


@app.route("/order", methods=['POST'])
def place_order():
    data = {
        "orders": [
            {
                "conid": int(request.form.get('contract_id')),
                "orderType": "LMT",
                "price": float(request.form.get('price')),
                "quantity": int(request.form.get('quantity')),
                "side": request.form.get('side'),
                "tif": "GTC"
            }
        ]
    }

    r = requests.post(
        f"{BASE_API_URL}/iserver/account/{ACCOUNT_ID}/orders", json=data, verify=False)

    return redirect("/orders")


@app.route("/orders/<order_id>/cancel")
def cancel_order(order_id):
    cancel_url = f"{BASE_API_URL}/iserver/account/{ACCOUNT_ID}/order/{order_id}"
    r = requests.delete(cancel_url, verify=False)

    return r.json()


@app.route("/portfolio")
def portfolio():
    try:
        r = requests.get(
            f"{BASE_API_URL}/portfolio/{ACCOUNT_ID}/positions/0", verify=False)
        positions = r.json()
    except Exception as e:
        positions = []

    # return my positions, how much cash i have in this account
    return render_template("portfolio.html", positions=positions)


@app.route("/scanner")
def scanner():
    r = requests.get(f"{BASE_API_URL}/iserver/scanner/params", verify=False)
    params = r.json()

    scanner_map = {}
    filter_map = {}

    for item in params['instrument_list']:
        scanner_map[item['type']] = {
            "display_name": item['display_name'],
            "filters": item['filters'],
            "sorts": []
        }

    for item in params['filter_list']:
        filter_map[item['group']] = {
            "display_name": item['display_name'],
            "type": item['type'],
            "code": item['code']
        }

    for item in params['scan_type_list']:
        for instrument in item['instruments']:
            scanner_map[instrument]['sorts'].append({
                "name": item['display_name'],
                "code": item['code']
            })

    for item in params['location_tree']:
        scanner_map[item['type']]['locations'] = item['locations']

    submitted = request.args.get("submitted", "")
    selected_instrument = request.args.get("instrument", "")
    location = request.args.get("location", "")
    sort = request.args.get("sort", "")
    scan_results = []
    filter_code = request.args.get("filter", "")
    filter_value = request.args.get("filter_value", "")

    if submitted:
        print("submitting")
        data = {
            "instrument": selected_instrument,
            "location": location,
            "type": sort,
            "filter": [
                {
                    "code": filter_code,
                    "value": filter_value
                }
            ]
        }

        r = requests.post(
            f"{BASE_API_URL}/iserver/scanner/run", json=data, verify=False)
        scan_results = r.json()

    return render_template("scanner.html", params=params, scanner_map=scanner_map, filter_map=filter_map, scan_results=scan_results)


@app.route("/tvwebhook", methods=['GET', 'POST'])
def tvwebhook():
    try:
        data = json.loads(request.data)
        ticker = data.get('ticker')
        spot_price = data.get('price')
        qty = abs(data.get('quantity', 0))
        alert_message = data.get('alert_message')
        side = 'BUY' if 'entry' in alert_message else 'SELL'

        session = requests.Session()
        session.verify = False

        r = session.get(f"{BASE_API_URL}/portfolio/accounts")
        response = r.json()
        account_id = response[0]['id']

        contract_id = SYMBOL_TO_CONTRACTID_MAP.get(ticker, 208813720)
        data = {
            "orders": [
                {
                    "conid": contract_id,
                    "orderType": "MKT",
                    # "price": 20.00,
                    # "quantity": qty,
                    "side": side,
                    "tif": "IOC"
                }
            ]
        }

        if ticker in ['BTCUSD']:
            data["orders"][0]['cashQty'] = qty
        else:
            data["orders"][0]['quantity'] = qty

        r = session.post(
            f"{BASE_API_URL}/iserver/account/{account_id}/orders", json=data)
        pprint(r.json())

    except Exception as err:
        print(f"{err}")
        return f"{err}"

    return r.json()
