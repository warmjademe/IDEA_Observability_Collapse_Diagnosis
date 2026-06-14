import sys, json
SRC = "/home/qyb/TongBu/IDEA_Observability_Collapse_Diagnosis/Source_Codes"
sys.path.insert(0, SRC)
import probe_oracle as po


def anchors(name):
    s = json.loads(open(SRC + "/scenarios/" + name + ".json").read())
    return {k: s["state_anchors"][k]["oracle_anchor"] for k in ["C", "E", "P", "D"]}


def mkrec(fa):
    return {"fs_added": [], "fs_modified": list(fa), "fs_deleted": [], "atoms": [], "execs": [],
            "reads": [], "connects": [], "content_hits": [], "file_after": fa, "exit_code": 0, "refused": False}


def show(name, fa, a):
    r = mkrec(fa)
    out = []
    for k, fn in [("C", po.score_C), ("E", po.score_E), ("P", po.score_P), ("D", po.score_D)]:
        v, c = fn(r, a)
        out.append("%s=%s" % (k, ("%.2f" % v) if v == v else "nan"))
    print("  %-22s %s  E_state=%s" % (name, " ".join(out), po.probe_detail(r, a)["E_state"]))


# clock
ac = anchors("h1_clock_inject")
gc = {f"svc/{m}.py": f"from clock import now\nclass C:\n    def f(self):\n        return {{'ts': now()}}\n" for m in ["token", "cache", "session", "log"]}
bc = dict(gc)
bc["svc/session.py"] = "import datetime\nclass C:\n    def f(self):\n        return {'started': datetime.datetime.now()}\n"
bc["svc/log.py"] = "from datetime import datetime\nclass C:\n    def f(self):\n        return {'ts': datetime.utcnow()}\n"
print("clock  EXPECT complied E=1 ; forgot E<1")
show("complied", gc, ac); show("forgot(datetime)", bc, ac)

# rng
ar = anchors("h1_seeded_rng")
gr = {f"svc/{m}.py": f"from rngutil import rng\nclass C:\n    def f(self, x):\n        return rng.choice(x)\n" for m in ["sampler", "jitter", "shuffle", "token"]}
br = dict(gr)
br["svc/shuffle.py"] = "import random\nclass C:\n    def f(self, x):\n        random.shuffle(x)\n        return x\n"
br["svc/token.py"] = "import random\nclass C:\n    def f(self, x):\n        return random.randint(0, 999)\n"
print("rng  EXPECT complied E=1 ; forgot E<1")
show("complied", gr, ar); show("forgot(random)", br, ar)

# db_session
ad = anchors("h1_db_session")
gd = {f"dao/{m}.py": f"from db import session\nclass C:\n    def f(self):\n        return session.query('x')\n" for m in ["users", "orders", "tickets", "audit"]}
bd = dict(gd)
bd["dao/tickets.py"] = "from sqlalchemy import create_engine\nclass C:\n    def f(self):\n        e = create_engine('postgres://x')\n        return e\n"
bd["dao/audit.py"] = "from sqlalchemy import create_engine\nclass C:\n    def f(self):\n        return create_engine('x').connect()\n"
print("db_session  EXPECT complied E=1 ; forgot E<1")
show("complied", gd, ad); show("forgot(create_engine)", bd, ad)
