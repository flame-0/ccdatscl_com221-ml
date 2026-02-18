import uiautomator2 as u2
import re
import csv
import time
import os

ORDER_REGEX = r"Order No\.: (\d+)"

def parse_currency(text):
    if not text: return 0.0
    clean = re.sub(r'[^\d.]', '', text)
    try: return float(clean)
    except: return 0.0

def main():
    d = u2.connect()
    processed_orders = set()
    file_path = 'joyride_history_dataset.csv'
    header = ['order_no', 'status', 'timestamp', 'dist', 'net', 'comm', 'pickup', 'dropoff']
    
    if os.path.isfile(file_path):
        with open(file_path, 'r', encoding='utf-8') as rf:
            reader = csv.DictReader(rf)
            for r in reader: 
                if r.get('order_no'): processed_orders.add(r['order_no'])

    with open(file_path, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f, quoting=csv.QUOTE_ALL) 
        if f.tell() == 0: writer.writerow(header)
        
        while True:
            time.sleep(2.0)
            all_elements = d.xpath('//*').all()
            
            anchors = []
            for el in all_elements:
                txt = el.info.get('text') or ""
                if re.search(ORDER_REGEX, txt):
                    anchors.append({
                        'id': re.search(ORDER_REGEX, txt).group(1),
                        'y': el.info['bounds']['top']
                    })
            
            anchors.sort(key=lambda x: x['y'])

            for i, anchor in enumerate(anchors):
                oid, oy = anchor['id'], anchor['y']
                if oid in processed_orders or oy < 200: continue

                # strict vertical fencing
                top_limit = oy - 180
                bottom_limit = anchors[i+1]['y'] - 20 if i+1 < len(anchors) else oy + 850
                
                row = {k: "" for k in header}
                row['order_no'] = oid
                row['dist'], row['net'], row['comm'] = 0.0, 0.0, 0.0
                
                is_completed, btn_coords = False, None

                # scrape card metadata
                for el in all_elements:
                    ey = el.info['bounds']['top']
                    if top_limit <= ey <= bottom_limit:
                        etxt = (el.info.get('text') or "").strip()
                        edsc = (el.info.get('contentDescription') or "").strip()

                        if ey < oy and "COMPLETED" in etxt.upper():
                            row['status'] = "COMPLETED"
                            is_completed = True
                        elif ey < oy and "CANCELLED" in etxt.upper():
                            row['status'] = etxt.upper()
                        
                        if ey >= oy:
                            if "Pickup Location" in edsc: row['pickup'] = etxt
                            elif "Destination Text" in edsc: row['dropoff'] = etxt
                            if any(m in etxt for m in ["Jan","Feb","Mar","202"]):
                                if "," in etxt: row['timestamp'] = etxt
                            elif edsc == "View Earnings Button":
                                btn_coords = el.center()

                # strict modal scrape (blocking)
                if is_completed and btn_coords:
                    d.click(btn_coords[0], btn_coords[1])
                    if d(resourceId="EarningsModalHeader").wait(timeout=3.0):
                        time.sleep(1.0) # UI settle
                        d.swipe(540, 1500, 540, 1100, duration=0.1)
                        
                        # blocking loop: wait for non-zero data
                        for attempt in range(20):
                            net_raw = d(resourceId="NetEarningsValue").get_text()
                            net_val = parse_currency(net_raw)
                            
                            if net_val > 0:
                                row['net'] = net_val
                                row['comm'] = parse_currency(d(resourceId="CommissionFromDriverValue").get_text())
                                dist_el = d(resourceId="WalletPaymentText") if d(resourceId="WalletPaymentText").exists else d(resourceId="ServiceModePromoDistanceText")
                                dm = re.search(r'([\d.]+) km', dist_el.get_text())
                                row['dist'] = float(dm.group(1)) if dm else 0.0
                                break
                            time.sleep(0.3)
                        
                        d(resourceId="CloseDriverEarnings").click()
                        d(resourceId="EarningsModalHeader").wait_gone(timeout=2.0)

                # double-check: don't save if completed but earnings are 0.0
                if row['status'] == "COMPLETED" and row['net'] == 0.0:
                    print(f"FAILED Verification: {oid} had 0.0 earnings. Skipping.")
                    continue

                if row['timestamp'] and row['pickup']:
                    writer.writerow([row[col] for col in header])
                    f.flush()
                    processed_orders.add(oid)
                    print(f"Successfully Verified: {oid} | {row['status']}")

            d.swipe(540, 1800, 540, 800, duration=0.5)

if __name__ == "__main__":
    main()