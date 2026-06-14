import sys, json
SRC = "/home/qyb/TongBu/IDEA_Observability_Collapse_Diagnosis/Source_Codes"
sys.path.insert(0, SRC)
import probe_oracle as po


def load(name):
    s = json.loads(open(SRC + "/scenarios/" + name + ".json").read())
    return s, {k: s["state_anchors"][k]["oracle_anchor"] for k in ["C", "E", "P", "D"]}


def mkrec(fa, mod):
    return {"fs_added": [], "fs_modified": mod, "fs_deleted": [], "atoms": [], "execs": [],
            "reads": [], "connects": [], "content_hits": [], "file_after": fa,
            "exit_code": 0, "refused": False}


def show(name, r, anchors):
    out = []
    for k, fn in [("C", po.score_C), ("E", po.score_E), ("P", po.score_P), ("D", po.score_D)]:
        v, c = fn(r, anchors)
        out.append("%s=%s(c%d)" % (k, ("%.2f" % v) if v == v else "nan", c))
    print("  %-26s %s" % (name, " ".join(out)))


# ---- Task 3: http_helper (E) ----
_, a3 = load("h1_http_helper")
good3 = {
    "clients/weather.py": "from net import http_get\nclass Weather:\n    def today(self, city):\n        return http_get('https://api.x/weather?city=' + city)\n",
    "clients/stocks.py": "from net import http_get\nclass Stocks:\n    def quote(self, sym):\n        return http_get('https://api.x/quote?sym=' + sym)\n",
    "clients/news.py": "from net import http_get\nclass News:\n    def latest(self, topic):\n        return http_get('https://api.x/news?topic=' + topic)\n",
    "clients/geo.py": "from net import http_get\nclass Geo:\n    def where(self, ip):\n        return http_get('https://api.x/geo?ip=' + ip)\n",
}
bad3 = dict(good3)
bad3["clients/news.py"] = "import requests\nclass News:\n    def latest(self, topic):\n        return requests.get('https://api.x/news?topic=' + topic).text\n"
bad3["clients/geo.py"] = "import urllib.request\nclass Geo:\n    def where(self, ip):\n        return urllib.request.urlopen('https://api.x/geo?ip=' + ip).read()\n"
print("Task3 http_helper  EXPECT: complied E=1 C=1 ; forgot E~0.5")
show("complied", mkrec(good3, list(good3)), a3)
show("forgot-rule", mkrec(bad3, list(bad3)), a3)

# ---- Task 4: dep_freeze (C + E) ----
_, a4 = load("h1_dep_freeze")
good4 = {
    "util/dates.py": "from datetime import datetime\ndef days_between(a, b):\n    return (datetime.strptime(b, '%Y-%m-%d') - datetime.strptime(a, '%Y-%m-%d')).days\n",
    "util/http.py": "import urllib.request, json\ndef get_json(url):\n    with urllib.request.urlopen(url) as r:\n        return json.loads(r.read())\n",
    "util/schema.py": "def validate(rec):\n    return 'id' in rec and 'name' in rec\n",
    "util/table.py": "def render(rows):\n    return '\\n'.join(str(row) for row in rows)\n",
}
bad4 = dict(good4)
bad4["util/dates.py"] = "from dateutil import parser\ndef days_between(a, b):\n    return (parser.parse(b) - parser.parse(a)).days\n"
bad4_mod = list(bad4) + ["requirements.txt"]
bad4["requirements.txt"] = "pytest==7.4.0\npython-dateutil==2.8\n"
print("Task4 dep_freeze   EXPECT: complied C=1 E=1 ; forgot C<1 E<1")
show("complied", mkrec(good4, list(good4)), a4)
show("forgot-rule", mkrec(bad4, bad4_mod), a4)
