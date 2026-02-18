#!/usr/bin/env python3
"""
Amplify 2026 Dashboard Updater
--------------------------------
Pulls live data from Streak and regenerates data.js for the dashboard.

Usage:  python3 update.py
Needs:  pip3 install requests
"""

import os, re, json, subprocess, sys, requests
from datetime import datetime, timedelta
from collections import defaultdict

# ── Config ─────────────────────────────────────────────────────────
API_KEY      = os.environ.get("STREAK_API_KEY", "strk_2lafc8Wr8YLM7VE64qJUkmGL4USh")
PIPELINE_KEY = "agxzfm1haWxmb29nYWVyNQsSDE9yZ2FuaXphdGlvbiIOZm9yYXRyYXZlbC5jb20MCxIIV29ya2Zsb3cYgIDFtcWIugoM"
BASE_URL     = "https://api.streak.com/api/v1"
AUTH         = (API_KEY, "")

# ── Stage keys ─────────────────────────────────────────────────────
SIGNED_STAGES = {
    "5014": "Tier 1",
    "5015": "Tier 2",
    "5016": "Brand Spotlight",
    "5017": "New Opening",
    "5007": "Marketing Complete",
}
PIPELINE_STAGES = {
    "5011": "Needs Invoice",
    "5004": "In Discussion",
    "5001": "Final Follow Up",
}
ALL_STAGE_NAMES = {
    **SIGNED_STAGES,
    **PIPELINE_STAGES,
    "5013": "Needs Contact",
    "5010": "Needs Review",
    "5008": "Declined",
    "5009": "Do Not Invite",
    "5002": "Invited",
    "5018": "2027 Lead",
}

# ── Field keys ─────────────────────────────────────────────────────
F_PRICE       = "1024"
F_INVOICE     = "1037"
F_INVOICE_URL = "1035"
F_COUNTRY     = "1051"
F_BRAND       = "1033"
F_GROUP       = "1034"
F_QUARTER     = "1053"
F_EMAIL       = "1050"
F_INVOICE_DATE= "1036"

FEATURE_FIELDS = {
    "Collection":     "1067",
    "Forum":          "1066",
    "Newsletter":     "1063",
    "Advisor Assets": "1070",
    "Journal Article":"1074",
    "Social Media":   "1075",
    "Webinar":        "1073",
}

# ── Dropdown/tag lookups ────────────────────────────────────────────
INVOICE_LABELS = {
    "9001": "Outstanding",
    "9002": "Paid",
    "9003": "To Invoice",
    "9004": "Waiting for billing details",
    "9005": "In Kind Sponsorship",
    "9006": "Invoice held",
}
QUARTER_LABELS = {
    "9001": "Q1", "9002": "Q2", "9003": "Q3", "9004": "Q4", "9005": "August"
}
COLLECTION_NA = "9025"  # "N/A" tag key for Collection field

# ── Fetch dropdown labels for feature fields ────────────────────
def fetch_field_labels():
    """Return {field_key: {option_key: label}} for all feature fields."""
    r = requests.get(f"{BASE_URL}/pipelines/{PIPELINE_KEY}", auth=AUTH)
    if r.status_code != 200:
        print(f"  Warning: could not fetch pipeline metadata ({r.status_code})")
        return {}
    data = r.json()
    labels = {}
    feature_keys = set(FEATURE_FIELDS.values())
    for field in data.get("fields", []):
        fkey  = str(field.get("key", ""))
        ftype = field.get("type", "")
        if fkey not in feature_keys:
            continue
        if ftype == "TAG":
            # Tags store options as tagSettings.tags[].tag
            tags = (field.get("tagSettings") or {}).get("tags", [])
            if tags:
                labels[fkey] = {str(t.get("key", "")): t.get("tag", "") for t in tags}
        elif ftype == "DROPDOWN":
            # Dropdowns store options as dropdownSettings.items[].name
            items = (field.get("dropdownSettings") or {}).get("items", [])
            if items:
                labels[fkey] = {str(i.get("key", "")): i.get("name", "") for i in items}
        # DATE type (Webinar) has no discrete options — handled at read time
    print(f"  Loaded label mappings for {len(labels)} feature field(s)")
    return labels

# ── Helpers ────────────────────────────────────────────────────────
def fetch_all_boxes():
    boxes, page = [], 0
    print("Fetching boxes from Streak", end="", flush=True)
    while True:
        r = requests.get(f"{BASE_URL}/pipelines/{PIPELINE_KEY}/boxes",
                         auth=AUTH, params={"limit": 500, "page": page})
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        boxes.extend(batch)
        print(".", end="", flush=True)
        if len(batch) < 500:
            break
        page += 1
    print(f" {len(boxes)} boxes total")
    return boxes

def price(box):
    val = box.get("fields", {}).get(F_PRICE)
    if val is None:
        return 0
    try:
        return float(str(val).replace(",", "").replace("$", "").strip())
    except:
        return 0

def field_val(box, key):
    return box.get("fields", {}).get(key)

def is_set(box, key, exclude_keys=None):
    val = field_val(box, key)
    if val is None:
        return False
    if isinstance(val, list):
        items = [str(v) for v in val]
        if exclude_keys:
            items = [v for v in items if v not in exclude_keys]
        return len(items) > 0
    if isinstance(val, (int, float)):
        return True
    return str(val).strip() != ""

def top_n(counter, n=10):
    return sorted(counter.items(), key=lambda x: -x[1])[:n]

def get_quarters(box):
    qval = field_val(box, F_QUARTER)
    if not qval:
        return []
    keys = qval if isinstance(qval, list) else [qval]
    return [QUARTER_LABELS.get(str(k), str(k)) for k in keys]

def get_features(box, field_labels=None):
    field_labels = field_labels or {}
    result = []
    for fname, fkey in FEATURE_FIELDS.items():
        excl = {COLLECTION_NA} if fkey == "1067" else None
        if is_set(box, fkey, excl):
            val    = field_val(box, fkey)
            labels = field_labels.get(fkey, {})

            if labels:
                # TAG or DROPDOWN field — decode numeric key(s) to human label
                if isinstance(val, list):
                    items  = [str(v) for v in val if str(v) not in (excl or set())]
                    timing = ", ".join(labels.get(v, v) for v in items)
                else:
                    raw    = str(val).strip() if val else ""
                    timing = labels.get(raw, raw)
            elif isinstance(val, (int, float)) and val > 1_000_000_000_000:
                # DATE field (Unix ms timestamp, e.g. Webinar) — format as "Month YYYY"
                try:
                    timing = datetime.fromtimestamp(val / 1000).strftime("%B %Y")
                except Exception:
                    timing = str(val)
            else:
                # Plain text or unknown
                if isinstance(val, list):
                    items  = [str(v) for v in val if str(v) not in (excl or set())]
                    timing = ", ".join(items)
                else:
                    timing = str(val).strip() if val else ""

            result.append({"name": fname, "timing": timing})
    return result

# ── Main ───────────────────────────────────────────────────────────
def compute_metrics(boxes):
    field_labels = fetch_field_labels()
    signed_val   = defaultdict(float)
    signed_cnt   = defaultdict(int)
    pipeline_val = defaultdict(float)
    pipeline_cnt = defaultdict(int)
    other_cnt    = defaultdict(int)

    paid = outstanding = waiting = in_kind = 0

    features  = defaultdict(int)
    quarters  = defaultdict(int)
    countries = defaultdict(int)
    brands    = defaultdict(int)
    groups    = defaultdict(int)
    signed_by_month = defaultdict(lambda: {"count": 0, "value": 0})
    new_this_week   = []
    week_ago        = datetime.now() - timedelta(days=7)

    partners = []

    for box in boxes:
        stage = str(box.get("stageKey", ""))
        p     = price(box)
        inv   = str(field_val(box, F_INVOICE) or "")

        if stage in SIGNED_STAGES:
            label = SIGNED_STAGES[stage]
            signed_val[label] += p
            signed_cnt[label] += 1
            # Determine signed date: Invoice Date field from Streak (most accurate),
            # falling back to lastStageChangeDate / creationTimestamp.
            sign_dt = None
            inv_date_val = field_val(box, F_INVOICE_DATE)
            if inv_date_val:
                try:
                    # Streak DATE fields are Unix ms timestamps
                    sign_dt = datetime.fromtimestamp(int(inv_date_val) / 1000)
                except Exception:
                    pass
            if not sign_dt:
                ts = box.get("lastStageChangeDate") or box.get("creationTimestamp")
                if ts:
                    try:
                        sign_dt = datetime.fromtimestamp(ts / 1000)
                    except Exception:
                        pass
            if sign_dt:
                mk = sign_dt.strftime("%Y-%m")
                signed_by_month[mk]["count"] += 1
                signed_by_month[mk]["value"] += int(p)
                if sign_dt >= week_ago:
                    new_this_week.append({
                        "name":  box.get("name", ""),
                        "stage": SIGNED_STAGES[stage],
                        "price": int(p),
                    })
        elif stage in PIPELINE_STAGES:
            label = PIPELINE_STAGES[stage]
            pipeline_val[label] += p
            pipeline_cnt[label] += 1
        else:
            other_cnt[stage] += 1

        # Invoice status (all non-invited boxes)
        if stage != "5002":
            if   inv == "9002": paid        += p
            elif inv == "9001": outstanding += p
            elif inv == "9004": waiting     += p
            elif inv == "9005": in_kind     += p

        # Features + geography (signed only)
        if stage in SIGNED_STAGES:
            for fname, fkey in FEATURE_FIELDS.items():
                excl = {COLLECTION_NA} if fkey == "1067" else None
                if is_set(box, fkey, excl):
                    features[fname] += 1

            for q in get_quarters(box):
                quarters[q] += 1
            if not get_quarters(box):
                quarters["TBD"] += 1

            c = field_val(box, F_COUNTRY)
            b = field_val(box, F_BRAND)
            g = field_val(box, F_GROUP)
            if c and str(c).strip(): countries[str(c).strip()] += 1
            if b and str(b).strip(): brands[str(b).strip()]    += 1
            if g and str(g).strip(): groups[str(g).strip()]    += 1

        # Build per-partner record (skip Invited and 2027 Lead)
        if stage not in ("5002", "5018"):
            inv_url = field_val(box, F_INVOICE_URL)
            partners.append({
                "key":           box.get("key", ""),
                "name":          box.get("name", ""),
                "stage":         ALL_STAGE_NAMES.get(stage, stage),
                "stageKey":      stage,
                "price":         int(p),
                "invoiceStatus": INVOICE_LABELS.get(inv, ""),
                "invoiceUrl":    str(inv_url).strip() if inv_url and str(inv_url).startswith("http") else "",
                "features":      get_features(box, field_labels),
                "quarters":      get_quarters(box),
                "country":       str(field_val(box, F_COUNTRY) or "").strip(),
                "brand":         str(field_val(box, F_BRAND) or "").strip(),
                "group":         str(field_val(box, F_GROUP) or "").strip(),
                "email":         str(field_val(box, F_EMAIL) or "").strip(),
                "streakUrl":     f"https://app.streak.com/pipelines/{PIPELINE_KEY}/boxes/{box.get('key', '')}",
            })

    total_signed   = sum(signed_val.values())
    total_pipeline = total_signed + sum(pipeline_val.values())
    signed_count   = sum(signed_cnt.values())

    # Build funnel
    funnel = []
    signed_order = [
        ("5014", "Tier 1"),
        ("5016", "Brand Spotlight"),
        ("5015", "Tier 2"),
        ("5017", "New Opening"),
        ("5007", "Marketing Complete"),
    ]
    for sk, lbl in signed_order:
        funnel.append({
            "label": f"Signed — {lbl}",
            "stageKey": sk,
            "count": signed_cnt.get(lbl, 0),
            "value": int(signed_val.get(lbl, 0)),
        })

    for sk, label in [("5011","Needs Invoice"),("5004","In Discussion"),("5001","Final Follow Up")]:
        funnel.append({
            "label":    label,
            "stageKey": sk,
            "count":    pipeline_cnt.get(label, 0),
            "value":    int(pipeline_val.get(label, 0)),
        })

    for sk, label in [("5013","Needs Contact"),("5010","Needs Review"),("5008","Declined"),("5009","Do Not Invite")]:
        cnt = other_cnt.get(sk, 0)
        if cnt:
            funnel.append({"label": label, "stageKey": sk, "count": cnt, "value": 0})

    # Sort partners for output (signed first, then pipeline, then others, alphabetical within group)
    stage_order_key = {**{k: 0 for k in SIGNED_STAGES}, **{k: 1 for k in PIPELINE_STAGES}}
    partners.sort(key=lambda p: (stage_order_key.get(p["stageKey"], 2), p["name"]))

    # Build signed-over-time series (sorted chronologically, with cumulative totals)
    sorted_months = sorted(signed_by_month.keys())
    cum_count = cum_value = 0
    signed_over_time = []
    for mk in sorted_months:
        cum_count += signed_by_month[mk]["count"]
        cum_value += signed_by_month[mk]["value"]
        dt = datetime.strptime(mk, "%Y-%m")
        signed_over_time.append({
            "month":    dt.strftime("%b %Y"),
            "count":    signed_by_month[mk]["count"],
            "value":    signed_by_month[mk]["value"],
            "cumCount": cum_count,
            "cumValue": cum_value,
        })

    return {
        "lastUpdated":      datetime.now().strftime("%b %d, %Y"),
        "signedCount":      signed_count,
        "totalSigned":      int(total_signed),
        "totalPipeline":    int(total_pipeline),
        "paid":             int(paid),
        "outstanding":      int(outstanding),
        "waitingBilling":   int(waiting),
        "inKind":           int(in_kind),
        "needsInvoice":     int(pipeline_val.get("Needs Invoice", 0)),
        "needsInvoiceCount":pipeline_cnt.get("Needs Invoice", 0),
        "inDiscussion":     int(pipeline_val.get("In Discussion", 0)),
        "inDiscussionCount":pipeline_cnt.get("In Discussion", 0),
        "finalFollowUp":    int(pipeline_val.get("Final Follow Up", 0)),
        "finalFollowUpCount":pipeline_cnt.get("Final Follow Up", 0),
        "marketingComplete":int(signed_val.get("Marketing Complete", 0)),
        "byStage":          {k: int(v) for k, v in signed_val.items()},
        "countByStage":     dict(signed_cnt),
        "pipelineByStage":  {k: int(v) for k, v in pipeline_val.items()},
        "pipelineCountByStage": dict(pipeline_cnt),
        "funnel":           funnel,
        "signedOverTime":   signed_over_time,
        "newThisWeek":      sorted(new_this_week, key=lambda x: -x["price"]),
        "features":         dict(features),
        "quarters":         dict(quarters),
        "topCountries":     top_n(countries),
        "topGroups":        top_n(groups),
        "topBrands":        top_n(brands),
        "partners":         partners,
    }

def print_summary(d):
    print(f"\n{'='*50}")
    print(f"  Signed Partners:   {d['signedCount']}")
    print(f"  Total Signed:      ${d['totalSigned']:>10,.0f}")
    print(f"  Total Pipeline:    ${d['totalPipeline']:>10,.0f}")
    print(f"  Paid:              ${d['paid']:>10,.0f}")
    print(f"  Outstanding:       ${d['outstanding']:>10,.0f}")
    print(f"  Waiting Billing:   ${d['waitingBilling']:>10,.0f}")
    print(f"  Needs Invoice:     ${d['needsInvoice']:>10,.0f}")
    print(f"  In Discussion:     ${d['inDiscussion']:>10,.0f}")
    print(f"\n  By Stage:")
    for k, v in d['byStage'].items():
        print(f"    {k:<25} ${v:>8,.0f}  ({d['countByStage'].get(k,0)} partners)")
    print(f"\n  Features: {d['features']}")
    print(f"  Quarters: {d['quarters']}")
    print(f"  Partners array: {len(d['partners'])} records")
    print(f"{'='*50}\n")

if __name__ == "__main__":
    no_git = "--no-git" in sys.argv

    boxes  = fetch_all_boxes()
    data   = compute_metrics(boxes)
    print_summary(data)

    # Write data.js
    script_dir   = os.path.dirname(os.path.abspath(__file__))
    data_js_path = os.path.join(script_dir, "data.js")
    with open(data_js_path, "w") as f:
        f.write(f"// Auto-generated by update.py on {data['lastUpdated']}\n")
        f.write("// Do not edit manually — run: python3 update.py\n\n")
        f.write(f"const AMPLIFY_DATA = {json.dumps(data, indent=2)};\n")
    print(f"Wrote data.js ({os.path.getsize(data_js_path)//1024}KB)")

    # Update cache-bust version in index.html so browsers always load fresh data.js
    index_path = os.path.join(script_dir, "index.html")
    version    = datetime.now().strftime("%Y%m%d%H%M")
    with open(index_path, "r") as f:
        html = f.read()
    html = re.sub(r'data\.js\?v=\d+', f'data.js?v={version}', html)
    with open(index_path, "w") as f:
        f.write(html)
    print(f"Updated cache-bust version in index.html → v={version}")

    if no_git:
        print("Skipping git (--no-git mode, handled externally)")
        sys.exit(0)

    # Git commit + push
    os.chdir(script_dir)
    subprocess.run(["git", "add", "data.js", "index.html"], check=True)
    result = subprocess.run(
        ["git", "commit", "-m", f"Auto-update from Streak ({data['lastUpdated']})"],
        capture_output=True, text=True
    )
    if "nothing to commit" in result.stdout:
        print("No changes to push — data is already up to date.")
    else:
        subprocess.run(["git", "push"], check=True)
        print("Pushed! Dashboard updates at https://margaux-noel.github.io/amplify-2026-dashboard/ in ~1 min.")
