#!/usr/bin/env python3
"""Adapter for the esim sample: testdata/*.txt (pipe-delimited, body_tag 02) -> seed CSV for the landing table.
Job-specific on purpose - every job has its own landing layout, write one small adapter per job (appendix J, step 2).
usage: make_landing_seed.py <testdata folder> <out folder>
Only rows with body_tag '02' are streamed into the landing table by Blendata (header 01 / trailer 99 / junk are not) -
this matches expected_results.csv of the esim testdata (expected_streamed = Y).
"""
import csv, sys, os
td, out = sys.argv[1], sys.argv[2]
FILES = {"r1": [("PGZ_ESIM_INVENTORY1_20260827_100000_1.txt", 202608271000), ("PGZ_ESIM_INVENTORY1_20260827_101000_2.txt", 202608271010),
                ("PGZ_ESIM_INVENTORY1_20260827_102000_3.txt", 202608271020), ("PGZ_ESIM_INVENTORY1_20260827_103000.txt", 202608271030)],
         "r2": [("PGZ_ESIM_INVENTORY1_20260827_110000_4.txt", 202608271100)]}
HDR = "body_tag,partner,owner,iccid,first_installed,profile_type,eid,sim_type,raw_data,number_of_cols,process_date,input_source_name,partition_date,partition_hour,partition_minute".split(",")
NUL = "\\N"
for rnd, files in FILES.items():
    with open(os.path.join(out, "landing_%s.csv" % rnd), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(HDR)
        for fn, pm in files:
            for line in open(os.path.join(td, fn), encoding="utf-8").read().split("\n"):
                p = line.split("|")
                if p[0] != "02": continue
                cols = p[1:8] + [NUL] * (7 - len(p[1:8]))      # short row: missing fields are NULL
                w.writerow(["02"] + cols + [line, len(p), "2026-08-27 %02d:31:00" % (pm % 10000 // 100),
                           "viewfs://ClusterBDE/bdedatastore/zeus_stg/imports/ss_esim/" + fn, 20260827, pm // 100, pm])
print("ok")
