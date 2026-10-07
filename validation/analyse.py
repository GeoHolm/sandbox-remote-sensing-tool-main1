"""Score the soil-armor metrics against the UGA survey's tillage labels.

Every comparison is made WITHIN crop. Peanuts are dug at harvest, so peanut
fields in this survey are overwhelmingly conventional (133 of 188) and cotton
overwhelmingly conservation (144 of 208). Pooling the crops would show a strong
"tillage signal" that is really a crop signal.
"""
import sys
import numpy as np
import pandas as pd


def auc(pos, neg):
    """Mann-Whitney AUC: P(a random positive scores above a random negative)."""
    pos, neg = np.asarray(pos, float), np.asarray(neg, float)
    pos, neg = pos[~np.isnan(pos)], neg[~np.isnan(neg)]
    if len(pos) < 3 or len(neg) < 3:
        return np.nan, len(pos), len(neg)
    allv = np.concatenate([pos, neg])
    r = pd.Series(allv).rank().to_numpy()
    a = (r[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))
    return a, len(pos), len(neg)


def main(metrics_csv="validation/pilot_metrics.csv", truth_csv="validation/pilot.csv"):
    m = pd.read_csv(metrics_csv)
    t = pd.read_csv(truth_csv)
    d = t.merge(m, on="key")
    d = d[d.n_obs > 0]
    print(f"scored {len(d)} of {len(t)} field-years "
          f"(median {d.n_obs.median():.0f} clear dates each)\n")

    CONS, CONV = "> 30%", "< 15%"
    METRICS = [("f_npv", "residue fraction", 1),
               ("armor", "soil armor (1-f_bs)", 1),
               ("f_bs", "bare soil fraction", -1),
               ("min_ndti", "min NDTI (old metric)", 1),
               ("med_ndti", "median NDTI", 1)]

    print("=== AUC for conservation (>30% residue) vs conventional (<15%) ===")
    print("    1.00 = perfect separation, 0.50 = no signal\n")
    rows = []
    for crop in list(d["crop"].unique()) + ["BOTH (confounded)"]:
        sub = d if crop.startswith("BOTH") else d[d["crop"] == crop]
        for col, lab, sign in METRICS:
            a, npos, nneg = auc(sign * sub.loc[sub.till == CONS, col],
                                sign * sub.loc[sub.till == CONV, col])
            rows.append({"crop": crop, "metric": lab, "AUC": a,
                         "n_cons": npos, "n_conv": nneg})
    r = pd.DataFrame(rows).pivot(index="metric", columns="crop", values="AUC")
    print(r.round(3).to_string())

    print("\n=== group medians ===")
    g = (d.groupby(["crop", "till"])[["f_npv", "armor", "f_bs", "min_ndti", "ndvi_med"]]
         .median().round(3))
    print(g.to_string())
    print("\n=== n per cell ===")
    print(pd.crosstab(d["crop"], d.till).to_string())


if __name__ == "__main__":
    main(*sys.argv[1:])
