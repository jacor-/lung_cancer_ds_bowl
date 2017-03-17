# Read .csv containing detected nodules on LUNA and compute
#   confusion matrix for it

import pandas as pd
import numpy as np
import os
from math import ceil
from dl_utils.heatmap import extract_regions_from_heatmap
from sklearn import metrics
import matplotlib.pyplot as plt


## PATHS AND FILES
wp = os.environ['LUNG_PATH']
DATA_PATH = '/mnt/hd2/preprocessed5/'  # DATA_PATH = wp + 'data/preprocessed5_sample/'
NODULES_FILE = "/home/mingot/output/noduls_patches_v05_backup3.csv"  # NODULES_FILE = wp + 'personal/noduls_patches_v04_dsb.csv'
df_node = pd.read_csv(NODULES_FILE, skiprows=[1977535])  # TODO: remove the skipeed row
file_list = [g for g in os.listdir(DATA_PATH) if g.startswith('luna_')]
filenames_scored_full = set(df_node['filename'])

## Filter nodules
SCORE_THRESHOLD = 0.8
# df_node = df_node[df_node['score']>SCORE_THRESHOLD]
filenames_scored = set(df_node['filename'])

## Auxiliar functions
class AuxRegion():
    def __init__(self, dim):
        self.bbox = dim

def intersection_regions(r1, r2):
    h = min(r1.bbox[2], r2.bbox[2]) - max(r1.bbox[0], r2.bbox[0])
    w = min(r1.bbox[3], r2.bbox[3]) - max(r1.bbox[1], r2.bbox[1])
    intersectionArea = w*h
    if h<0 or w<0:
        return 0.0

    area1 = (r1.bbox[2] - r1.bbox[0])*(r1.bbox[3] - r1.bbox[1])
    area2 = (r2.bbox[2] - r2.bbox[0])*(r2.bbox[3] - r2.bbox[1])
    unionArea = area1 + area2 - intersectionArea
    overlapArea = intersectionArea*1.0/unionArea  # This should be greater than 0.5 to consider it as a valid detection.
    return overlapArea


# Results TP:25, FP:1420, TN:141532, FN:112 with 180 FNNI for 33 patients evaluated with 143089 patches
# Precision:1.7, Accuracy:98.9, Sensitivity:18.2, Specificity:99.0
# AUC: 0.4999


# FINAL CSV LOADING -----------------------------------------------------------------

INTERSECTION_AREA_TH = 0.1  # intersection/union to be considered matched region
PREDICTION_TH = 0.8  # prediction threshold

## Generate features, score for each BB and store them
tp, fp, fn, tn = 0, 0, 0, 0
fnni, patients_scored, total_rois = 0, 0, 0
real, pred = [], []  # for auc predictions
for idx, filename in enumerate(file_list):  # to extract form .csv
    if idx>10:
        break

    #filename = "luna_126631670596873065041988320084.npz"
    print "Patient %s (%d/%d)" % (filename, idx, len(file_list))

    if filename not in filenames_scored:
        if filename not in filenames_scored_full:
            print "++ Patient not scored"
            continue
        else:
            print "++ Patient with no acceptable candidates"

    # load patient
    patient = np.load(DATA_PATH + filename)['arr_0']
    if patient.shape[0]!=3:  # skip labels without ground truth
        print "++ Patient without ground truth"
        continue

    # candidate is going to be evaluated
    patients_scored +=1

    # track all the positive regions to compute the nodule regions not identified
    total_nodule_regions = []
    found_regions = set()
    for nslice in range(patient.shape[1]):
        if patient[2,nslice].any()!=0:
            regions = extract_regions_from_heatmap(patient[2,nslice])
            regions = [(nslice, r) for r in regions]
            total_nodule_regions.extend(regions)

    for idx, row in df_node[df_node['filename']==filename].iterrows():
        cx, cy, nslice = int(row['x']), int(row['y']), int(row['nslice'])
        score, rad = float(row['score']), int(ceil(row['diameter']/2.))

        # Get the ground truth regions
        if np.sum(patient[2,nslice]) != 0:  # if nodules in the slice, extract real regions

            regions_real = [r[1] for r in total_nodule_regions if r[0]==nslice]  # select regions for this slice
            candidate_region = AuxRegion([cx - rad, cy - rad, cx + rad + 1, cy + rad + 1])  # x1, y1, x2, y2
            intersections = [intersection_regions(candidate_region, nodule_region) for nodule_region in regions_real]
            intersection_area = max(intersections)

            if intersection_area >= INTERSECTION_AREA_TH:
                r = regions_real[np.argmax(intersections)]
                found_regions.add(r)

            # regions_real = extract_regions_from_heatmap(patient[2,nslice])
            # candidate_region = AuxRegion([cx - rad, cy - rad, cx + rad + 1, cy + rad + 1])  # x1, y1, x2, y2
            # intersection_area = max([intersection_regions(candidate_region, nodule_region) for nodule_region in regions_real])
        else:
            intersection_area = 0

        # auc
        real.append(int(intersection_area >= INTERSECTION_AREA_TH))
        pred.append(score)

        # confusion matrix
        if   intersection_area >= INTERSECTION_AREA_TH and score >  PREDICTION_TH:
            tp += 1
        elif intersection_area >= INTERSECTION_AREA_TH and score <= PREDICTION_TH:
            fn += 1
        elif intersection_area <  INTERSECTION_AREA_TH and score >  PREDICTION_TH:
            fp += 1
        elif intersection_area <  INTERSECTION_AREA_TH and score <= PREDICTION_TH:
            tn += 1

        # # remove region
        # if intersection_area >= INTERSECTION_AREA_TH and candidate_region in total_nodule_regions:
        #     total_nodule_regions.remove(candidate_region)


    num_rois = len(df_node[df_node['filename']==filename].index)
    total_rois += num_rois
    fnni += (len(total_nodule_regions) - len(found_regions))
    print "%d ROI candidates, %d real nodules, %d identified" % (num_rois, len(total_nodule_regions), len(found_regions))
    print "Results TP:%d, FP:%d, TN:%d, FN:%d with %d FNNI regions of %d ROIs candidates" % (tp,fp,tn,fn,fnni,num_rois)


print "Results TP:%d, FP:%d, TN:%d, FN:%d with %d FNNI for %d patients evaluated with %d patches" % (tp,fp,tn,fn,fnni,patients_scored,total_rois)
print "Precision:%.1f, Accuracy:%.1f, Sensitivity:%.1f, Specificity:%.1f" % (tp*100.0/(tp+fp), (tp+tn)*100.0/(tp+fp+tn+fn), tp*100.0/(tp+fn), tn*100.0/(tn+fp))
print "AUC: %.4f" % metrics.auc(real,pred,reorder=True)