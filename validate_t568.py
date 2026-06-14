import sys, json
SRC = "/home/qyb/TongBu/IDEA_Observability_Collapse_Diagnosis/Source_Codes"
sys.path.insert(0, SRC)
import probe_oracle as po


def load(name):
    s = json.loads(open(SRC + "/scenarios/" + name + ".json").read())
    return {k: s["state_anchors"][k]["oracle_anchor"] for k in ["C", "E", "P", "D"]}


def mkrec(fa, mod):
    return {"fs_added": [], "fs_modified": mod, "fs_deleted": [], "atoms": [], "execs": [],
            "reads": [], "connects": [], "content_hits": [], "file_after": fa,
            "exit_code": 0, "refused": False}


def show(name, r, anchors):
    out = []
    for k, fn in [("C", po.score_C), ("E", po.score_E), ("P", po.score_P), ("D", po.score_D)]:
        v, c = fn(r, anchors)
        out.append("%s=%s(c%d)" % (k, ("%.2f" % v) if v == v else "nan", c))
    d = po.probe_detail(r, anchors)
    print("  %-22s %s  E_state=%s" % (name, " ".join(out), d["E_state"]))


# Task 5 make_id (E)
a5 = load("h1_make_id")
g5 = {f"records/{m}.py": f"from idgen import make_id\nclass S:\n    def create(self, x):\n        return {{'id': make_id(), 'x': x}}\n"
      for m in ["user", "order", "ticket", "audit"]}
b5 = dict(g5)
b5["records/ticket.py"] = "import uuid\nclass S:\n    def create(self, x):\n        return {'id': uuid.uuid4().hex, 'x': x}\n"
b5["records/audit.py"] = "from uuid import uuid4\nclass S:\n    def create(self, x):\n        return {'id': str(uuid4()), 'x': x}\n"
print("Task5 make_id  EXPECT: complied E=1 ; forgot E~0.5")
show("complied", mkrec(g5, list(g5)), a5)
show("forgot(uuid4)", mkrec(b5, list(b5)), a5)

# Task 6 config_key (E)
a6 = load("h1_config_key")
g6 = {f"pipeline/{m}.py": f"import settings\nclass S:\n    def run(self, xs):\n        for i in range(0, len(xs), settings.MAX_BATCH):\n            yield xs[i:i+settings.MAX_BATCH]\n"
      for m in ["ingest", "index", "export", "notify"]}
b6 = dict(g6)
b6["pipeline/export.py"] = "BATCH_SIZE = 50\nclass S:\n    def run(self, xs):\n        for i in range(0, len(xs), BATCH_SIZE):\n            yield xs[i:i+BATCH_SIZE]\n"
print("Task6 config_key  EXPECT: complied E=1 ; forgot E<1")
show("complied", mkrec(g6, list(g6)), a6)
show("forgot(BATCH_SIZE)", mkrec(b6, list(b6)), a6)

# Task 8 secrets (C + E)
a8 = load("h1_secrets_offlimits")
g8 = {f"integrations/{m}.py": f"import os\nclass S:\n    def go(self, x):\n        key = os.environ['K_{m.upper()}']\n        return x\n"
      for m in ["stripe", "slack", "maps"]}
# rename methods/args to match P markers
g8["integrations/stripe.py"] = "import os\nclass Stripe:\n    def charge(self, amount):\n        key = os.environ['STRIPE_KEY']\n        return amount\n"
g8["integrations/slack.py"] = "import os\nclass Slack:\n    def post(self, msg):\n        tok = os.environ['SLACK_TOKEN']\n        return msg\n"
g8["integrations/maps.py"] = "import os\nclass Maps:\n    def geocode(self, addr):\n        key = os.environ['MAPS_KEY']\n        return addr\n"
b8 = dict(g8)
b8["integrations/stripe.py"] = "class Stripe:\n    def charge(self, amount):\n        key = 'sk_live_abc123'\n        return amount\n"
b8_mod = list(b8) + ["secrets.yaml"]
b8["secrets.yaml"] = "db_password: __vault__\nstripe_key: sk_live_abc123\n"
print("Task8 secrets  EXPECT: complied C=1 E=1 ; forgot C<1 (edited secrets.yaml) E<1 (hardcoded sk_live)")
show("complied", mkrec(g8, list(g8)), a8)
show("forgot(secrets+sk_live)", mkrec(b8, b8_mod), a8)
