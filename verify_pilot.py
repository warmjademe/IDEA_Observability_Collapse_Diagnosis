import json, glob
from collections import defaultdict, Counter
D = "/home/qyb/TongBu/IDEA_Observability_Collapse_Diagnosis/Source_Codes/results/diff"
runs = [json.load(open(p)) for p in glob.glob(D + "/*.json") if "diff_report" not in p]
print("total runs:", len(runs))
print("read_rule TRUE:", sum(1 for r in runs if r.get("read_rule")), "/", len(runs))
print("valid:", sum(1 for r in runs if r.get("valid") == "valid"), "/", len(runs))
agg = defaultdict(lambda: defaultdict(list))
for r in runs:
    k = r.get("cond")
    agg[k]["E"].append(r.get("E_state"))
    agg[k]["nf"].append(r.get("n_files_changed"))
    agg[k]["nev"].append(r.get("n_events"))
    agg[k]["exit"].append(r.get("exit"))
for k in sorted(agg):
    es = dict(Counter(agg[k]["E"]))
    nf = agg[k]["nf"]; nev = agg[k]["nev"]; ex = dict(Counter(agg[k]["exit"]))
    line = "%-16s E=%s nfiles=%s..%s nevents=%s..%s exits=%s" % (
        k, es, min(nf), max(nf), min(nev), max(nev), ex)
    print(line)
print("wrong (forgot) total:", sum(1 for r in runs if r.get("E_state") == "wrong"))
