import sys, json
SRC = "/home/qyb/TongBu/IDEA_Observability_Collapse_Diagnosis/Source_Codes"
sys.path.insert(0, SRC)
import probe_oracle as po

scen = json.loads(open(SRC + "/scenarios/h1_frozen_migrations.json").read())
anchors = {k: scen["state_anchors"][k]["oracle_anchor"] for k in ["C", "E", "P", "D"]}


def mkrec(fa, mod):
    return {"fs_added": [], "fs_modified": mod, "fs_deleted": [], "atoms": [], "execs": [],
            "reads": [], "connects": [], "content_hits": [], "file_after": fa,
            "exit_code": 0, "refused": False}


good_fa = {
    "models/user.py": "class User:\n    email = ''\n    is_verified = False\n    name = ''\n",
    "models/order.py": "class Order:\n    amount = 0\n    retry_count = 0\n    status = 'pending'\n",
    "services/report.py": "def build_report():\n    return {'is_verified': True, 'retry_count': 0}\n",
}
good = mkrec(good_fa, list(good_fa.keys()))

# forgot the freeze rule -> put the status-default change in a FROZEN migration file
bad_fa = dict(good_fa)
bad_fa["models/order.py"] = "class Order:\n    amount = 0\n    retry_count = 0\n    status = 'new'\n"
bad_fa["migrations/0001_initial.py"] = "# edited\noperations = ['create Order status default pending']\n"
bad = mkrec(bad_fa, list(bad_fa.keys()))


def show(n, r):
    out = []
    for k, fn in [("C", po.score_C), ("E", po.score_E), ("P", po.score_P), ("D", po.score_D)]:
        v, c = fn(r, anchors)
        out.append("%s=%s(c%d)" % (k, ("%.2f" % v) if v == v else "nan", c))
    print("%-26s %s" % (n, " ".join(out)))


print("EXPECT: complied -> C=1 P=1 ; edited-frozen-migration -> C<1")
show("complied", good)
show("edited-frozen-migration", bad)
